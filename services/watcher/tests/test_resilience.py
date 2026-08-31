import pytest
from fastapi.testclient import TestClient
from app.main import app, cooldown_tracker
from app.gcp_client import GCPClient
from app.config import Config

client = TestClient(app)

def test_watcher_reset_endpoint():
    cooldown_tracker["rev-001:error_rate_spike"] = 123456.0
    assert len(cooldown_tracker) == 1

    response = client.post("/reset")
    assert response.status_code == 200
    assert response.json()["status"] == "watcher state reset successfully"
    assert len(cooldown_tracker) == 0

def test_watcher_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "watcher_running"

def test_gcp_client_resilience_on_exception(monkeypatch):
    Config.MOCK_MODE = False
    
    def mock_logging_client_failure(*args, **kwargs):
        raise RuntimeError("Simulated GCP Logging Service Unavailable")

    monkeypatch.setattr("google.cloud.logging.Client", mock_logging_client_failure)
    
    gcp = GCPClient()
    logs, metrics, current_rev, lkgr = gcp.fetch_observability_data()
    
    assert logs == []
    assert metrics == {"error_rate": 0.0, "memory_mb": 0, "restart_count": 0}
    assert current_rev != ""
    assert lkgr != ""
