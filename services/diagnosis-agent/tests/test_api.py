"""
HTTP-level test of POST /diagnose against the exact wire format in §4.2.
Needs fastapi + httpx installed (they weren't in the sandbox this was built
in, so this hasn't been executed — the offline pipeline tests cover the
same logic without the HTTP layer). Run with:

    pip install -r requirements.txt
    python3 -m pytest tests/test_api.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "failure_events.json").read_text())

client = TestClient(app)


def fake_call_gemini(event: dict) -> dict:
    return {
        "service_id": event["service_id"],
        "diagnosed_cause": "test",
        "confidence": 0.9,
        "chosen_action": "rollback_to_last_good",
        "action_params": {"target_revision": event["last_known_good_revision"]},
        "reasoning": "test",
    }


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_diagnose_happy_path():
    with patch("app.main.call_gemini", fake_call_gemini):
        resp = client.post("/diagnose", json=FIXTURES["crash_loop"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["chosen_action"] == "rollback_to_last_good"
    assert set(body.keys()) == {
        "service_id", "diagnosed_cause", "confidence",
        "chosen_action", "action_params", "reasoning",
    }


def test_diagnose_rejects_malformed_event():
    resp = client.post("/diagnose", json={"service_id": "x"})  # missing required fields
    assert resp.status_code in (422,)  # pydantic validation kicks in first


def test_diagnose_bad_model_output_still_returns_valid_shape():
    def bad_call(event: dict) -> dict:
        return {"chosen_action": "not_a_real_action"}

    with patch("app.main.call_gemini", bad_call):
        resp = client.post("/diagnose", json=FIXTURES["memory_leak"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["chosen_action"] in {
        "rollback_to_last_good", "patch_env_var", "increase_memory_limit",
        "restart_instance", "scale_down_instance",
    }


if __name__ == "__main__":
    test_health()
    test_diagnose_happy_path()
    test_diagnose_rejects_malformed_event()
    test_diagnose_bad_model_output_still_returns_valid_shape()
    print("all test_api.py checks passed")
