import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from crewai import Task, Crew, Process

# Add root folder to sys.path so src.* imports work correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.workflow_crewai.agents import (
    profiler_agent,
    constraint_validator_agent,
    evaluator_agent,
    reflection_critic_agent,
    presenter_agent,
)
from src.strava_sync import sync_activities
from src.validator import validate_and_clean

load_dotenv()


def run_workflow(user_prompt: str):
    # ── 0. Sync latest Strava data ────────────────────────────────────────────
    sync_activities()

    # ── Setup dynamic logging ─────────────────────────────────────────────────
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(logs_dir, f"crewai_flow_{timestamp}.log")

    print("=" * 60)
    print(f"USER REQUEST: {user_prompt}")
    print(f"Logging to:   {log_filename}")
    print("=" * 60)

    # ── Task 1 — Profiler ─────────────────────────────────────────────────────
    profile_task = Task(
        description=(
            f"Analyze the following user request and extract structured, numeric cycling constraints.\n"
            f"USER REQUEST: '{user_prompt}'\n\n"
            "Extract as many of these as you can infer:\n"
            "• max_moving_time (seconds)\n"
            "• min_distance / max_distance (meters)\n"
            "• max_elevation_gain (meters)\n"
            "• fatigue_level: low / medium / high\n"
            "• effort_zone: easy / moderate / hard\n"
            "• outdoor_only: true / false\n"
            "• prefer_flat: true / false\n"
            "• target_calories (kcal, if mentioned)\n"
            "• suffer_score preference (if mentioned)"
        ),
        expected_output=(
            "A structured list of extracted constraints with values and units. "
            "Include a brief reasoning note for each inferred value."
        ),
        agent=profiler_agent,
    )

    # ── Task 2 — Constraint Validator ─────────────────────────────────────────
    validate_task = Task(
        description=(
            "Review the constraints extracted by the Profiler. "
            "Check for contradictions (e.g. high fatigue + hard effort) and resolve them with sensible defaults. "
            "Normalise all values to consistent units (meters, seconds). "
            "Fill smart defaults if missing: "
            "  • If fatigue is high but no suffer_score cap → assume suffer_score < 50. "
            "  • If effort is hard but no heartrate zone → assume average_heartrate > 140. "
            "  • If outdoor_only is true → add filter activity_type != 'VirtualRide' AND trainer = 0. "
            "Output the final, contradiction-free constraint set as a clean list."
        ),
        expected_output=(
            "A final, validated constraint set as a clean list: "
            "MAX_MOVING_TIME, MIN_DISTANCE, MAX_DISTANCE, MAX_ELEVATION, SUFFER_SCORE_MAX, "
            "HEARTRATE_MAX, OUTDOOR_ONLY, and any other active filters with their final values."
        ),
        agent=constraint_validator_agent,
        context=[profile_task],
    )

    # ── Task 3 — Evaluator ────────────────────────────────────────────────────
    evaluate_task = Task(
        description=(
            "Using the validated constraints from the Constraint Validator, write and execute ONE SQL query "
            "against the 'activities' SQLite table using the search_local_routes tool.\n\n"
            "Rules:\n"
            "• Always include in SELECT: strava_id, name, distance, elevation_gain, moving_time, "
            "  suffer_score, calories, average_heartrate, weighted_average_watts, pr_count\n"
            "• Exclude indoor/virtual unless user requested indoor\n"
            "• Apply all active filters from the validated constraints\n"
            "• Order intelligently based on the user's goal (flat → elevation_gain ASC, hard day → suffer_score DESC)\n"
            "• LIMIT 5 (the Critic will pick the best 3)"
        ),
        expected_output="The raw SQL results from search_local_routes (up to 5 routes with all requested fields).",
        agent=evaluator_agent,
        context=[validate_task],
    )

    # ── Task 4 — Reflection / Critic ──────────────────────────────────────────
    critic_task = Task(
        description=(
            "Review the SQL results from the Evaluator.\n\n"
            "Check:\n"
            "1. Are there at least 3 results? If fewer, the query is too strict.\n"
            "2. Are the routes meaningfully diverse in distance/elevation profile? "
            "   If all are virtually identical, the ranking needs adjustment.\n"
            "3. Did the query return 0 results? The constraints need relaxing.\n\n"
            "If results are poor, use search_local_routes to retry with relaxed constraints "
            "(widen distance window by 20%, raise elevation cap by 50%, remove heartrate/suffer_score filters). "
            "Retry up to 2 times. "
            "Output the final curated shortlist of exactly 3 routes with all rich fields."
        ),
        expected_output=(
            "A curated shortlist of exactly 3 routes, each including: strava_id, name, distance, "
            "elevation_gain, moving_time, suffer_score, calories, average_heartrate, "
            "weighted_average_watts, pr_count, and a note on why it was selected."
        ),
        agent=reflection_critic_agent,
        context=[evaluate_task],
    )

    # ── Task 5 — Presenter ────────────────────────────────────────────────────
    present_task = Task(
        description=(
            "Take the curated shortlist from the Critic and write a beautiful Markdown response "
            "in the voice of a warm, encouraging personal cycling coach.\n\n"
            "CRITICAL RULES — violation is not acceptable:\n"
            "• You MUST use ONLY the strava_id values that appear verbatim in the Critic's output.\n"
            "• NEVER invent, guess, modify, or generate any strava_id. If a strava_id is not explicitly \n"
            "  present in the data you received, do not create a Strava link for that route.\n"
            "• The Strava link format is: https://www.strava.com/activities/<strava_id>\n\n"
            "For each of the 3 routes include:\n"
            "• Route name as heading with a Strava link using the EXACT strava_id from the data\n"
            "• Distance (km) and Elevation Gain (m) — use EXACT values from the data\n"
            "• Estimated calorie burn — use EXACT value from the data\n"
            "• Suffer score and what it means for today's energy level\n"
            "• Heart rate zone insight (if average_heartrate available in the data)\n"
            "• A coach-voiced sentence explaining WHY this fits the user's physical state and goals\n"
            "• A 'Best for:' tag (e.g. 'Best for: flat endurance base', 'Best for: threshold power')\n\n"
            "Do NOT show raw SQL, database field names, or any data not present in the Critic's output."
        ),
        expected_output=(
            "A polished Markdown document with 3 route recommendations using ONLY data from the Critic's output. "
            "Each route has a verified Strava link (exact strava_id from data), calorie/suffer score, and a Best-for tag."
        ),
        agent=presenter_agent,
        context=[critic_task],
    )

    # ── Crew Assembly ─────────────────────────────────────────────────────────
    route_crew = Crew(
        agents=[
            profiler_agent,
            constraint_validator_agent,
            evaluator_agent,
            reflection_critic_agent,
            presenter_agent,
        ],
        tasks=[profile_task, validate_task, evaluate_task, critic_task, present_task],
        process=Process.sequential,
        verbose=True,
        output_log_file=log_filename,
    )

    result = route_crew.kickoff()
    validated_result = validate_and_clean(str(result))

    print("\n\n" + "=" * 60)
    print("FINAL RECOMMENDATIONS")
    print("=" * 60)
    print(validated_result)


if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "YOUR_GEMINI_API_KEY_HERE":
        print("CRITICAL ERROR: Please add your GEMINI_API_KEY to the .env file!")
        exit(1)

    sample_prompt = (
        "I would like to do a outdoor mountain bike ride tomorrow morning. I'm planning to start about 7:00 AM, "
        "but I need to be at home at 10 AM. I want more flat routes that don't have too much elevation gain. I want to ride outdoors. "
        "I want to cover high distance instead of high elevation."
    )
    run_workflow(sample_prompt)
