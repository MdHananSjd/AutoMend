"""
AutoMend Orchestrator — Unit Tests

Uses FastAPI TestClient with mocked Firestore, Cloud Run, and diagnosis agent.
No live server or GCP credentials required.

Run from services/orchestrator/:
    python -m tests.test_unit
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ─── Mock Firestore ──────────────────────────────────────────────────────────

MOCK_INCIDENTS: dict[str, dict[str, Any]] = {}


class MockFirestoreClient:
    def create_incident(self, service_id: str, incident_id: str, failure_event: dict) -> None:
        MOCK_INCIDENTS[incident_id] = {
            "failure_event": failure_event,
            "recovery_decision": None,
            "action_taken": None,
            "verification_result": None,
            "outcome": None,
            "status": "received",
            "timestamps": {"received": "2026-01-01T00:00:00Z"},
        }

    def update_incident(self, service_id: str, incident_id: str, **fields: Any) -> None:
        if incident_id not in MOCK_INCIDENTS:
            MOCK_INCIDENTS[incident_id] = {"status": "unknown", "timestamps": {}}
        doc = MOCK_INCIDENTS[incident_id]
        for k, v in fields.items():
            if k == "status":
                doc["status"] = v.value if hasattr(v, "value") else v
                doc["timestamps"][doc["status"]] = "2026-01-01T00:00:00Z"
            else:
                doc[k] = v

    def get_active_incident(self, service_id: str) -> dict | None:
        for iid, doc in MOCK_INCIDENTS.items():
            if doc.get("failure_event", {}).get("service_id") != service_id:
                continue
            status = doc.get("status", "")
            if status not in ("recovered", "failed", "escalated"):
                return {**doc, "_id": iid}
        return None

    def list_incidents(self, service_id: str, limit: int = 50) -> list:
        return []

    def list_all_incidents(self, limit: int = 100) -> list:
        return []


def _mock_get_firestore_client():
    return MockFirestoreClient()


async def _mock_get_diagnosis(failure_event):
    from decision_client import _build_fallback_decision
    return _build_fallback_decision(failure_event)


def _mock_execute_action(decision):
    return {"action": decision.chosen_action.value, "success": True, "mocked": True}


async def _mock_verify_health(service_id=None):
    return {"healthy": True, "attempts": 1, "response": {"status": "ok"}, "error": None}


# ─── Apply patches before importing main ─────────────────────────────────────

patch("firestore_client.get_firestore_client", _mock_get_firestore_client).start()

from main import app

# Patch after import so main's local names get replaced
import main as _main_module
_main_module.get_diagnosis = _mock_get_diagnosis
_main_module.execute_action = _mock_execute_action
_main_module.verify_health = _mock_verify_health

from fastapi.testclient import TestClient
client = TestClient(app)

# ─── Test data ───────────────────────────────────────────────────────────────

CRASH_LOOP_EVENT = {
    "service_id": "automend-target",
    "revision_id": "automend-target-00002-abc",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "failure_type": "crash_loop",
    "log_snippet": "ERROR Container crashed with exit code 137\nINFO Restarting...",
    "metrics": {"error_rate": 1.0, "memory_mb": 512, "restart_count": 5},
    "last_known_good_revision": "automend-target-00001-xyz",
}


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "orchestrator"


class TestCreateIncident:
    def setup_method(self):
        MOCK_INCIDENTS.clear()

    def test_returns_202_with_incident_id(self):
        event = {**CRASH_LOOP_EVENT, "service_id": "test-202"}
        resp = client.post("/incidents", json=event)
        assert resp.status_code == 202
        body = resp.json()
        assert "incident_id" in body
        assert body["status"] == "received"

    def test_rejects_invalid_payload(self):
        resp = client.post("/incidents", json={"invalid": "payload"})
        assert resp.status_code == 422

    def test_rejects_unknown_failure_type(self):
        event = {**CRASH_LOOP_EVENT, "failure_type": "nonexistent_type"}
        resp = client.post("/incidents", json=event)
        assert resp.status_code == 422

    def test_creates_firestore_document(self):
        event = {**CRASH_LOOP_EVENT, "service_id": "test-doc"}
        resp = client.post("/incidents", json=event)
        incident_id = resp.json()["incident_id"]
        assert incident_id in MOCK_INCIDENTS
        doc = MOCK_INCIDENTS[incident_id]
        # The failure_event is stored correctly
        assert doc["failure_event"]["failure_type"] == "crash_loop"
        assert doc["failure_event"]["service_id"] == "test-doc"
        # The background pipeline runs to completion, so status will be "recovered"
        assert doc["status"] in ("received", "diagnosing", "action_taken", "verifying", "recovered")

    def test_idempotency_during_active_incident(self):
        """When an incident is already active for a service, duplicate events
        return the existing incident_id instead of creating a new one."""
        # Manually insert an active (non-terminal) incident
        MOCK_INCIDENTS["existing-inc-123"] = {
            "failure_event": {**CRASH_LOOP_EVENT, "service_id": "test-idempotent"},
            "status": "diagnosing",
            "timestamps": {"received": "2026-01-01T00:00:00Z"},
        }
        event = {**CRASH_LOOP_EVENT, "service_id": "test-idempotent"}
        resp = client.post("/incidents", json=event)
        assert resp.status_code == 202
        assert resp.json()["incident_id"] == "existing-inc-123"

    def test_different_services_get_different_incidents(self):
        event_a = {**CRASH_LOOP_EVENT, "service_id": "test-svc-a"}
        event_b = {**CRASH_LOOP_EVENT, "service_id": "test-svc-b"}
        resp1 = client.post("/incidents", json=event_a)
        resp2 = client.post("/incidents", json=event_b)
        assert resp1.json()["incident_id"] != resp2.json()["incident_id"]

    def test_background_pipeline_completes(self):
        """Verify the background pipeline runs through all stages to 'recovered'."""
        event = {**CRASH_LOOP_EVENT, "service_id": "test-pipeline"}
        resp = client.post("/incidents", json=event)
        incident_id = resp.json()["incident_id"]
        doc = MOCK_INCIDENTS[incident_id]
        # With mocked recovery, pipeline should complete to recovered
        assert doc["status"] == "recovered"
        assert doc["outcome"] == "recovered"
        assert doc["recovery_decision"] is not None
        assert doc["action_taken"] is not None
        assert doc["verification_result"] is not None


class TestListIncidents:
    def setup_method(self):
        MOCK_INCIDENTS.clear()

    def test_list_incidents_empty(self):
        resp = client.get("/incidents")
        assert resp.status_code == 200
        assert resp.json() == []


class TestIncidentModels:
    def test_failure_event_valid(self):
        from models import FailureEvent
        event = FailureEvent(**CRASH_LOOP_EVENT)
        assert event.service_id == "automend-target"
        assert event.failure_type.value == "crash_loop"

    def test_failure_event_all_types(self):
        from models import FailureEvent, FailureType
        for ft in FailureType:
            event = FailureEvent(**{**CRASH_LOOP_EVENT, "failure_type": ft.value})
            assert event.failure_type == ft

    def test_recovery_decision_valid(self):
        from models import RecoveryDecision, ChosenAction
        d = RecoveryDecision(
            service_id="test", diagnosed_cause="test", confidence=0.9,
            chosen_action=ChosenAction.ROLLBACK_TO_LAST_GOOD, reasoning="test",
        )
        assert d.chosen_action == ChosenAction.ROLLBACK_TO_LAST_GOOD

    def test_chosen_action_enum_completeness(self):
        from models import ChosenAction
        expected = {"rollback_to_last_good", "patch_env_var", "increase_memory_limit",
                    "restart_instance", "scale_down_instance"}
        assert {a.value for a in ChosenAction} == expected

    def test_failure_type_enum_completeness(self):
        from models import FailureType
        expected = {"crash_loop", "error_rate_spike", "memory_leak", "bad_deploy",
                    "health_check_failure", "dependency_failure"}
        assert {ft.value for ft in FailureType} == expected


class TestDecisionClientFallback:
    def setup_method(self):
        MOCK_INCIDENTS.clear()

    def test_fallback_uses_correct_action_per_type(self):
        from decision_client import _build_fallback_decision
        from models import FailureEvent, ChosenAction
        expected_map = {
            "crash_loop": ChosenAction.ROLLBACK_TO_LAST_GOOD,
            "bad_deploy": ChosenAction.ROLLBACK_TO_LAST_GOOD,
            "error_rate_spike": ChosenAction.INCREASE_MEMORY_LIMIT,
            "memory_leak": ChosenAction.INCREASE_MEMORY_LIMIT,
            "health_check_failure": ChosenAction.RESTART_INSTANCE,
            "dependency_failure": ChosenAction.RESTART_INSTANCE,
        }
        for ft, exp in expected_map.items():
            event = FailureEvent(**{**CRASH_LOOP_EVENT, "failure_type": ft})
            decision = _build_fallback_decision(event)
            assert decision.chosen_action == exp
            assert decision.confidence == 0.0

    def test_validate_decision_rejects_invalid_action(self):
        from decision_client import _validate_decision
        result = _validate_decision({
            "service_id": "test", "diagnosed_cause": "test", "confidence": 0.9,
            "chosen_action": "nonexistent_action", "action_params": {}, "reasoning": "test",
        })
        assert result is None

    def test_validate_decision_accepts_valid_action(self):
        from decision_client import _validate_decision
        result = _validate_decision({
            "service_id": "test", "diagnosed_cause": "test", "confidence": 0.9,
            "chosen_action": "rollback_to_last_good",
            "action_params": {"target_revision": "rev-1"}, "reasoning": "test",
        })
        assert result is not None
        assert result.chosen_action.value == "rollback_to_last_good"


class TestContractConsistency:
    def test_failure_event_matches_watcher_output(self):
        from models import FailureEvent
        watcher_keys = {"service_id", "revision_id", "timestamp", "failure_type",
                        "log_snippet", "metrics", "last_known_good_revision"}
        assert set(FailureEvent.model_fields.keys()) == watcher_keys

    def test_metrics_matches_spec(self):
        from models import Metrics
        assert set(Metrics.model_fields.keys()) == {"error_rate", "memory_mb", "restart_count"}

    def test_recovery_decision_matches_diagnosis_output(self):
        from models import RecoveryDecision
        expected = {"service_id", "diagnosed_cause", "confidence",
                    "chosen_action", "action_params", "reasoning"}
        assert set(RecoveryDecision.model_fields.keys()) == expected

    def test_action_params_matches_spec(self):
        from models import ActionParams
        assert set(ActionParams.model_fields.keys()) == {"target_revision", "env_key", "env_value", "memory_mb"}


# ─── Manual runner ───────────────────────────────────────────────────────────

def main():
    test_classes = [TestHealthEndpoint, TestCreateIncident, TestListIncidents,
                    TestIncidentModels, TestDecisionClientFallback, TestContractConsistency]
    passed = failed = 0
    errors = []
    for cls in test_classes:
        instance = cls()
        for method_name in sorted(m for m in dir(instance) if m.startswith("test_")):
            method = getattr(instance, method_name)
            try:
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                method()
                passed += 1
                print(f"  PASS  {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                errors.append((f"{cls.__name__}.{method_name}", e))
                print(f"  FAIL  {cls.__name__}.{method_name}: {e}")
    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed\n{'='*60}")
    if errors:
        for name, err in errors:
            print(f"  {name}: {err}")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
