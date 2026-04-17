# Technical Architecture — PathFinderAI

## Overview

PathFinderAI is a **local-first AI recommendation engine** for cycling routes. It combines:
- A local SQLite database populated from the Strava API
- A 5-stage agentic LLM pipeline (implemented in both CrewAI and Pure Python)
- A post-generation safety validator (prevents hallucinated Strava links)
- Bike-type-aware SQL filtering using Strava's `sport_type` column

No user data is sent to any cloud database. The LLM receives only anonymised constraint values and anonymised query results.

---

## Data Layer

```
Strava API v3
     │
     ▼
src/auth.py                 ← OAuth 2.0 token refresh (reads from .env)
src/strava_sync.py          ← incremental sync engine
     │
     ▼
strava_data.db (SQLite)     ← all activity metadata + gpx_path pointers
     │
     └── data/bike/         ← outdoor bike GPX files (strava_<id>.gpx)
```

### Activity Model (`src/database.py`)

| Category | Fields |
|---|---|
| Identifiers | `strava_id`, `external_id`, `upload_id`, `resource_state` |
| Core | `name`, `distance`, `moving_time`, `elapsed_time`, `elevation_gain` |
| Activity Type | `activity_type` (legacy), `sport_type` (used for filtering) |
| Dates | `start_date`, `start_date_local`, `timezone`, `utc_offset` |
| Location | `start_latlng`, `end_latlng`, `polyline` |
| Power | `average_watts`, `weighted_average_watts` (NP), `max_watts`, `kilojoules` |
| Heart Rate | `average_heartrate`, `max_heartrate`, `has_heartrate` |
| Effort | `suffer_score`, `calories`, `workout_type`, `pr_count` |
| Boolean Flags | `trainer`, `commute`, `private`, `hide_from_home`, `leaderboard_opt_out` |
| JSON Blobs | `segment_efforts`, `splits_metric`, `laps`, `gear`, `photos`, `highlighted_kudosers` |
| Local | `gpx_path` — absolute path to the downloaded `.gpx` file |

### `sport_type` Values in Database

| Value | Description |
|---|---|
| `Ride` | Generic outdoor road/mountain bike ride |
| `MountainBikeRide` | Explicitly tagged MTB activity |
| `GravelRide` | Explicitly tagged gravel activity |
| `EBikeRide` | E-bike activity |
| `VirtualRide` | Indoor trainer / Zwift — **excluded by default** |

---

## Sync Engine

### Incremental Sync (`src/strava_sync.py`)

Called automatically at the start of every workflow run:

```python
if latest_date in DB:
    mode = "INCREMENTAL"       # fetch activities after latest start_date
else:
    mode = "FULL HISTORICAL"   # fetch all pages from Strava
```

### Full Sync Script (`scripts/full_sync.py`)

Designed for the one-time historical backfill (or periodic re-sync). Three phases:

**Phase 1 — Metadata sync:**
- Paginates `/athlete/activities` (100 per page)
- Fetches full activity detail from `/activities/{id}` for each new entry
- On insert, auto-sets `gpx_path` if a matching file already exists in `data/bike/`
- Saves all fields to SQLite via SQLAlchemy

**Phase 2 — GPX download (bike only):**
- Queries DB for `sport_type IN ('Ride', 'MountainBikeRide', 'GravelRide', 'EBikeRide', ...)`
- Excludes `VirtualRide` and `trainer=1`
- If the canonical file already exists at `data/bike/strava_<id>.gpx`, updates the DB path without re-downloading
- Calls `/activities/{id}/streams` for GPS data; builds and writes a valid `.gpx` file

**Phase 3 — Path repair (`--repair-paths`):**
- Scans all files in `data/bike/` matching `strava_<id>.gpx`
- Updates `gpx_path` in DB for any activity where the path is NULL, wrong, or stale
- Can run without a Strava token (pure local operation)

### Rate Limiting Strategy

Strava imposes (free tier, non-upload):
- `100 requests / 15-minute window`
- `1,000 requests / day`

The `RateLimiter` class reads `X-ReadRateLimit-Usage` and `X-ReadRateLimit-Limit` headers from **every** API response. When `window_remaining <= 5`, it calculates sleep time to the next natural boundary (`:00`, `:15`, `:30`, `:45`) and pauses automatically. When daily quota is within 10 requests, the script stops to preserve quota for the next run.

---

## 5-Agent Pipeline

### Bike-Type Filtering Logic

All agents are aware of the bike type specified by the user. The Evaluator translates this into SQL:

| User intent | `sport_type` SQL filter |
|---|---|
| Mountain bike | `IN ('Ride', 'MountainBikeRide')` |
| Gravel | `IN ('GravelRide', 'Ride')` |
| Not specified | All outdoor types (`VirtualRide` always excluded) |
| Indoor ride | Includes `VirtualRide`, no `trainer` exclusion |

### Dynamic Route Count

The workflow parses the requested number of routes from the user prompt:

```python
# "show me 7 options" → n_routes = 7
# "I want 3 routes"  → n_routes = 3
# (nothing)          → n_routes = 5  (default)
```

The count is threaded through all task descriptions: Evaluator fetches `n+2` candidates, Critic curates exactly `n`, Presenter formats exactly `n`.

### Agent Definitions (`src/workflow_crewai/agents.py`)

| Agent | Role | Key Logic |
|---|---|---|
| **Profiler** | Extracts structured constraints | NL → distance, time, fatigue, effort zone, bike type, route count |
| **Constraint Validator** | Sanity-checks + fills defaults | Detects contradictions; passes bike type through; fills smart defaults |
| **Evaluator** | Translates constraints → SQL | Applies `sport_type` filter; excludes `VirtualRide`; queries `activities` via tool |
| **Critic** | Quality + diversity check | Retries with relaxed SQL (up to 2x); **always preserves `sport_type` filters** |
| **Presenter** | Formats coach-voiced output | Uses exact data from Critic — no fabrication; only verified `strava_id` values |

### SQL Tool (`src/workflow_crewai/tools/database_tools.py`)

```python
@tool("Search Local Strava Routes")
def search_local_routes(sql_query: str) -> str:
    """Executes a SELECT query against the local activities table."""
```

The tool docstring exposes the full schema (including `sport_type`) to the LLM so it generates accurate, filterable SQL. Results always include `strava_id`.

### Ordering Strategy

| User intent | SQL `ORDER BY` |
|---|---|
| Flat ride | `elevation_gain ASC` |
| Hard day / goal ride | `suffer_score DESC` |
| Recovery | `suffer_score ASC` |
| High distance | `distance DESC` |

---

## Anti-Hallucination Validator (`src/validator.py`)

After the Presenter generates its response, before display:

```
1. Regex scan  →  extract all strava.com/activities/<id> links
2. Batch SQL   →  SELECT strava_id FROM activities WHERE strava_id IN (...)
3. For each ID:
   - Found in DB → keep link
   - Not found   → strip link + append ⚠️ warning note
```

This prevents the LLM from generating plausible-looking but fabricated Strava IDs.

---

## Pure Python Workflow (`src/workflow_pure/workflow.py`)

Implements the same 5-step logic without CrewAI, using direct Gemini API calls:

```python
constraints  = step_profiler(client, user_prompt)       # LLM → JSON
validated    = step_validator(client, constraints)      # LLM → JSON (fixed)
results, sql = step_evaluator(client, validated)        # LLM → SQL → execute
final_routes = step_critic(client, results, sql, ...)   # retry loop (max 2x)
output       = step_presenter(client, user_prompt, final_routes)
output       = validate_and_clean(output)               # hallucination check
```

### Critic Retry Logic

```python
for attempt in range(MAX_CRITIC_RETRIES + 1):   # max 2 retries
    if len(results) >= n_routes and diversity_ok:
        return results[:n_routes]                 # good enough
    # LLM generates a more permissive SQL:
    # - widens distance window by 20%
    # - raises elevation cap by 50%
    # - removes heartrate/suffer_score filters
    # - ALWAYS maintains sport_type filter
    results = run_sql(relaxed_sql)
```

---

## CI/CD Pipeline

### On every push/PR to `main`:
- `ci.yml` runs: Ruff linter, Python syntax check, core import check

### On PR merge to `main`:
- `release.yml` runs:
  1. Determines next semver (patch bump by default; minor if PR title contains `feat`; major if `breaking`)
  2. Appends new entry to `CHANGELOG.md` (PR title, number, author, date)
  3. Commits the updated changelog back to `main`
  4. Creates and pushes the new git tag
  5. Publishes a GitHub Release with the changelog section as release notes

---

## Logging

Every workflow run creates a unique timestamped log file:

```
logs/
├── crewai_flow_20260417_090000.log    # CrewAI run
├── pure_flow_20260417_090500.log      # Pure Python run
└── full_sync.log                      # Full sync operations
```

Logs capture: sync mode, each agent's decisions, SQL queries generated, `sport_type` filters applied, rate limit state, and the final recommendation including validator results.
