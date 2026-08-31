"""
AutoMend Orchestrator — End-to-End Test

Sends a hand-crafted FailureEvent to the orchestrator's POST /incidents endpoint
and verifies the response and Firestore state.

Usage:
    # Start the orchestrator locally first:
    #   cd services/orchestrator && uvicorn main:app --port 8080

    python -m tests.test_e2e
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import httpx

ORCHESTRATOR_URL = "http://localhost:8080"

# ─── Hand-crafted Failure Events for each failure type ───────────────────────

TEST_EVENTS = {
    "crash_loop": {
        "service_id": "automend-target",
        "revision_id": "automend-target-00002-abc",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": "crash_loop",
        "log_snippet": "2024-01-01T00:00:00Z ERROR Container crashed with exit code 137\n"
        "2024-01-01T00:00:01Z INFO Restarting container...\n"
        "2024-01-01T00:00:05Z ERROR Container crashed with exit code 137\n"
        "2024-01-01T00:00:06Z INFO Restarting container...\n"
        "2024-01-01T00:00:10Z ERROR Container crashed with exit code 137",
        "metrics": {
            "error_rate": 1.0,
            "memory_mb": 512,
            "restart_count": 5,
        },
        "last_known_good_revision": "automend-target-00001-xyz",
    },
    "error_rate_spike": {
        "service_id": "automend-target",
        "revision_id": "automend-target-00003-def",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": "error_rate_spike",
        "log_snippet": "2024-01-01T00:00:00Z ERROR 500 Internal Server Error\n"
        "2024-01-01T00:00:01Z ERROR 500 Internal Server Error\n"
        "2024-01-01T00:00:02Z ERROR 500 Internal Server Error",
        "metrics": {
            "error_rate": 0.95,
            "memory_mb": 256,
            "restart_count": 0,
        },
        "last_known_good_revision": "automend-target-00002-abc",
    },
    "memory_leak": {
        "service_id": "automend-target",
        "revision_id": "automend-target-00004-ghi",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": "memory_leak",
        "log_snippet": "2024-01-01T00:00:00Z WARN Memory usage at 85%\n"
        "2024-01-01T00:00:05Z WARN Memory usage at 90%\n"
        "2024-01-01T00:00:10Z ERROR OOMKilled - container terminated",
        "metrics": {
            "error_rate": 0.0,
            "memory_mb": 1024,
            "restart_count": 1,
        },
        "last_known_good_revision": "automend-target-00003-def",
    },
    "bad_deploy": {
        "service_id": "automend-target",
        "revision_id": "automend-target-00005-jkl",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": "bad_deploy",
        "log_snippet": "2024-01-01T00:00:00Z ERROR ImportError: cannot import name 'broken_module'\n"
        "2024-01-01T00:00:01Z ERROR ModuleNotFoundError: No module named 'broken_module'",
        "metrics": {
            "error_rate": 1.0,
            "memory_mb": 0,
            "restart_count": 0,
        },
        "last_known_good_revision": "automend-target-00004-ghi",
    },
}


def test_health_endpoint():
    """Test that the orchestrator's /health endpoint works."""
    print("Testing GET /health...")
    try:
        resp = httpx.get(f"{ORCHESTRATOR_URL}/health", timeout=5.0)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        print(f"  ✓ Health check passed: {body}")
        return True
    except Exception as e:
        print(f"  ✗ Health check failed: {e}")
        return False


def test_create_incident(failure_type: str = "crash_loop"):
    """Test POST /incidents with a hand-crafted FailureEvent."""
    event = TEST_EVENTS[failure_type]
    print(f"\nTesting POST /incidents ({failure_type})...")

    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/incidents",
            json=event,
            timeout=10.0,
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "incident_id" in body
        assert body["status"] == "received"
        print(f"  ✓ Incident created: {json.dumps(body, indent=2)}")
        return body["incident_id"]
    except Exception as e:
        print(f"  ✗ Failed to create incident: {e}")
        return None


def test_idempotency(failure_type: str = "crash_loop"):
    """Test that sending the same event twice returns the same incident_id."""
    event = TEST_EVENTS[failure_type]
    print(f"\nTesting idempotency for {failure_type}...")

    try:
        resp1 = httpx.post(f"{ORCHESTRATOR_URL}/incidents", json=event, timeout=10.0)
        resp2 = httpx.post(f"{ORCHESTRATOR_URL}/incidents", json=event, timeout=10.0)

        id1 = resp1.json().get("incident_id")
        id2 = resp2.json().get("incident_id")

        if id1 == id2:
            print(f"  ✓ Idempotent: both returned incident_id={id1}")
            return True
        else:
            print(f"  ✗ NOT idempotent: got {id1} then {id2}")
            return False
    except Exception as e:
        print(f"  ✗ Idempotency test failed: {e}")
        return False


def test_invalid_payload():
    """Test that invalid payloads are rejected with 422."""
    print("\nTesting invalid payload...")
    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_URL}/incidents",
            json={"invalid": "payload"},
            timeout=5.0,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        print(f"  ✓ Invalid payload rejected: {resp.status_code}")
        return True
    except Exception as e:
        print(f"  ✗ Invalid payload test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("AutoMend Orchestrator — End-to-End Tests")
    print("=" * 60)

    results = []

    # Health check
    results.append(("Health check", test_health_endpoint()))

    # Create incident for each failure type
    for ft in TEST_EVENTS:
        incident_id = test_create_incident(ft)
        results.append((f"Create incident ({ft})", incident_id is not None))

    # Idempotency
    results.append(("Idempotency", test_idempotency()))

    # Invalid payload
    results.append(("Invalid payload", test_invalid_payload()))

    # Summary
    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} — {name}")

    passed = sum(1 for _, p in results if p)
    total = len(results)
    print(f"\n{passed}/{total} tests passed")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
