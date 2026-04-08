import json
from pathlib import Path

import jsonschema

BASE = Path(__file__).resolve().parents[1]


def load(name: str):
    return json.loads((BASE / "schemas" / name).read_text())


def test_call_result_schema_valid_example():
    schema = load("call_result.schema.json")
    sample = {
        "call_id": "123e4567-e89b-12d3-a456-426614174000",
        "direction": "inbound",
        "tenant_id": "tenant_example_001",
        "timestamp_start": "2026-03-11T15:00:00Z",
        "timestamp_end": "2026-03-11T15:01:00Z",
        "intent": {"name": "general_inquiry", "confidence": 0.9, "slots": {}},
        "action_required": "none",
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_transcript_event_schema_valid_example():
    schema = load("transcript_event.schema.json")
    sample = {
        "event_id": "123e4567-e89b-12d3-a456-426614174001",
        "call_id": "123e4567-e89b-12d3-a456-426614174000",
        "timestamp": "2026-03-11T15:00:10Z",
        "role": "user",
        "text": "Ich brauche einen Termin",
    }
    jsonschema.validate(instance=sample, schema=schema)
