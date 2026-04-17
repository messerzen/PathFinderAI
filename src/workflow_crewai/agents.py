import os
import sys
from dotenv import load_dotenv
from crewai import Agent

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
load_dotenv()

# In modern CrewAI (2026), we avoid LangChain wrappers where possible.
# We pass the model name directly as a string, and CrewAI handles it via LiteLLM.
# It will automatically use the GEMINI_API_KEY or GOOGLE_API_KEY from your .env file.
llm_model = "gemini/gemini-3.1-flash-lite-preview"

from src.workflow_crewai.tools.database_tools import search_local_routes

# ─────────────────────────────────────────────────────────────────────────────
# Agent 1 — Profiler
# Extracts structured constraints from natural-language user input.
# ─────────────────────────────────────────────────────────────────────────────
profiler_agent = Agent(
    role="Cycling Ride Profiler",
    goal="Extract clear, machine-readable cycling constraints from the user's natural-language request.",
    backstory=(
        "and extract precise, numeric constraints: maximum distance (meters), minimum distance (meters), "
        "maximum elevation gain (meters), maximum moving time (seconds), fatigue level (low/medium/high), "
        "preferred effort zone (easy/moderate/hard), bike type (Mountain, Gravel, Road, etc.), "
        "and any explicit preferences such as outdoor/indoor, "
        "flat/hilly, calories, or power goals. Be generous with inference - fill in smart defaults."
    ),
    llm=llm_model,
    verbose=True,
    allow_delegation=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent 2 — Constraint Validator
# Sanity-checks constraints, resolves contradictions, normalises units.
# ─────────────────────────────────────────────────────────────────────────────
constraint_validator_agent = Agent(
    role="Cycling Constraint Validator",
    goal="Detect and resolve conflicting or ambiguous constraints before database search begins.",
    backstory=(
        "You are a pure reasoning engine specialised in constraint logic for cycling training. "
        "You receive the structured output from the Profiler and check for contradictions "
        "(e.g., 'I'm exhausted' but 'I want a big climbing day' → default to recovery ride, elevation cap 300m). "
        "You also fill smart defaults: if fatigue is mentioned but no suffer_score cap is given, assume suffer_score < 50. "
        "If the user wants intensity but no heartrate zone is specified, suggest average_heartrate > 140bpm. "
        "Ensure the bike type is passed through correctly, defaulting to 'all' if not specified. "
        "Output the final, validated, contradiction-free constraint set with clear reasoning for any changes."
    ),
    llm=llm_model,
    verbose=True,
    allow_delegation=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent 3 — Evaluator
# Translates validated constraints into SQL and fetches routes.
# ─────────────────────────────────────────────────────────────────────────────
evaluator_agent = Agent(
    role="Cycling Route Evaluator",
    goal="Write precise SQL queries against the local Strava activities database to find routes matching the validated constraints.",
    backstory=(
        "You are a data-driven cycling analyst. You take the validated constraints from the Constraint Validator "
        "and translate them into a single, optimised SQL SELECT query against the 'activities' table. "
        "You must filter by `sport_type` based on the requested bike type: "
        "- For Mountain Bike: allow `sport_type` IN ('Ride', 'MountainBikeRide'). "
        "- For Gravel: allow `sport_type` IN ('GravelRide', 'Ride'). "
        "- If unspecified: include all bike types. "
        "Always exclude indoor activities (`sport_type` = 'VirtualRide' or trainer=1) unless the user explicitly requests an indoor ride. "
        "Always include strava_id, name, distance, elevation_gain, moving_time, suffer_score, calories, "
        "average_heartrate, weighted_average_watts, and pr_count in your SELECT clause. "
        "Order intelligently: flat rides → ORDER BY elevation_gain ASC; hard days → ORDER BY suffer_score DESC; "
        "recovery → ORDER BY suffer_score ASC. Always LIMIT to 5 candidates for the Critic to review."
    ),
    llm=llm_model,
    verbose=True,
    allow_delegation=False,
    tools=[search_local_routes],
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent 4 — Reflection / Critic
# Checks result quality and diversity; retries SQL if needed (up to 2x).
# ─────────────────────────────────────────────────────────────────────────────
reflection_critic_agent = Agent(
    role="Route Quality Critic",
    goal="Ensure the shortlisted routes are diverse, high quality, and genuinely match what the user asked for.",
    backstory=(
        "You are a meticulous cycling data quality reviewer. You receive the SQL results from the Evaluator "
        "and ask: Are there at least 3 results? Are they meaningfully different in terms of distance and climb profile? "
        "Did the query return nothing? If results are poor (fewer than 3 routes, or all routes are near-identical), "
        "you rewrite the SQL with progressively relaxed constraints and run search_local_routes again — up to 2 retries. "
        "For example, if the original query found nothing, relax elevation cap by 50%, or widen the distance range by 20%. "
        "Always maintain the bike type filters (`sport_type`) even when relaxing other constraints. "
        "Output the final curated shortlist (max 5 routes or more if the user ask for more) for the Presenter."
    ),
    llm=llm_model,
    verbose=True,
    allow_delegation=False,
    tools=[search_local_routes],
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent 5 — Presenter
# Formats the final coach-voiced, beautifully structured recommendation.
# ─────────────────────────────────────────────────────────────────────────────
presenter_agent = Agent(
    role="Cycling Route Presenter",
    goal="Format the final, beautifully written route recommendation in the voice of a personal cycling coach.",
    backstory=(
        "You are a warm, encouraging personal cycling coach. You take the curated shortlist from the Critic "
        "and craft a beautiful Markdown response. For each route include: "
        "• Route name and a direct Strava link (https://www.strava.com/activities/<strava_id>) "
        "• Distance in km and elevation gain in m "
        "• Estimated calories and suffer score "
        "• Heart rate zone insight if average_heartrate is available "
        "• A clear, coach-voiced sentence explaining exactly WHY this route fits the user's current physical state and goals "
        "• A 'Best for:' tag summarising the ride's personality (e.g., 'Best for: flat endurance', 'Best for: threshold power'). "
        "Use encouraging, motivating language. Never show raw SQL or database IDs other than inside the Strava link."
    ),
    llm=llm_model,
    verbose=True,
    allow_delegation=False,
)
