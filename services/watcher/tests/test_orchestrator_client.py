import pytest
from app.orchestrator_client import OrchestratorClient
from app.config import Config

pytestmark = pytest.mark.asyncio

MOCK_EVENT = {
    "service_id": "target-service-dev",
    "revision_id": "rev-001",
    "timestamp": "2026-08-31T12:00:00Z",
    "failure_type": "error_rate_spike",
    "log_snippet": "HTTP 500 Error observed",
    "metrics": {"error_rate": 0.8, "memory_mb": 45, "restart_count": 0},
    "last_known_good_revision": "rev-001"
}

async def test_successful_dispatch(httpx_mock):
    Config.ORCHESTRATOR_URL = "http://localhost:8080/incidents"
    Config.DISABLE_AUTH = True
    
    httpx_mock.add_response(
        url="http://localhost:8080/incidents",
        method="POST",
        status_code=202,
        json={"incident_id": "inc-test-123", "status": "received"}
    )

    success, resp = await OrchestratorClient.send_incident(MOCK_EVENT)
    assert success is True
    assert resp["incident_id"] == "inc-test-123"

async def test_retry_exhaustion_on_500(httpx_mock):
    Config.ORCHESTRATOR_URL = "http://localhost:8080/incidents"
    Config.DISABLE_AUTH = True
    Config.MAX_RETRIES = 3
    Config.INITIAL_BACKOFF_SEC = 0.01

    # Use is_reusable=True so the mocked 500 response can handle all retry attempts
    httpx_mock.add_response(
        url="http://localhost:8080/incidents",
        method="POST",
        status_code=500,
        text="Internal Server Error",
        is_reusable=True
    )

    success, resp = await OrchestratorClient.send_incident(MOCK_EVENT)
    assert success is False
    assert resp["error"] == "Retry limit reached"