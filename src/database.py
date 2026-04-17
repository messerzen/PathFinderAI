import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, JSON, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strava_data.db")
engine = create_engine(f"sqlite:///{DB_PATH}")

Base = declarative_base()

class Activity(Base):
    __tablename__ = 'activities'

    # ── Primary Keys & Identifiers ──────────────────────────────────────────
    id               = Column(Integer, primary_key=True)
    strava_id        = Column(String, unique=True, index=True)  # Strava activity ID (string for safety)
    resource_state   = Column(Integer, nullable=True)
    external_id      = Column(String, nullable=True)            # e.g. "garmin_push_12345"
    upload_id        = Column(String, nullable=True)            # stored as String to avoid int overflow

    # ── Core Activity Fields ────────────────────────────────────────────────
    name             = Column(String)
    distance         = Column(Float)              # meters
    moving_time      = Column(Integer)            # seconds
    elapsed_time     = Column(Integer)            # seconds
    elevation_gain   = Column(Float)              # total_elevation_gain in meters
    activity_type    = Column(String)             # "type" field (e.g. "Ride")
    sport_type       = Column(String)             # e.g. "MountainBikeRide"

    # ── Dates & Location ────────────────────────────────────────────────────
    start_date       = Column(DateTime)
    start_date_local = Column(DateTime)
    timezone         = Column(String)
    utc_offset       = Column(Integer)
    start_latlng     = Column(String)
    end_latlng       = Column(String)

    # ── Map ─────────────────────────────────────────────────────────────────
    polyline         = Column(String, nullable=True)  # summary_polyline

    # ── Boolean Flags ───────────────────────────────────────────────────────
    trainer          = Column(Boolean, nullable=True)
    commute          = Column(Boolean, nullable=True)
    manual           = Column(Boolean, nullable=True)
    private          = Column(Boolean, nullable=True)
    flagged          = Column(Boolean, nullable=True)
    from_accepted_tag = Column(Boolean, nullable=True)
    has_kudoed       = Column(Boolean, nullable=True)
    hide_from_home   = Column(Boolean, nullable=True)
    device_watts     = Column(Boolean, nullable=True)
    has_heartrate    = Column(Boolean, nullable=True)
    segment_leaderboard_opt_out = Column(Boolean, nullable=True)
    leaderboard_opt_out         = Column(Boolean, nullable=True)

    # ── Gear ────────────────────────────────────────────────────────────────
    gear_id          = Column(String, nullable=True)

    # ── Speed & Motion ──────────────────────────────────────────────────────
    average_speed    = Column(Float, nullable=True)   # m/s
    max_speed        = Column(Float, nullable=True)   # m/s

    # ── Power ───────────────────────────────────────────────────────────────
    average_watts          = Column(Float, nullable=True)
    weighted_average_watts = Column(Float, nullable=True)  # Normalised Power
    max_watts              = Column(Float, nullable=True)
    kilojoules             = Column(Float, nullable=True)

    # ── Heart Rate ──────────────────────────────────────────────────────────
    average_heartrate = Column(Float, nullable=True)  # bpm
    max_heartrate     = Column(Float, nullable=True)  # bpm

    # ── Cadence & Temp ──────────────────────────────────────────────────────
    average_cadence  = Column(Float, nullable=True)
    average_temp     = Column(Float, nullable=True)

    # ── Elevation Bounds ────────────────────────────────────────────────────
    elev_high        = Column(Float, nullable=True)
    elev_low         = Column(Float, nullable=True)

    # ── Engagement Counts ───────────────────────────────────────────────────
    achievement_count = Column(Integer, nullable=True)
    kudos_count       = Column(Integer, nullable=True)
    comment_count     = Column(Integer, nullable=True)
    athlete_count     = Column(Integer, nullable=True)
    photo_count       = Column(Integer, nullable=True)
    total_photo_count = Column(Integer, nullable=True)
    pr_count          = Column(Integer, nullable=True)

    # ── Effort & Nutrition ──────────────────────────────────────────────────
    suffer_score     = Column(Float, nullable=True)
    calories         = Column(Float, nullable=True)
    workout_type     = Column(Integer, nullable=True)

    # ── Metadata ────────────────────────────────────────────────────────────
    description      = Column(String, nullable=True)
    device_name      = Column(String, nullable=True)
    embed_token      = Column(String, nullable=True)

    # ── JSON Blobs (nested objects) ─────────────────────────────────────────
    segment_efforts  = Column(JSON, nullable=True)
    splits_metric    = Column(JSON, nullable=True)
    laps             = Column(JSON, nullable=True)
    gear             = Column(JSON, nullable=True)
    photos           = Column(JSON, nullable=True)
    highlighted_kudosers = Column(JSON, nullable=True)

    # ── Local File ──────────────────────────────────────────────────────────
    gpx_path         = Column(String, nullable=True)


Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()
