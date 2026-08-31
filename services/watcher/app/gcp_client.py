import os
import json
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any
from app.config import Config

# ─── Mock scenarios (used only when MOCK_MODE=true) ─────────────────────────
# Inlined here to avoid importing from tests/ — the tests/ directory is not
# present in the production container image.
MOCK_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "healthy": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 35, "restart_count": 0},
        "logs": [
            {"message": "Request processed successfully", "status_code": 200, "path": "/"},
            {"message": "Request processed successfully", "status_code": 200, "path": "/health"},
        ],
    },
    "error_rate_spike": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.85, "memory_mb": 40, "restart_count": 0},
        "logs": [
            {"message": "Request failure observed", "status_code": 500, "path": "/api/data", "event_type": "error_rate_spike"},
            {"message": "Request failure observed", "status_code": 500, "path": "/api/data"},
        ],
    },
    "memory_leak": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 850, "restart_count": 0},
        "logs": [{"message": "Failure injected", "event_type": "memory_leak"}],
    },
    "crash_loop": {
        "current_revision": "rev-002",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 0, "restart_count": 5},
        "logs": [{"message": "Crash loop state detected on startup. Crashing immediately.", "event_type": "crash_loop"}],
    },
    "bad_deploy": {
        "current_revision": "rev-003",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 0, "restart_count": 0},
        "logs": [{"message": "Startup failed: Invalid configuration detected", "event_type": "bad_deploy"}],
    },
    "health_check_failure": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 40, "restart_count": 0},
        "logs": [
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"},
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"},
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"},
        ],
    },
    "dependency_failure": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.1, "memory_mb": 40, "restart_count": 0},
        "logs": [{"message": "Database error: Connection refused to 10.0.0.5", "event_type": "dependency_failure"}],
    },
}


class GCPClient:
    """Fetches logs and metrics from Google Cloud Logging/Monitoring or Mocks."""

    def __init__(self):
        self.mock_scenario_index = os.getenv("MOCK_SCENARIO", "healthy")

    def fetch_observability_data(self) -> Tuple[List[Dict[str, Any]], Dict[str, float], str, str]:
        """Returns (logs, metrics, current_revision, last_known_good_revision)."""
        if Config.MOCK_MODE:
            return self._fetch_mock_data()
        return self._fetch_real_gcp_data()

    def _fetch_mock_data(self) -> Tuple[List[Dict[str, Any]], Dict[str, float], str, str]:
        scenario = MOCK_SCENARIOS.get(self.mock_scenario_index, MOCK_SCENARIOS["healthy"])
        return (
            scenario["logs"],
            scenario["metrics"],
            scenario["current_revision"],
            scenario["last_known_good_revision"],
        )

    def _fetch_real_gcp_data(self) -> Tuple[List[Dict[str, Any]], Dict[str, float], str, str]:
        from google.cloud import logging as cloud_logging

        logs: List[Dict[str, Any]] = []
        current_rev = "unknown"
        lkgr = "unknown"
        metrics: Dict[str, float] = {
            "error_rate": 0.0,
            "memory_mb": 0,
            "restart_count": 0,
        }

        try:
            log_client = cloud_logging.Client(project=Config.PROJECT_ID)

            filter_str = (
                f'resource.type="cloud_run_revision" '
                f'AND resource.labels.service_name="{Config.SERVICE_ID}"'
            )
            entries = log_client.list_entries(
                filter_=filter_str,
                order_by=cloud_logging.DESCENDING,
                max_results=100,
            )

            for entry in entries:
                rev_label = (
                    entry.resource.labels.get("revision_name", "unknown")
                    if entry.resource and entry.resource.labels
                    else "unknown"
                )

                if isinstance(entry.payload, dict):
                    log_data = dict(entry.payload)
                elif isinstance(entry.payload, str):
                    try:
                        log_data = json.loads(entry.payload)
                    except Exception:
                        log_data = {"message": entry.payload}
                else:
                    log_data = {"message": str(entry.payload or "")}

                log_rev = log_data.get("revision_id", rev_label)
                log_data["revision_id"] = log_rev

                if current_rev == "unknown" and log_rev != "unknown":
                    current_rev = log_rev

                # LKGR inference: find most recent healthy startup log
                if log_data.get("status") == "ready" and log_rev != "unknown":
                    if lkgr == "unknown":
                        lkgr = log_rev

                logs.append(log_data)
        except Exception as err:
            import logging
            logging.getLogger("watcher.gcp_client").error(
                f"GCP Observability fetch error (recovering): {err}"
            )

        if current_rev == "unknown":
            current_rev = f"{Config.SERVICE_ID}-v1"
        if lkgr == "unknown":
            lkgr = current_rev

        return logs, metrics, current_rev, lkgr
