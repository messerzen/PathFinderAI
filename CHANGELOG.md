# Changelog

All notable changes to PathFinderAI are documented in this file.  
This project follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.0.0] — 2026-04-16

### Added

#### Core Architecture
- 5-agent pipeline: **Profiler → Constraint Validator → Evaluator → Critic → Presenter**
- Two parallel implementations: **CrewAI workflow** (`src/workflow_crewai/`) and **Pure Python workflow** (`src/workflow_pure/`)
- Sequential task chaining with structured context passing between agents

#### Strava Integration
- Full Strava API v3 integration with OAuth 2.0 token refresh (`src/auth.py`)
- **Incremental sync** engine — fetches only new activities after the latest stored date (`src/strava_sync.py`)
- **Rate-limit-aware full sync** script — reads `X-ReadRateLimit` response headers and sleeps until the next 15-min window (`scratch/full_sync.py`)
- **Phase 1**: full metadata sync (all activity types)
- **Phase 2**: GPX download for outdoor bike activities only → `data/bike/`

#### Database
- SQLite database via SQLAlchemy ORM with a comprehensive `Activity` model
- Full Strava field coverage: power (avg/NP/max watts), heart rate, suffer score, calories, GPX path, segment efforts, laps, gear
- Schema migration utility (`scratch/alter_db.py`) and in-process rebuild tool (`scratch/rebuild_db.py`)

#### AI / Agent Features
- **Agent 1 — Profiler**: extracts numeric constraints (distance, time, elevation, fatigue, effort zone) from natural language
- **Agent 2 — Constraint Validator**: resolves contradictions (e.g. "exhausted" + "hard climb"), fills smart defaults (e.g. `suffer_score < 50` when fatigued)
- **Agent 3 — Evaluator**: generates optimised SQL queries with rich field ordering (flattest, hardest, recovery-friendly)
- **Agent 4 — Critic**: checks result diversity; retries with relaxed SQL constraints up to 2× if fewer than 3 routes are found
- **Agent 5 — Presenter**: generates coach-voiced Markdown recommendations with Strava links, calorie burn, effort zone, suffer score context
- **Post-generation validator** (`src/validator.py`): regex-scans every Strava link in LLM output and verifies the ID against the local DB before displaying — removes hallucinated links with a visible warning

#### Logging & Observability
- Timestamped log file per workflow run → `logs/crewai_flow_YYYYMMDD_HHMMSS.log`
- Sync-mode logging: `[FULL HISTORICAL]` vs `[INCREMENTAL]` clearly printed on every sync
- Per-page, per-activity progress logging during sync

#### DevOps / Repository
- GitHub Actions CI: lint (ruff) + import check on every push and PR
- GitHub Actions Release: automatic GitHub Release created on `v*.*.*` tags
- Comprehensive `README.md` with architecture diagram and quickstart
- `docs/ARCHITECTURE.md` — deep-dive technical reference
- `docs/SETUP.md` — step-by-step Strava OAuth + Gemini API setup guide
- `.env.example` — safe credentials template
