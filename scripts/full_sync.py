"""
scripts/full_sync.py  —  One-time full historical sync for PathFinderAI
========================================================================
Phase 1 — Sync ALL activity metadata into SQLite
Phase 2 — Download GPX for outdoor BIKE activities only → data/bike/
Phase 3 — Repair gpx_path: scan data/bike/ and update DB for any stale/missing paths

All credentials are read exclusively from the .env file (never hardcoded).
Required .env keys: STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN

Respects Strava rate limits by reading X-ReadRateLimit headers on every
response and sleeping until the next 15-min window when approaching the limit.

Rate limits (Strava free tier, non-upload):
  100 requests per 15-minute window
  1,000 requests per day

Usage:
    python scripts/full_sync.py                 # Phase 1 + 2 + 3 (recommended first run)
    python scripts/full_sync.py --meta          # Phase 1 only (metadata sync)
    python scripts/full_sync.py --gpx           # Phase 2 only (GPX download)
    python scripts/full_sync.py --repair-paths  # Phase 3 only (fix stale gpx_path in DB)
"""
import os
import re
import sys
import time
import logging
import argparse
import sqlite3
import requests
import gpxpy.gpx
from datetime import datetime, timezone

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from src.auth import get_strava_access_token
from src.database import Base, engine, get_session, Activity
from sqlalchemy.exc import IntegrityError

# ── Directories ──────────────────────────────────────────────────────────────
BIKE_GPX_DIR = os.path.join(ROOT, "data", "bike")
DB_PATH      = os.path.join(ROOT, "strava_data.db")
os.makedirs(BIKE_GPX_DIR, exist_ok=True)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(ROOT, "logs", "full_sync.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Bike activity types that should have GPX downloaded ──────────────────────
BIKE_SPORT_TYPES = {
    "Ride", "MountainBikeRide", "GravelRide", "EBikeRide",
    "EMountainBikeRide", "CyclingRace",
}
# Always excluded from GPX download
INDOOR_SPORT_TYPES = {"VirtualRide"}


# ─────────────────────────────────────────────────────────────────────────────
# Rate-limit-aware request helper
# ─────────────────────────────────────────────────────────────────────────────
class RateLimiter:
    """
    Reads Strava X-ReadRateLimit-Usage/Limit headers from every response
    and sleeps until the next natural 15-min boundary when approaching the
    per-window cap (threshold: <= 5 remaining in window).
    """
    WINDOW_THRESHOLD = 5    # sleep when fewer than this many requests remain in window
    DAILY_THRESHOLD  = 10   # abort when fewer than this many daily requests remain

    def __init__(self):
        self.window_used  = 0
        self.window_limit = 100
        self.daily_used   = 0
        self.daily_limit  = 1000

    def update(self, response: requests.Response):
        """Parse rate limit headers from an HTTP response."""
        limits = response.headers.get("X-ReadRateLimit-Limit", "")
        usage  = response.headers.get("X-ReadRateLimit-Usage", "")
        if limits and usage:
            try:
                wl, dl = limits.split(",")
                wu, du = usage.split(",")
                self.window_limit = int(wl)
                self.daily_limit  = int(dl)
                self.window_used  = int(wu)
                self.daily_used   = int(du)
            except (ValueError, AttributeError):
                pass

    def window_remaining(self) -> int:
        return max(0, self.window_limit - self.window_used)

    def daily_remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_used)

    def log_status(self):
        log.info(
            f"  [RATE] window {self.window_used}/{self.window_limit} "
            f"| daily {self.daily_used}/{self.daily_limit} "
            f"| window remaining: {self.window_remaining()}"
        )

    def wait_for_next_window_if_needed(self):
        """If close to per-window cap, sleep until next :00/:15/:30/:45 boundary."""
        if self.window_remaining() > self.WINDOW_THRESHOLD:
            return

        now = datetime.now(timezone.utc)
        current_minute = now.minute
        next_boundary  = (current_minute // 15 + 1) * 15

        if next_boundary >= 60:
            sleep_seconds = (60 - current_minute) * 60 - now.second + 5
        else:
            sleep_seconds = (next_boundary - current_minute) * 60 - now.second + 5

        sleep_seconds = max(sleep_seconds, 10)
        log.warning(
            f"  [RATE] Window limit approached ({self.window_remaining()} left). "
            f"Sleeping {sleep_seconds}s until next window..."
        )
        time.sleep(sleep_seconds)

    def abort_if_daily_exhausted(self) -> bool:
        if self.daily_remaining() <= self.DAILY_THRESHOLD:
            log.error(
                f"  [RATE] Daily limit nearly exhausted ({self.daily_remaining()} remaining). "
                "Stopping to preserve quota. Resume tomorrow after midnight UTC."
            )
            return True
        return False


rl = RateLimiter()


def _get(url: str, headers: dict, params: dict = None) -> requests.Response | None:
    """Rate-limit-aware GET: updates limiter, waits if needed, returns response or None on error."""
    rl.wait_for_next_window_if_needed()

    resp = requests.get(url, headers=headers, params=params, verify=False)
    rl.update(resp)

    if resp.status_code == 429:
        log.warning("  [RATE] 429 received. Sleeping 15 minutes...")
        time.sleep(15 * 60 + 10)
        return None
    if resp.status_code != 200:
        log.error(f"  [HTTP {resp.status_code}] {url} — {resp.text[:200]}")
        return None
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _latlng_str(raw):
    return f"{raw[0]},{raw[1]}" if raw and len(raw) == 2 else ""


def _update_gpx_path(strava_id: str, filepath: str):
    """Update the gpx_path column in the DB for a given strava_id."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE activities SET gpx_path = ? WHERE strava_id = ?",
        (filepath, str(strava_id))
    )
    conn.commit()
    conn.close()


def _expected_gpx_path(strava_id: str) -> str:
    """Return the canonical expected GPX file path for a given strava_id."""
    return os.path.join(BIKE_GPX_DIR, f"strava_{strava_id}.gpx")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Sync all activity metadata
# ─────────────────────────────────────────────────────────────────────────────
def phase1_sync_metadata(token: str) -> int:
    log.info("=" * 60)
    log.info("PHASE 1 — Syncing all activity metadata to SQLite")
    log.info("=" * 60)

    session  = get_session()
    headers  = {"Authorization": f"Bearer {token}"}
    seen_ids = {str(row[0]) for row in session.query(Activity.strava_id).all()}
    log.info(f"  Activities already in DB: {len(seen_ids)}")

    new_count = 0
    page      = 1

    while True:
        if rl.abort_if_daily_exhausted():
            break

        log.info(f"  Fetching activity list — page {page}...")
        resp = _get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers=headers,
            params={"per_page": 100, "page": page},
        )
        if resp is None:
            log.warning("  Skipping page due to error. Waiting 5s...")
            time.sleep(5)
            continue

        activities = resp.json()
        rl.log_status()

        if not activities:
            log.info(f"  No more activities on page {page}. Phase 1 complete.")
            break

        log.info(f"  Page {page}: {len(activities)} returned.")

        for summary in activities:
            sid = str(summary["id"])
            if sid in seen_ids:
                continue

            if rl.abort_if_daily_exhausted():
                log.info("  Daily limit reached mid-page. Stopping.")
                break

            rl.wait_for_next_window_if_needed()

            detail_resp = _get(
                f"https://www.strava.com/api/v3/activities/{sid}",
                headers=headers,
            )
            if detail_resp is None:
                continue

            act = detail_resp.json()
            rl.log_status()

            # Determine if a GPX file already exists at the canonical path
            expected_path = _expected_gpx_path(sid)
            gpx_path_value = expected_path if os.path.exists(expected_path) else None

            db_activity = Activity(
                strava_id                   = sid,
                resource_state              = act.get("resource_state"),
                external_id                 = act.get("external_id"),
                upload_id                   = str(act.get("upload_id")) if act.get("upload_id") else None,
                name                        = act.get("name"),
                distance                    = act.get("distance"),
                moving_time                 = act.get("moving_time"),
                elapsed_time                = act.get("elapsed_time"),
                elevation_gain              = act.get("total_elevation_gain"),
                activity_type               = act.get("type"),
                sport_type                  = act.get("sport_type"),
                start_date                  = _parse_dt(act.get("start_date")),
                start_date_local            = _parse_dt(act.get("start_date_local")),
                timezone                    = act.get("timezone"),
                utc_offset                  = act.get("utc_offset"),
                start_latlng                = _latlng_str(act.get("start_latlng")),
                end_latlng                  = _latlng_str(act.get("end_latlng")),
                polyline                    = act.get("map", {}).get("summary_polyline") if act.get("map") else None,
                trainer                     = act.get("trainer"),
                commute                     = act.get("commute"),
                manual                      = act.get("manual"),
                private                     = act.get("private"),
                flagged                     = act.get("flagged"),
                from_accepted_tag           = act.get("from_accepted_tag"),
                has_kudoed                  = act.get("has_kudoed"),
                hide_from_home              = act.get("hide_from_home"),
                device_watts                = act.get("device_watts"),
                has_heartrate               = act.get("has_heartrate"),
                segment_leaderboard_opt_out = act.get("segment_leaderboard_opt_out"),
                leaderboard_opt_out         = act.get("leaderboard_opt_out"),
                gear_id                     = act.get("gear_id"),
                average_speed               = act.get("average_speed"),
                max_speed                   = act.get("max_speed"),
                average_watts               = act.get("average_watts"),
                weighted_average_watts      = act.get("weighted_average_watts"),
                max_watts                   = act.get("max_watts"),
                kilojoules                  = act.get("kilojoules"),
                average_heartrate           = act.get("average_heartrate"),
                max_heartrate               = act.get("max_heartrate"),
                average_cadence             = act.get("average_cadence"),
                average_temp                = act.get("average_temp"),
                elev_high                   = act.get("elev_high"),
                elev_low                    = act.get("elev_low"),
                achievement_count           = act.get("achievement_count"),
                kudos_count                 = act.get("kudos_count"),
                comment_count               = act.get("comment_count"),
                athlete_count               = act.get("athlete_count"),
                photo_count                 = act.get("photo_count"),
                total_photo_count           = act.get("total_photo_count"),
                pr_count                    = act.get("pr_count"),
                suffer_score                = act.get("suffer_score"),
                calories                    = act.get("calories"),
                workout_type                = act.get("workout_type"),
                description                 = act.get("description"),
                device_name                 = act.get("device_name"),
                embed_token                 = act.get("embed_token"),
                segment_efforts             = act.get("segment_efforts"),
                splits_metric               = act.get("splits_metric"),
                laps                        = act.get("laps"),
                gear                        = act.get("gear"),
                photos                      = act.get("photos"),
                highlighted_kudosers        = act.get("highlighted_kudosers"),
                gpx_path                    = gpx_path_value,
            )

            session.add(db_activity)
            try:
                session.commit()
                new_count += 1
                seen_ids.add(sid)
                log.info(f"    [{sid}] Saved: {act.get('name', '?')} (total new: {new_count})")
            except IntegrityError:
                session.rollback()
                seen_ids.add(sid)

        page += 1

    log.info(f"Phase 1 done. {new_count} new activities saved.")
    return new_count


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Download GPX for outdoor bike activities
# ─────────────────────────────────────────────────────────────────────────────
def phase2_download_bike_gpx(token: str):
    log.info("=" * 60)
    log.info("PHASE 2 — Downloading GPX for outdoor bike activities")
    log.info(f"Output folder: {BIKE_GPX_DIR}")
    log.info("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    placeholders = ",".join(f"'{t}'" for t in BIKE_SPORT_TYPES)
    excludes     = ",".join(f"'{t}'" for t in INDOOR_SPORT_TYPES)

    # Find all outdoor bike activities where the GPX file is missing or path is stale
    cur.execute(f"""
        SELECT strava_id, name, sport_type, gpx_path
        FROM activities
        WHERE sport_type IN ({placeholders})
          AND sport_type NOT IN ({excludes})
          AND (trainer = 0 OR trainer IS NULL)
        ORDER BY start_date DESC
    """)
    targets = cur.fetchall()
    conn.close()

    log.info(f"  Bike activities to check: {len(targets)}")

    headers = {"Authorization": f"Bearer {token}"}
    done    = 0
    skipped = 0
    errors  = 0

    for sid, name, sport_type, current_gpx_path in targets:
        if rl.abort_if_daily_exhausted():
            break

        expected_path = _expected_gpx_path(str(sid))

        # File already exists at the canonical location — just fix DB if needed
        if os.path.exists(expected_path):
            if current_gpx_path != expected_path:
                log.info(f"  [{sid}] File exists, updating stale DB path.")
                _update_gpx_path(str(sid), expected_path)
            else:
                log.info(f"  [{sid}] Already up to date. Skipping.")
            skipped += 1
            continue

        rl.wait_for_next_window_if_needed()

        resp = _get(
            f"https://www.strava.com/api/v3/activities/{sid}/streams",
            headers=headers,
            params={"keys": "latlng,time,altitude", "key_by_type": "true"},
        )
        rl.log_status()

        if resp is None:
            log.warning(f"  [{sid}] Stream request failed. Skipping.")
            errors += 1
            continue

        streams = resp.json()

        if "latlng" not in streams:
            log.info(f"  [{sid}] No GPS data (indoor or manual). Skipping GPX.")
            continue

        latlng_data = streams["latlng"]["data"]
        alt_data    = streams.get("altitude", {}).get("data")

        gpx     = gpxpy.gpx.GPX()
        track   = gpxpy.gpx.GPXTrack()
        segment = gpxpy.gpx.GPXTrackSegment()
        gpx.tracks.append(track)
        track.segments.append(segment)

        for i, (lat, lon) in enumerate(latlng_data):
            ele = alt_data[i] if alt_data else None
            segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=ele))

        with open(expected_path, "w") as f:
            f.write(gpx.to_xml())

        _update_gpx_path(str(sid), expected_path)
        done += 1
        log.info(f"  [{sid}] {name} ({sport_type}) — saved → {expected_path} (done: {done})")

    log.info(
        f"Phase 2 done. {done} GPX files downloaded, "
        f"{skipped} already existed, {errors} errors."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Repair gpx_path for all files already on disk
# ─────────────────────────────────────────────────────────────────────────────
def phase3_repair_paths():
    log.info("=" * 60)
    log.info("PHASE 3 — Repairing gpx_path for existing files in data/bike/")
    log.info("=" * 60)

    pattern = re.compile(r"strava_(\d+)\.gpx$")
    files   = os.listdir(BIKE_GPX_DIR)
    gpx_files = [f for f in files if pattern.match(f)]

    log.info(f"  Found {len(gpx_files)} GPX files in {BIKE_GPX_DIR}")

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT strava_id FROM activities")
    existing_ids = {str(row[0]) for row in cur.fetchall()}

    updated  = 0
    skipped  = 0
    no_match = 0

    for filename in gpx_files:
        m = pattern.match(filename)
        if not m:
            continue
        strava_id = m.group(1)

        if strava_id not in existing_ids:
            log.info(f"  [{strava_id}] Not found in DB. Skipping.")
            no_match += 1
            continue

        canonical_path = os.path.join(BIKE_GPX_DIR, filename)

        # Check current value
        cur.execute("SELECT gpx_path FROM activities WHERE strava_id = ?", (strava_id,))
        row = cur.fetchone()
        current_path = row[0] if row else None

        if current_path == canonical_path:
            skipped += 1
            continue

        conn.execute(
            "UPDATE activities SET gpx_path = ? WHERE strava_id = ?",
            (canonical_path, strava_id)
        )
        updated += 1

    conn.commit()
    conn.close()

    log.info(
        f"Phase 3 done. {updated} paths updated, "
        f"{skipped} already correct, {no_match} files with no DB match."
    )
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def _validate_env():
    """Ensure required env vars are set. All values come from .env — never hardcoded."""
    required = ["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        log.error(f"Missing required environment variables: {', '.join(missing)}")
        log.error("Copy .env.example to .env and fill in your Strava credentials.")
        sys.exit(1)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="PathFinderAI — full historical sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/full_sync.py                  Run all phases (recommended first run)
  python scripts/full_sync.py --meta           Phase 1 only: sync activity metadata
  python scripts/full_sync.py --gpx            Phase 2 only: download missing GPX files
  python scripts/full_sync.py --repair-paths   Phase 3 only: fix stale gpx_path in DB

Credentials are read from .env (see .env.example). Never hardcoded.
        """
    )
    parser.add_argument("--meta",         action="store_true", help="Phase 1 only — metadata sync")
    parser.add_argument("--gpx",          action="store_true", help="Phase 2 only — GPX download")
    parser.add_argument("--repair-paths", action="store_true", help="Phase 3 only — repair stale gpx_path values")
    args = parser.parse_args()

    run_all = not args.meta and not args.gpx and not args.repair_paths

    _validate_env()

    # Ensure DB schema is up to date
    Base.metadata.create_all(engine)

    log.info(f"PathFinderAI full sync — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("Rate limits: 100 req/15-min | 1000 req/day (headers-driven throttle active)")

    # Phase 3 (repair) can run without a token
    if args.repair_paths:
        phase3_repair_paths()
        sys.exit(0)

    token = get_strava_access_token()
    if not token:
        log.error("Could not obtain Strava access token. Check your .env credentials.")
        sys.exit(1)

    log.info("Strava access token obtained successfully.")

    if args.meta or run_all:
        phase1_sync_metadata(token)

    if args.gpx or run_all:
        phase2_download_bike_gpx(token)

    if run_all:
        # Always repair paths after a full sync to catch any edge cases
        phase3_repair_paths()

    log.info("=" * 60)
    log.info("Full sync complete.")
    log.info("=" * 60)
