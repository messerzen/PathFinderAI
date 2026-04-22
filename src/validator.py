"""
Post-generation validation utility.
Extracts all Strava activity IDs from the LLM output and verifies
they actually exist in the local database. Flags or strips any
hallucinated IDs before the response is shown to the user.
"""
import re
import logging
import sqlite3
import os

log = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strava_data.db")
_STRAVA_LINK_RE = re.compile(r"https://www\.strava\.com/activities/(\d+)")


def _ids_in_db(ids: list[str]) -> dict[str, bool]:
    """Returns a dict mapping each strava_id to True if it exists in the DB."""
    if not ids:
        return {}
    conn = sqlite3.connect(_DB_PATH)
    cur  = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT strava_id FROM activities WHERE strava_id IN ({placeholders})", ids
    )
    found = {row[0] for row in cur.fetchall()}
    conn.close()
    return {sid: sid in found for sid in ids}


def validate_and_clean(markdown: str) -> str:
    """
    Scans the LLM-generated markdown for Strava activity links.
    - Any link whose strava_id is found in the local DB → kept as-is.
    - Any link whose strava_id is NOT in the DB (hallucinated) → replaced
      with a visible warning so the user knows.
    Returns the cleaned markdown string plus a summary log.
    """
    found_ids = _STRAVA_LINK_RE.findall(markdown)
    if not found_ids:
        log.warning("[VALIDATOR] No Strava links found in output.")
        return markdown

    unique_ids = list(dict.fromkeys(found_ids))  # preserve order, deduplicate
    results    = _ids_in_db(unique_ids)

    hallucinated = [sid for sid, ok in results.items() if not ok]
    verified     = [sid for sid, ok in results.items() if ok]

    log.info(f"[VALIDATOR] Links found: {len(unique_ids)} | Verified: {len(verified)} | Hallucinated: {len(hallucinated)}")

    if not hallucinated:
        log.info("[VALIDATOR] All Strava links verified. ✓")
        return markdown

    # Replace each hallucinated link with a clear warning
    cleaned = markdown
    for sid in hallucinated:
        log.warning(f"[VALIDATOR] HALLUCINATED strava_id detected: {sid} — removing link.")
        bad_link = f"https://www.strava.com/activities/{sid}"
        warning  = f"[⚠️ Link removed — activity {sid} not found in your database]"
        cleaned  = cleaned.replace(bad_link, warning)

    # Append a validation note at the bottom
    cleaned += (
        f"\n\n---\n> **⚠️ Validation Warning:** {len(hallucinated)} Strava link(s) were generated "
        f"with IDs not found in your local database and have been removed: `{'`, `'.join(hallucinated)}`. "
        f"Only {len(verified)} link(s) were verified: `{'`, `'.join(verified)}`."
    )
    return cleaned
