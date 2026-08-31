import asyncio
import logging
import json
import time
from typing import Dict
from fastapi import FastAPI
from app.config import Config
from app.gcp_client import GCPClient
from app.classifier import FailureClassifier
from app.orchestrator_client import OrchestratorClient

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s", "level":"%(levelname)s", "message":"%(message)s"}')
logger = logging.getLogger("watcher")

app = FastAPI(title="AutoMend Watcher")
client = GCPClient()

# Cooldown Map: Stores last reported timestamp per failure signature (revision_id + failure_type)
cooldown_tracker: Dict[str, float] = {}

@app.on_event("startup")
async def startup_event():
    logger.info(f"Watcher started. MOCK_MODE={Config.MOCK_MODE}, DISABLE_AUTH={Config.DISABLE_AUTH}")
    asyncio.create_task(watch_loop())

async def watch_loop():
    while True:
        try:
            logs, metrics, current_rev, lkgr = client.fetch_observability_data()
            
            # Check if any failure condition is present in logs or metrics
            failure_type_candidate = None
            if logs or metrics:
                # 1. DETECTED stage
                failure_event = FailureClassifier.classify(logs, metrics, current_rev, lkgr)
                
                if failure_event:
                    ftype = failure_event["failure_type"]
                    logger.warning(
                        f"[DETECTED] Failure anomaly observed in logs/metrics stream. Type: {ftype}",
                        extra={"extra_fields": {"stage": "DETECTED", "failure_type": ftype, "revision_id": current_rev}}
                    )
                    logger.info(
                        f"[CLASSIFIED] Failure rule matched: '{ftype}' for revision '{current_rev}' (LKGR: '{lkgr}')",
                        extra={"extra_fields": {"stage": "CLASSIFIED", "failure_type": ftype, "revision_id": current_rev, "lkgr": lkgr}}
                    )
                    logger.info(
                        f"[EVENT_BUILT] Failure Event contract constructed successfully for service '{failure_event['service_id']}'",
                        extra={"extra_fields": {"stage": "EVENT_BUILT", "failure_event": failure_event}}
                    )

                    signature = f"{failure_event['revision_id']}:{failure_event['failure_type']}"
                    last_sent = cooldown_tracker.get(signature, 0)
                    now = time.time()

                    if now - last_sent < Config.COOLDOWN_SEC:
                        logger.info(
                            f"Skipping duplicate incident dispatch for signature '{signature}'. "
                            f"Cooldown active ({int(Config.COOLDOWN_SEC - (now - last_sent))}s remaining)."
                        )
                    else:
                        logger.info(
                            f"[SENDING_TO_ORCHESTRATOR] Dispatching POST /incidents to Orchestrator at {Config.ORCHESTRATOR_URL}",
                            extra={"extra_fields": {"stage": "SENDING_TO_ORCHESTRATOR", "target_url": Config.ORCHESTRATOR_URL}}
                        )
                        
                        success, resp = await OrchestratorClient.send_incident(failure_event)
                        if success:
                            cooldown_tracker[signature] = now
                            inc_id = resp.get("incident_id", "unknown")
                            logger.info(
                                f"[INCIDENT_ACCEPTED] Incident '{inc_id}' acknowledged by Orchestrator with HTTP 202 Accepted",
                                extra={"extra_fields": {"stage": "INCIDENT_ACCEPTED", "incident_id": inc_id}}
                            )
                        else:
                            logger.error(
                                f"Failed to record incident with Orchestrator: {resp}",
                                extra={"extra_fields": {"stage": "DISPATCH_FAILED", "error": resp}}
                            )
                else:
                    logger.info("Service healthy. No failure signatures detected.")
            else:
                logger.info("Service healthy. Observability stream clean.")
                
        except Exception as e:
            logger.error(f"Error in Watcher loop (recovering automatically): {str(e)}")

        await asyncio.sleep(Config.POLL_INTERVAL_SEC)

@app.get("/health")
def health():
    return {"status": "watcher_running", "cooldown_entries": len(cooldown_tracker)}

@app.post("/reset")
def reset_cooldown():
    cooldown_tracker.clear()
    logger.info("Watcher cooldown state reset.", extra={"extra_fields": {"stage": "RESET", "status": "cooldown_cleared"}})
    return {"status": "watcher state reset successfully", "cooldown_entries": 0}