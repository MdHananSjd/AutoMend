import os
import json
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any
from app.config import Config
from tests.mock_data import MOCK_SCENARIOS

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
            scenario["last_known_good_revision"]
        )

    def _fetch_real_gcp_data(self) -> Tuple[List[Dict[str, Any]], Dict[str, float], str, str]:
        from google.cloud import logging as cloud_logging

        logs = []
        current_rev = "unknown"
        lkgr = "unknown"
        metrics = {
            "error_rate": 0.0,
            "memory_mb": 0,
            "restart_count": 0
        }

        try:
            log_client = cloud_logging.Client(project=Config.PROJECT_ID)
            
            # Query logs for the target Cloud Run service
            filter_str = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{Config.SERVICE_ID}"'
            entries = log_client.list_entries(filter_=filter_str, order_by=cloud_logging.DESCENDING, max_results=100)
            
            for entry in entries:
                # Extract revision_name from Cloud Run resource labels if available
                rev_label = entry.resource.labels.get("revision_name", "unknown") if entry.resource and entry.resource.labels else "unknown"
                
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
            # Log error gracefully and return safe default observability snapshot
            import logging
            logging.getLogger("watcher.gcp_client").error(f"GCP Observability fetch error (recovering): {err}")

        if current_rev == "unknown":
            current_rev = f"{Config.SERVICE_ID}-v1"
        if lkgr == "unknown":
            lkgr = current_rev

        return logs, metrics, current_rev, lkgr