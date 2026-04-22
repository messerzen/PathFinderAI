"""
Pure Python 5-Step Cycling Recommendation Workflow
====================================================
Step 1 — Profiler:             Extract structured constraints from user prompt
Step 2 — Constraint Validator: Detect contradictions, fill smart defaults
Step 3 — Evaluator:            Generate SQL query from validated constraints
Step 4 — Reflection / Critic:  Check result quality; retry with relaxed SQL if needed
Step 5 — Presenter:            Format final coach-voiced Markdown recommendation
"""
import os
import sys
import json
import logging
from datetime import datetime
from google import genai
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from src.validator import validate_and_clean

DB_PATH    = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "strava_data.db")
LOGS_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
MODEL_NAME = "gemini-3.1-flash-lite-preview"
MAX_CRITIC_RETRIES = 2


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_client() -> genai.Client:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        print("Error: GEMINI_API_KEY not found in .env")
        sys.exit(1)
    return genai.Client(api_key=api_key)


def llm_call(client: genai.Client, prompt: str) -> str:
    """Single LLM call with fallback."""
    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        return response.text
    except Exception as e:
        print(f"  [LLM Error] {e}")
        return ""


def parse_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return {}


def run_sql(sql: str) -> list[dict]:
    """Execute a SELECT query and return rows as list of dicts."""
    engine = create_engine(f"sqlite:///{DB_PATH}")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        print(f"  [SQL Error] {e}")
        return []


def setup_logging() -> str:
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = os.path.join(LOGS_DIR, f"pure_flow_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


# ── Step 1 — Profiler ─────────────────────────────────────────────────────────

def step_profiler(client: genai.Client, user_prompt: str) -> dict:
    logging.info("-- Step 1: Profiler ------------------------------------")
    prompt = f"""
You are an expert cycling coach. Extract ride constraints from the user prompt below.
Return ONLY a raw JSON object (no markdown). Include any fields you can infer:
  max_moving_time (seconds), min_distance (meters), max_distance (meters),
  max_elevation_gain (meters), fatigue_level (low/medium/high),
  effort_zone (easy/moderate/hard), outdoor_only (bool),
  prefer_flat (bool), target_calories (kcal), suffer_score_max (int, omit if not inferable).

USER PROMPT: '{user_prompt}'
"""
    raw = llm_call(client, prompt)
    constraints = parse_json(raw)
    logging.info(f"Profiler output: {json.dumps(constraints, indent=2)}")
    return constraints


# ── Step 2 — Constraint Validator ────────────────────────────────────────────

def step_validator(client: genai.Client, constraints: dict) -> dict:
    logging.info("-- Step 2: Constraint Validator -----------------------")
    prompt = f"""
You are a cycling constraint validator. Review the following constraints for contradictions and fill smart defaults.
Rules:
- If fatigue_level is 'high' and effort_zone is 'hard' → set effort_zone to 'easy', add note.
- If fatigue_level is 'high' and suffer_score_max is missing → set suffer_score_max = 50.
- If effort_zone is 'hard' and there is no heartrate guidance → set average_heartrate_min = 140.
- If outdoor_only is true → ensure activity_type filter excludes 'VirtualRide' and trainer = 0.
- If prefer_flat is true and max_elevation_gain is missing → set max_elevation_gain = 400.
- Ensure min_distance < max_distance; fix if not.
- Normalise all distances to meters and times to seconds.

Return ONLY a raw JSON of the corrected, final constraint set. Add a 'validator_notes' key listing any changes made.

INPUT CONSTRAINTS: {json.dumps(constraints, indent=2)}
"""
    raw = llm_call(client, prompt)
    validated = parse_json(raw)
    if not validated:
        validated = constraints  # fallback: use as-is
    notes = validated.pop("validator_notes", [])
    if notes:
        logging.info(f"Validator changes: {notes}")
    logging.info(f"Validated constraints: {json.dumps(validated, indent=2)}")
    return validated


# ── Step 3 — Evaluator ───────────────────────────────────────────────────────

def step_evaluator(client: genai.Client, validated: dict) -> list[dict]:
    logging.info("-- Step 3: Evaluator ----------------------------------")
    prompt = f"""
You are a SQL expert for cycling data. Given the validated constraints below, write ONE raw SQL SELECT query
against an SQLite table called 'activities'.

Schema columns you may use:
  strava_id, name, distance (FLOAT, meters), elevation_gain (FLOAT, meters),
  moving_time (INT, seconds), activity_type (VARCHAR), sport_type (VARCHAR),
  trainer (BOOLEAN), suffer_score (FLOAT), calories (FLOAT),
  average_heartrate (FLOAT, bpm), max_heartrate (FLOAT, bpm),
  average_watts (FLOAT), weighted_average_watts (FLOAT), pr_count (INT).

Rules:
- Always SELECT: strava_id, name, distance, elevation_gain, moving_time, suffer_score, calories, average_heartrate, weighted_average_watts, pr_count
- Apply all active filters from the constraints.
- Exclude VirtualRide and trainer=1 when outdoor_only is true.
- Order by: elevation_gain ASC if prefer_flat; suffer_score DESC if effort is hard; suffer_score ASC if fatigue is high.
- LIMIT 5.
- Return ONLY the raw SQL string, no markdown.

VALIDATED CONSTRAINTS: {json.dumps(validated, indent=2)}
"""
    sql = llm_call(client, prompt).strip().strip("```sql").strip("```").strip()
    logging.info(f"Generated SQL:\n{sql}")
    results = run_sql(sql)
    logging.info(f"Evaluator found {len(results)} routes.")
    return results, sql


# ── Step 4 — Reflection / Critic ─────────────────────────────────────────────

def step_critic(client: genai.Client, results: list[dict], original_sql: str, validated: dict) -> list[dict]:
    logging.info("-- Step 4: Reflection / Critic ------------------------")
    for attempt in range(MAX_CRITIC_RETRIES + 1):
        if len(results) >= 3:
            # Check diversity: distance spread > 10km across top 3
            distances = sorted([r.get("distance", 0) for r in results[:3]])
            spread = distances[-1] - distances[0] if len(distances) == 3 else 0
            if spread > 5000:  # at least 5km spread
                logging.info(f"Results are diverse (spread={spread/1000:.1f}km). Selecting top 3.")
                return results[:3]
            elif attempt == MAX_CRITIC_RETRIES:
                logging.info("Results not fully diverse but max retries reached. Using top 3.")
                return results[:3]

        if attempt >= MAX_CRITIC_RETRIES:
            logging.warning("Max critic retries reached. Using best available results.")
            return results[:3] if results else []

        logging.info(f"Critic retry {attempt + 1}/{MAX_CRITIC_RETRIES}: relaxing constraints...")
        prompt = f"""
You are a cycling data critic. The previous SQL query returned only {len(results)} routes, which is insufficient.
Original SQL:
{original_sql}

Write a NEW, more permissive SQL query that will return more results. Rules:
- Always SELECT: strava_id, name, distance, elevation_gain, moving_time, suffer_score, calories, average_heartrate, weighted_average_watts, pr_count
- Remove ALL numeric distance and suffer_score filters entirely.
- If elevation_gain was filtered, increase the cap by 50% (or remove it if it was <= 0).
- Keep the activity_type != 'VirtualRide' filter if it was present.
- Keep the trainer filter if it was present.
- Keep the moving_time filter if it was present and valid (> 0).
- LIMIT 5.
- Return ONLY the raw SQL string, no markdown, no explanation.
"""
        relaxed_sql = llm_call(client, prompt).strip().strip("```sql").strip("```").strip()
        logging.info(f"Relaxed SQL (attempt {attempt + 1}):\n{relaxed_sql}")
        results = run_sql(relaxed_sql)
        logging.info(f"Critic retry {attempt + 1} found {len(results)} routes.")

    return results[:3] if results else []


# ── Step 5 — Presenter ───────────────────────────────────────────────────────

def step_presenter(client: genai.Client, user_prompt: str, routes: list[dict]) -> str:
    logging.info("-- Step 5: Presenter ----------------------------------")
    if not routes:
        return "I couldn't find any routes matching your criteria, even after relaxing the constraints. Try a broader search or sync more Strava activities."

    routes_json = json.dumps(routes, indent=2, default=str)
    prompt = f"""
You are a warm, encouraging personal cycling coach. The user asked:
'{user_prompt}'

Here is the EXACT data from their Strava history that you MUST use:
{routes_json}

CRITICAL RULES — violation is not acceptable:
- You MUST use ONLY the strava_id values that appear in the JSON above. Do NOT invent, guess, or modify any strava_id.
- Build Strava links ONLY as: https://www.strava.com/activities/<strava_id> using the EXACT strava_id from the JSON.
- Use ONLY the distance, elevation_gain, calories, suffer_score, average_heartrate values from the JSON above.
- Do NOT generate, estimate, or modify any numeric values — use only what is in the data.

Write a beautiful Markdown response recommending these routes. For each route:
• Heading with the route name and a Strava link built from the EXACT strava_id in the data
• Distance in km (convert from meters) and elevation gain in m — from the data only
• Calories burned — from the data only (if null, omit this field)
• Suffer score context (if null, omit this field)
• Heart rate zone context if average_heartrate is present in the data
• One coach-voiced sentence explaining WHY this route fits their physical state and goals
• A 'Best for:' tag

Do NOT expose raw field names or database internals.
"""
    return llm_call(client, prompt)


# ── Main Workflow ─────────────────────────────────────────────────────────────

def run_workflow(user_prompt: str):
    log_path = setup_logging()
    logging.info("=" * 60)
    logging.info("PURE PYTHON 5-STEP WORKFLOW STARTING")
    logging.info(f"USER PROMPT: {user_prompt}")
    logging.info(f"Log file: {log_path}")
    logging.info("=" * 60)

    try:
        client = get_client()

        # Step 1 — Profiler
        constraints = step_profiler(client, user_prompt)

        # Step 2 — Validator
        validated = step_validator(client, constraints)

        # Step 3 — Evaluator
        results, sql = step_evaluator(client, validated)

        # Step 4 — Critic / Reflection loop
        final_routes = step_critic(client, results, sql, validated)

        # Step 5 — Presenter
        recommendation = step_presenter(client, user_prompt, final_routes)

        # Step 6 — Post-validation: verify all Strava links against local DB
        recommendation = validate_and_clean(recommendation)

        logging.info("\n\n" + "=" * 60)
        logging.info("FINAL RECOMMENDATIONS")
        logging.info("=" * 60)
        print(recommendation)
        logging.info(recommendation)

    except Exception as e:
        logging.error(f"Workflow encountered an error: {e}", exc_info=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sample_prompt = " ".join(sys.argv[1:])
    else:
        sample_prompt = (
            "I would like to do a bike tomorrow morning. I'm planning to start about 6:30 AM, "
            "but I need to be at home at 10 AM. I'm not sure I will have a good night of sleep, "
            "but now I'm feeling good. I want routes that don't have too much climb. I want to ride outdoors. "
            "I want to cover high distance instead of high elevation."
        )
    run_workflow(sample_prompt)
