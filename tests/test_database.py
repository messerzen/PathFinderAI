import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from src.database import Base, Activity

@pytest.fixture
def session():
    """Create an in-memory SQLite database and return a session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_create_activity(session):
    """Test that we can insert and retrieve an Activity."""
    act = Activity(
        strava_id="12345",
        name="Morning Ride",
        distance=10000.5,
        moving_time=3600,
        activity_type="Ride",
        sport_type="MountainBikeRide",
        start_date=datetime(2023, 10, 1, 8, 0, 0),
        trainer=False
    )
    session.add(act)
    session.commit()

    retrieved = session.query(Activity).filter_by(strava_id="12345").first()
    assert retrieved is not None
    assert retrieved.name == "Morning Ride"
    assert retrieved.distance == 10000.5
    assert retrieved.trainer is False

def test_unique_strava_id(session):
    """Test that strava_id must be unique."""
    act1 = Activity(strava_id="999", name="Ride 1")
    act2 = Activity(strava_id="999", name="Ride 2")
    
    session.add(act1)
    session.commit()
    
    session.add(act2)
    with pytest.raises(IntegrityError):
        session.commit()
