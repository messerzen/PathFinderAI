# Setup Guide — PathFinderAI

This guide walks you through obtaining a Strava refresh token and a Gemini API key, then running your first full sync and recommendation workflow.

---

## 1. Create a Strava API Application

1. Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
2. Fill in:
   - **Application Name**: PathFinderAI (or anything)
   - **Category**: Data Importer
   - **Website**: `http://localhost`
   - **Authorization Callback Domain**: `localhost`
3. Click **Create** — you will see your **Client ID** and **Client Secret**. Copy both.

---

## 2. Obtain a Refresh Token (OAuth 2.0)

Strava uses OAuth 2.0. You need to complete a one-time browser flow to get your `refresh_token`.

### Step 1 — Build the authorisation URL

Replace `YOUR_CLIENT_ID` with your actual Client ID:

```
https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&redirect_uri=http://localhost&response_type=code&scope=activity:read_all
```

Open this URL in your browser and click **Authorize**.

### Step 2 — Grab the code from the redirect

After authorising, your browser will redirect to something like:

```
http://localhost/?state=&code=abc123xyz&scope=read,activity:read_all
```

Copy the value of `code=` (in this example: `abc123xyz`).

### Step 3 — Exchange the code for tokens

Run this in your terminal (replace all placeholders):

```bash
curl -X POST https://www.strava.com/oauth/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=YOUR_CODE \
  -d grant_type=authorization_code
```

The response contains:

```json
{
  "access_token": "...",
  "refresh_token": "YOUR_REFRESH_TOKEN",
  "expires_at": 1234567890
}
```

Copy `refresh_token` — that is the value you need. It never expires unless you revoke access.

---

## 3. Get a Google Gemini API Key

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API Key**
3. Copy the key

> **Note on model availability:** Free-tier API keys have model-specific quotas. If you hit `429 RESOURCE_EXHAUSTED`, the tested working model for free tier as of April 2026 is `gemini-3.1-flash-lite-preview`.

---

## 4. Configure `.env`

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```env
STRAVA_CLIENT_ID=123456
STRAVA_CLIENT_SECRET=abc...
STRAVA_REFRESH_TOKEN=def...
GEMINI_API_KEY=AIza...
```

> **Security:** `.env` is listed in `.gitignore` and will never be committed to the repository. Never hardcode credentials in source files.

---

## 5. Install Dependencies

```bash
python -m venv .venv3_11
.venv3_11\Scripts\activate          # Windows
# source .venv3_11/bin/activate     # macOS/Linux

# For CrewAI workflow (recommended):
pip install -r requirements_crewai.txt

# For the lightweight Pure Python workflow:
pip install -r requirements_pure.txt
```

---

## 6. Initial Data Sync

### Full sync (recommended for first run)

```bash
python scripts/full_sync.py
```

This runs three phases automatically:

| Phase | What it does |
|---|---|
| **Phase 1 — Metadata** | Syncs all your Strava activity metadata to `strava_data.db` |
| **Phase 2 — GPX download** | Downloads GPS tracks for all outdoor bike activities to `data/bike/` |
| **Phase 3 — Path repair** | Ensures `gpx_path` in the DB points to the correct file for every activity |

This may take a while depending on how many Strava activities you have.
The script respects Strava's rate limits (100 requests / 15 min) and can be safely interrupted and resumed.

### Run individual phases

```bash
python scripts/full_sync.py --meta           # Phase 1 only: metadata sync
python scripts/full_sync.py --gpx            # Phase 2 only: GPX download
python scripts/full_sync.py --repair-paths   # Phase 3 only: fix stale paths (no token needed)
```

---

## 7. Run the Workflow

```bash
# CrewAI 5-agent workflow (recommended)
python src/workflow_crewai/workflow.py

# Lightweight pure Python workflow
python src/workflow_pure/workflow.py
```

You can also pass a custom prompt directly:

```bash
python src/workflow_crewai/workflow.py "I want a flat gravel ride on Saturday morning, about 3 hours, moderate effort."
```

### Prompt tips

The agent understands natural language. Try:

- **Bike type**: "mountain bike ride", "gravel ride", "road ride"
- **Distance/time**: "3-hour ride", "50km", "back home by noon"
- **Effort**: "easy recovery spin", "hard day", "I'm exhausted"
- **Route count**: "give me 3 options", "show me 7 routes"

---

## 8. Incremental Sync (ongoing use)

After the initial full sync, `strava_sync.py` is called automatically at the start of every workflow run. It fetches only new activities since the last stored date — no manual intervention required.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `429 RESOURCE_EXHAUSTED` on Gemini | Model quota exceeded | Use `gemini-3.1-flash-lite-preview` or wait for quota reset |
| `429 Too Many Requests` on Strava | Rate limit hit | `scripts/full_sync.py` handles this automatically |
| `No module named 'src'` | Wrong working directory | Always run commands from project root |
| `Error: GEMINI_API_KEY not found` | `.env` not configured | Copy `.env.example` → `.env` and fill in values |
| `Missing required environment variables` | Keys missing from `.env` | Run `scripts/full_sync.py` — it validates env vars and shows which are missing |
| `[MISSING] strava_id=...` in output | Hallucinated Strava link | The validator already removed it — this is expected when the LLM hallucinates |
| `gpx_path` pointing to wrong location | Files moved after initial sync | Run `python scripts/full_sync.py --repair-paths` to fix all paths |
