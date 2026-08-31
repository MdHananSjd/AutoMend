import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import Config

class FailureClassifier:
    @staticmethod
    def classify(logs: List[Dict[str, Any]], metrics: Dict[str, float], current_rev: str, lkgr: str) -> Optional[Dict[str, Any]]:
        if not logs and not metrics:
            return None

        failure_type = None

        # 1. Evaluate explicit failure flags injected by debug endpoints or specific signatures
        for log in logs:
            if log.get("event_type") == "bad_deploy" or "Startup failed" in str(log.get("message", "")):
                failure_type = "bad_deploy"
                break
            if log.get("event_type") == "crash_loop":
                failure_type = "crash_loop"
                break
            if log.get("event_type") == "dependency_failure" or "Connection refused" in str(log.get("message", "")):
                failure_type = "dependency_failure"
                break

        # 2. Evaluate specific structural rules before generic error rates
        if not failure_type:
            health_failures = sum(1 for log in logs if log.get("path") == "/health" and log.get("status_code", 0) >= 500)
            
            if health_failures >= Config.CONSECUTIVE_HEALTH_FAILURES or any(l.get("event_type") == "health_check_failure" for l in logs):
                failure_type = "health_check_failure"
            elif metrics.get("memory_mb", 0) >= Config.MEMORY_MB_THRESHOLD or any(l.get("event_type") == "memory_leak" for l in logs):
                failure_type = "memory_leak"
            elif metrics.get("restart_count", 0) >= Config.CRASH_RESTART_THRESHOLD:
                failure_type = "crash_loop"
            else:
                # Count general HTTP 500s for error rate spikes
                error_count = sum(1 for log in logs if log.get("status_code", 0) >= 500)
                total_requests = sum(1 for log in logs if "status_code" in log)
                derived_error_rate = error_count / total_requests if total_requests > 0 else metrics.get("error_rate", 0)

                if derived_error_rate >= Config.ERROR_RATE_THRESHOLD:
                    failure_type = "error_rate_spike"

        if not failure_type:
            return None

        log_snippet = "\n".join([json.dumps(log) for log in logs[:50]])

        return {
            "service_id": Config.SERVICE_ID,
            "revision_id": current_rev,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failure_type": failure_type,
            "log_snippet": log_snippet,
            "metrics": {
                "error_rate": float(metrics.get("error_rate", 0.0)),
                "memory_mb": int(metrics.get("memory_mb", 0)),
                "restart_count": int(metrics.get("restart_count", 0))
            },
            "last_known_good_revision": lkgr
        }