import pytest
from unittest.mock import patch
from src.validator import validate_and_clean

@pytest.fixture
def mock_db():
    """Mock the DB check to control which IDs exist."""
    with patch("src.validator._ids_in_db") as mock:
        yield mock

def test_no_links(mock_db):
    """Markdown without Strava links should be untouched."""
    text = "Here is a great route with 500m of climbing."
    result = validate_and_clean(text)
    assert result == text
    mock_db.assert_not_called()

def test_valid_links(mock_db):
    """Valid links should remain untouched."""
    mock_db.return_value = {"123": True, "456": True}
    text = "Route 1: https://www.strava.com/activities/123\nRoute 2: https://www.strava.com/activities/456"
    result = validate_and_clean(text)
    assert "https://www.strava.com/activities/123" in result
    assert "Link removed" not in result

def test_hallucinated_links(mock_db):
    """Hallucinated links should be replaced with a warning."""
    mock_db.return_value = {"123": True, "999": False}
    text = "Valid: https://www.strava.com/activities/123\nFake: https://www.strava.com/activities/999"
    result = validate_and_clean(text)
    
    assert "https://www.strava.com/activities/123" in result
    assert "https://www.strava.com/activities/999" not in result
    assert "[Link removed" in result.replace("⚠️ ", "")
    assert "1 Strava link(s) were generated with IDs not found" in result
