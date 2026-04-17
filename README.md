# PathFinderAI 🚴

[![CI](https://github.com/messerzen/PathFinderAI/actions/workflows/ci.yml/badge.svg)](https://github.com/messerzen/PathFinderAI/actions/workflows/ci.yml)
[![Release](https://github.com/messerzen/PathFinderAI/actions/workflows/release.yml/badge.svg)](https://github.com/messerzen/PathFinderAI/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **An AI-powered cycling route recommendation engine** that connects to your personal Strava history, understands your physical state through natural language, and recommends the best routes for your next ride — powered by a 5-agent LLM pipeline running entirely on your machine.

---

## ✨ What it does

Describe your next ride in plain English:

> *"I want a flat mountain bike ride tomorrow morning. Starting at 7 AM, back by 10 AM. I want to cover as much distance as possible."*

PathFinderAI parses your intent, queries your **own Strava data locally**, and returns:

- 🗺️ **Top N routes** ranked by real data — distance, elevation gain, heart rate, suffer score
- 🔗 **Verified Strava links** — every activity ID is checked against your local database before display (no hallucinations)
- 🏋️ **Coach-voiced reasoning** — an explanation of *why* each route fits your physiology today
- 📊 **Rich metrics** — calorie burn, power (NP/AP), effort zone, and PR count for each suggestion
- 🚵 **Bike-type aware** — filters by Mountain Bike, Gravel, or Road rides based on your request

---

## 🏗️ Architecture

```
User Prompt
    │
    ▼
┌──────────────────────┐
│  Agent 1 — Profiler  │  NL → structured constraints (distance, time, fatigue, bike type)
└──────────┬───────────┘
           │
           ▼
┌────────────────────────────────┐
│  Agent 2 — Constraint Validator│  Detects contradictions, fills smart defaults
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────┐
│  Agent 3 — Evaluator   │  Writes SQL → queries local SQLite Strava cache
└──────────┬─────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Agent 4 — Critic/Reflection│  Validates diversity & coverage; retries with relaxed SQL
└──────────┬──────────────────┘
           │
           ▼
┌──────────────────────────┐
│  Agent 5 — Presenter     │  Generates coach-voiced Markdown recommendation
└──────────┬───────────────┘
           │
           ▼
┌────────────────────────────────────────────┐
│  Post-Generator Validator (validator.py)   │  Verifies all Strava IDs against local DB
└────────────────────────────────────────────┘
           │
           ▼
   Final Recommendation
```

Two parallel implementations are provided:

| | **CrewAI Workflow** | **Pure Python Workflow** |
|---|---|---|
| File | `src/workflow_crewai/workflow.py` | `src/workflow_pure/workflow.py` |
| Framework | CrewAI 1.x + LiteLLM | Google Gen AI SDK |
| Best for | Structured multi-agent orchestration with tool-use | Lightweight, full control, no framework overhead |

---

## 🔑 Key Features

| Feature | Detail |
|---|---|
| **Bike-type filtering** | Auto-filters `sport_type` by Mountain Bike (`Ride`, `MountainBikeRide`), Gravel (`GravelRide`, `Ride`), or all outdoor types |
| **Incremental sync** | Fetches only new Strava activities since the last stored date |
| **Full historical sync** | `scripts/full_sync.py` — rate-limit-aware 3-phase pipeline for first-time setup |
| **GPX path management** | Downloads and stores GPX for all outdoor bike activities; auto-repairs stale DB paths |
| **Anti-hallucination** | Post-generation validator regex-scans every Strava link and strips fake IDs |
| **Dynamic route count** | Returns 5 routes by default; parses user requests like "give me 3 options" |
| **Rate-limit-aware** | Reads `X-ReadRateLimit` headers and sleeps to the next 15-min window automatically |
| **Auto-release CI/CD** | Merging a PR to `main` triggers semver bump, CHANGELOG update, and GitHub Release |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| LLM Provider | Google Gemini (via `google-genai` SDK / LiteLLM) |
| Agent Framework | CrewAI 1.x |
| Database | SQLite + SQLAlchemy ORM |
| Strava Integration | Strava API v3 (OAuth 2.0) |
| GPX Processing | `gpxpy` |
| Runtime | Python 3.11+ |
| CI/CD | GitHub Actions |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- A [Strava API application](https://www.strava.com/settings/api)
- A [Google AI Studio API key](https://aistudio.google.com/app/apikey)

### 1. Clone & Install

```bash
git clone https://github.com/messerzen/PathFinderAI.git
cd PathFinderAI

python -m venv .venv3_11
.venv3_11\Scripts\activate          # Windows
# source .venv3_11/bin/activate     # macOS/Linux

pip install -r requirements_crewai.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
STRAVA_REFRESH_TOKEN=your_refresh_token
GEMINI_API_KEY=your_gemini_api_key
```

> See [docs/SETUP.md](docs/SETUP.md) for a full step-by-step guide to obtaining Strava OAuth tokens and Gemini API keys.

### 3. Initial Data Sync

```bash
# Full historical sync — all phases (recommended for first run)
python scripts/full_sync.py

# Or run individual phases:
python scripts/full_sync.py --meta          # Phase 1: sync all activity metadata
python scripts/full_sync.py --gpx           # Phase 2: download GPX for bike activities
python scripts/full_sync.py --repair-paths  # Phase 3: fix stale gpx_path in DB
```

The sync script respects Strava's rate limits (100 req / 15 min) automatically and can be resumed across sessions.

### 4. Run the Workflow

```bash
# CrewAI 5-agent workflow (recommended)
python src/workflow_crewai/workflow.py

# Lightweight pure Python workflow
python src/workflow_pure/workflow.py
```

Example with a custom prompt:

```bash
python src/workflow_crewai/workflow.py "I want a flat gravel ride this Saturday, about 3 hours, moderate effort."
```

---

## 📁 Project Structure

```
PathFinderAI/
├── src/
│   ├── auth.py                         # Strava OAuth 2.0 token refresh
│   ├── database.py                     # SQLAlchemy Activity model (all Strava fields)
│   ├── strava_sync.py                  # Incremental sync engine
│   ├── validator.py                    # Post-generation hallucination validator
│   ├── workflow_crewai/
│   │   ├── agents.py                   # 5 CrewAI agent definitions + bike-type logic
│   │   ├── workflow.py                 # Task orchestration, route count parsing, logging
│   │   └── tools/
│   │       └── database_tools.py       # @tool: SQL search against local activities DB
│   └── workflow_pure/
│       └── workflow.py                 # Pure Python 5-step pipeline (no framework)
├── scripts/
│   └── full_sync.py                    # 3-phase full historical sync (rate-limit-aware)
├── docs/
│   ├── ARCHITECTURE.md                 # Detailed technical architecture
│   └── SETUP.md                        # Strava OAuth + Gemini API setup walkthrough
├── .github/
│   └── workflows/
│       ├── ci.yml                      # Lint + syntax + import check on push/PR
│       └── release.yml                 # Auto-tag + CHANGELOG + GitHub Release on PR merge
├── .env.example                        # Template for environment variables
├── requirements_crewai.txt             # CrewAI workflow dependencies
├── requirements_pure.txt               # Pure Python workflow dependencies
├── CHANGELOG.md                        # Version history
└── README.md
```

---

## 🧪 Development

```bash
# Run linter
pip install ruff
ruff check src/ scripts/

# Verify core imports
python -c "from src.workflow_crewai.agents import profiler_agent; print('Agents OK')"
python -c "from src.database import Activity, Base; print('DB model OK')"
```

### CI/CD

Every PR to `main` runs:
1. **Ruff linter** — enforces code style
2. **Syntax check** — validates all `.py` files compile
3. **Import check** — verifies core modules load without errors

When a PR is **merged** to `main`:
1. Semver is auto-bumped (patch by default; minor if `feat` in PR title; major if `breaking`)
2. `CHANGELOG.md` is updated with the PR title and author
3. A git tag and GitHub Release are created automatically

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🤝 Acknowledgements

- [Strava API](https://developers.strava.com/) for athlete data access
- [CrewAI](https://www.crewai.com/) for the multi-agent orchestration framework
- [Google Gemini](https://ai.google.dev/) for the language model backbone
