import os
import sys
from crewai.tools import tool
from sqlalchemy import create_engine, text

# Add root folder to sys path so we can locate the sqlite db
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "strava_data.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

@tool("Search Local Strava Routes")
def search_local_routes(sql_query: str) -> str:
    """
    Useful to search local Strava activities from the SQLite database.
    The database table is called 'activities' with the following schema:
    - id (INTEGER)
    - strava_id (VARCHAR)
    - name (VARCHAR)
    - distance (FLOAT) - IN METERS
    - elevation_gain (FLOAT) - IN METERS
    - sport_type (VARCHAR)
    - start_date (DATETIME)
    - moving_time (INTEGER) - IN SECONDS
    - start_latlng (VARCHAR)
    
    You must provide ONLY a raw SQL SELECT query (e.g. `SELECT name, distance, elevation_gain FROM activities WHERE distance < 50000 AND sport_type IN ('Ride', 'MountainBikeRide') ORDER BY elevation_gain ASC LIMIT 5;`).
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_query))
            rows = result.fetchall()
            
            if not rows:
                return "0 routes found matching this query."
            
            # Format results
            res_str = ""
            for idx, row in enumerate(rows):
                res_str += f"Route {idx+1}: {dict(row._mapping)}\n"
            return res_str
    except Exception as e:
        return f"SQL Error: {str(e)}"
