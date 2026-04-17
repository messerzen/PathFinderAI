import os
import sys
import logging
import requests
import gpxpy.gpx
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from src.auth import get_strava_access_token
from src.database import get_session, Activity

# ── Logging ──────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [SYNC] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

# ── GPX Storage ──────────────────────────────────────────────────────────────
GPX_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gpx")
os.makedirs(GPX_DIR, exist_ok=True)


def download_gpx(activity_id, token):
    """Download GPS stream and save as GPX file. Returns filepath or None."""
    url     = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    headers = {"Authorization": f"Bearer {token}"}
    params  = {"keys": "latlng,time,altitude", "key_by_type": "true"}

    try:
        response = requests.get(url, headers=headers, params=params, verify=False)
        response.raise_for_status()
        streams = response.json()
    except requests.exceptions.RequestException as e:
        log.warning(f"[{activity_id}] Streams fetch error: {e}")
        return None

    if 'latlng' not in streams:
        log.info(f"[{activity_id}] No GPS stream (indoor or manual). Skipping GPX.")
        return None

    latlng_data = streams['latlng']['data']
    alt_data    = streams['altitude']['data'] if 'altitude' in streams else None

    gpx         = gpxpy.gpx.GPX()
    gpx_track   = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    for i, (lat, lon) in enumerate(latlng_data):
        ele = alt_data[i] if alt_data else None
        gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon, elevation=ele))

    filepath = os.path.join(GPX_DIR, f"strava_activity_{activity_id}.gpx")
    with open(filepath, 'w') as f:
        f.write(gpx.to_xml())

    return filepath


def _parse_dt(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _latlng_str(raw):
    if raw and len(raw) == 2:
        return f"{raw[0]},{raw[1]}"
    return ""


def sync_activities():
    """
    Incremental Strava sync:
    - If DB is empty  → full historical fetch (all pages)
    - If DB has data  → incremental fetch (only activities after latest start_date)
    Logs clearly which mode is being used and the result.
    """
    token = get_strava_access_token()
    if not token:
        log.error("Failed to obtain Strava access token. Sync aborted.")
        return

    session     = get_session()
    latest_date = session.query(func.max(Activity.start_date)).scalar()

    if latest_date:
        after_ts  = int(latest_date.timestamp())
        sync_mode = "INCREMENTAL"
        url_base  = f"https://www.strava.com/api/v3/athlete/activities?per_page=100&after={after_ts}"
        log.info(f"[{sync_mode}] Fetching new activities after {latest_date.strftime('%Y-%m-%d %H:%M:%S')} (ts={after_ts})")
    else:
        sync_mode = "FULL HISTORICAL"
        url_base  = "https://www.strava.com/api/v3/athlete/activities?per_page=100"
        log.info(f"[{sync_mode}] Database is empty — fetching ALL historical activities...")

    headers   = {"Authorization": f"Bearer {token}"}
    new_count = 0
    page      = 1

    while True:
        url = f"{url_base}&page={page}"
        log.info(f"  Fetching page {page}...")
        res = requests.get(url, headers=headers, verify=False)

        if res.status_code != 200:
            log.error(f"  API error {res.status_code}: {res.text}")
            break

        activities_data = res.json()
        if not activities_data:
            log.info(f"  No more activities on page {page}. Stopping.")
            break

        log.info(f"  Page {page}: {len(activities_data)} activities returned.")

        for act_summary in activities_data:
            strava_id_str = str(act_summary['id'])
            if session.query(Activity).filter_by(strava_id=strava_id_str).first():
                log.info(f"    [{strava_id_str}] Already in DB. Skipping.")
                continue

            # Fetch full activity detail
            detail_res = requests.get(
                f"https://www.strava.com/api/v3/activities/{strava_id_str}",
                headers=headers, verify=False
            )
            if detail_res.status_code != 200:
                log.warning(f"    [{strava_id_str}] Detail fetch failed ({detail_res.status_code}). Skipping.")
                continue

            act = detail_res.json()
            log.info(f"    [{strava_id_str}] {act.get('name', '(no name)')} — downloading GPX...")
            gpx_filepath = download_gpx(strava_id_str, token)

            db_activity = Activity(
                # Identifiers
                strava_id              = strava_id_str,
                resource_state         = act.get('resource_state'),
                external_id            = act.get('external_id'),
                upload_id              = str(act.get('upload_id')) if act.get('upload_id') else None,

                # Core
                name                   = act.get('name'),
                distance               = act.get('distance'),
                moving_time            = act.get('moving_time'),
                elapsed_time           = act.get('elapsed_time'),
                elevation_gain         = act.get('total_elevation_gain'),
                activity_type          = act.get('type'),
                sport_type             = act.get('sport_type'),

                # Dates & Location
                start_date             = _parse_dt(act.get('start_date')),
                start_date_local       = _parse_dt(act.get('start_date_local')),
                timezone               = act.get('timezone'),
                utc_offset             = act.get('utc_offset'),
                start_latlng           = _latlng_str(act.get('start_latlng')),
                end_latlng             = _latlng_str(act.get('end_latlng')),
                polyline               = act.get('map', {}).get('summary_polyline') if act.get('map') else None,

                # Boolean flags
                trainer                = act.get('trainer'),
                commute                = act.get('commute'),
                manual                 = act.get('manual'),
                private                = act.get('private'),
                flagged                = act.get('flagged'),
                from_accepted_tag      = act.get('from_accepted_tag'),
                has_kudoed             = act.get('has_kudoed'),
                hide_from_home         = act.get('hide_from_home'),
                device_watts           = act.get('device_watts'),
                has_heartrate          = act.get('has_heartrate'),
                segment_leaderboard_opt_out = act.get('segment_leaderboard_opt_out'),
                leaderboard_opt_out    = act.get('leaderboard_opt_out'),

                # Gear
                gear_id                = act.get('gear_id'),

                # Speed
                average_speed          = act.get('average_speed'),
                max_speed              = act.get('max_speed'),

                # Power
                average_watts          = act.get('average_watts'),
                weighted_average_watts = act.get('weighted_average_watts'),
                max_watts              = act.get('max_watts'),
                kilojoules             = act.get('kilojoules'),

                # Heart Rate
                average_heartrate      = act.get('average_heartrate'),
                max_heartrate          = act.get('max_heartrate'),

                # Cadence & Temp
                average_cadence        = act.get('average_cadence'),
                average_temp           = act.get('average_temp'),

                # Elevation bounds
                elev_high              = act.get('elev_high'),
                elev_low               = act.get('elev_low'),

                # Engagement
                achievement_count      = act.get('achievement_count'),
                kudos_count            = act.get('kudos_count'),
                comment_count          = act.get('comment_count'),
                athlete_count          = act.get('athlete_count'),
                photo_count            = act.get('photo_count'),
                total_photo_count      = act.get('total_photo_count'),
                pr_count               = act.get('pr_count'),

                # Effort & Nutrition
                suffer_score           = act.get('suffer_score'),
                calories               = act.get('calories'),
                workout_type           = act.get('workout_type'),

                # Metadata
                description            = act.get('description'),
                device_name            = act.get('device_name'),
                embed_token            = act.get('embed_token'),

                # JSON blobs
                segment_efforts        = act.get('segment_efforts'),
                splits_metric          = act.get('splits_metric'),
                laps                   = act.get('laps'),
                gear                   = act.get('gear'),
                photos                 = act.get('photos'),
                highlighted_kudosers   = act.get('highlighted_kudosers'),

                # Local
                gpx_path               = gpx_filepath,
            )

            session.add(db_activity)
            try:
                session.commit()
                new_count += 1
                log.info(f"    [{strava_id_str}] Saved. (Total new: {new_count})")
            except IntegrityError:
                session.rollback()
                log.warning(f"    [{strava_id_str}] Duplicate on commit. Rolled back.")

        page += 1

    log.info(f"[{sync_mode}] Sync complete. {new_count} new activities added to DB.")


if __name__ == '__main__':
    sync_activities()
