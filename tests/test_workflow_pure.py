import pytest
from src.workflow_pure.workflow import parse_json

def test_parse_json_valid():
    raw = '```json\n{"distance": 5000, "effort": "hard"}\n```'
    parsed = parse_json(raw)
    assert parsed == {"distance": 5000, "effort": "hard"}

def test_parse_json_no_markdown():
    raw = '{"fatigue_level": "low"}'
    parsed = parse_json(raw)
    assert parsed == {"fatigue_level": "low"}

def test_parse_json_invalid():
    raw = 'This is just some text.'
    parsed = parse_json(raw)
    assert parsed == {}
