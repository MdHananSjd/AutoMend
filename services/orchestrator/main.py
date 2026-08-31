"""
AutoMend Orchestrator — FastAPI Application

The central coordinator. Receives Failure Events from the Watcher,
calls the Diagnosis Agent, executes recovery actions, verifies health,
and writes the full incident lifecycle to Firestore.

POST /incidents — accepts a Failure Event, returns 202 immediately,
                  then runs the recovery pipeline in the background.
GET  /health    — simple health check for Cloud Run readiness probes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from config import config
from decision_client import get_diagnosis
from firestore_client import get_firestore_client
from models import (
    IncidentStatus,
    TERMINAL_STATES,
    FailureEvent,
    IncidentAccepted,
    HealthResponse,
    RecoveryDecision,
    generate_incident_id,
    utcnow_iso,
)
from recovery import execute_action
from verification import verify_health

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("orchestrator")

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AutoMend Orchestrator",
    description="Receives failure events, coordinates diagnosis, recovery, and verification.",
    version="1.0.0",
)


# ─── POST /incidents ────────────────────────────────────────────────────────


@app.post("/incidents", response_model=IncidentAccepted, status_code=202)
async def create_incident(request: Request) -> IncidentAccepted:
    """Receive a Failure Event from the Watcher.

    Returns 202 Accepted immediately with an incident_id.
    The actual diagnosis → recovery → verification pipeline runs in the background
    so the Watcher's HTTP call is never blocked.
    """
    body = await request.json()

    # Parse and validate the incoming Failure Event
    try:
        failure_event = FailureEvent(**body)
    except Exception as e:
        logger.warning("Invalid Failure Event payload: %s", e)
        raise HTTPException(status_code=422, detail=f"Invalid Failure Event: {e}")

    fs = get_firestore_client()

    # ── Idempotency gate ──────────────────────────────────────────────
    # Check if there's already an active incident for this service
    active = fs.get_active_incident(failure_event.service_id)
    if active is not None:
        existing_id = active["_id"]
        existing_status = active.get("status", "unknown")
        logger.info(
            "Active incident %s already exists for service %s (status=%s), "
            "returning existing incident_id",
            existing_id,
            failure_event.service_id,
            existing_status,
        )
        return IncidentAccepted(
            incident_id=existing_id,
            status=existing_status,
        )

    # ── Create new incident ───────────────────────────────────────────
    incident_id = generate_incident_id()
    fs.create_incident(
        service_id=failure_event.service_id,
        incident_id=incident_id,
        failure_event=failure_event.model_dump(mode="json"),
    )

    logger.info(
        "Accepted incident %s for service %s (failure_type=%s)",
        incident_id,
        failure_event.service_id,
        failure_event.failure_type.value,
    )

    # ── Kick off the recovery pipeline in the background ──────────────
    # This runs after the 202 response is sent to the Watcher
    asyncio.create_task(
        _run_recovery_pipeline(failure_event, incident_id)
    )

    return IncidentAccepted(incident_id=incident_id, status="received")


# ─── Background Recovery Pipeline ───────────────────────────────────────────


async def _run_recovery_pipeline(
    failure_event: FailureEvent,
    incident_id: str,
) -> None:
    """The full recovery pipeline, run in the background after responding 202.

    Steps: diagnose → execute → verify → update outcome
    """
    fs = get_firestore_client()
    service_id = failure_event.service_id

    try:
        # ── Step 1: Diagnose ──────────────────────────────────────────
        fs.update_incident(
            service_id, incident_id, status=IncidentStatus.DIAGNOSING
        )
        logger.info("Step 1: Requesting diagnosis for incident %s", incident_id)

        decision = await get_diagnosis(failure_event)

        fs.update_incident(
            service_id,
            incident_id,
            recovery_decision=decision.model_dump(mode="json"),
        )
        logger.info(
            "Diagnosis received for %s: action=%s, cause=%s",
            incident_id,
            decision.chosen_action.value,
            decision.diagnosed_cause,
        )

        # ── Step 2: Execute action ────────────────────────────────────
        fs.update_incident(
            service_id, incident_id, status=IncidentStatus.ACTION_TAKEN
        )
        logger.info("Step 2: Executing action for incident %s", incident_id)

        action_result = execute_action(decision)

        fs.update_incident(
            service_id, incident_id, action_taken=action_result
        )

        if not action_result.get("success", False):
            # Action failed — mark as failed, skip verification
            logger.error(
                "Action failed for incident %s: %s",
                incident_id,
                action_result.get("error"),
            )
            fs.update_incident(
                service_id,
                incident_id,
                status=IncidentStatus.FAILED,
                outcome="failed",
            )
            return

        logger.info(
            "Action executed for %s: %s",
            incident_id,
            action_result.get("action"),
        )

        # ── Step 3: Verify ────────────────────────────────────────────
        fs.update_incident(
            service_id, incident_id, status=IncidentStatus.VERIFYING
        )
        logger.info("Step 3: Verifying health for incident %s", incident_id)

        verification = await verify_health(service_id=failure_event.service_id)

        fs.update_incident(
            service_id,
            incident_id,
            verification_result=verification,
        )

        # ── Step 4: Mark outcome ──────────────────────────────────────
        if verification.get("healthy", False):
            fs.update_incident(
                service_id,
                incident_id,
                status=IncidentStatus.RECOVERED,
                outcome="recovered",
            )
            logger.info("Incident %s: RECOVERED ✓", incident_id)
        else:
            fs.update_incident(
                service_id,
                incident_id,
                status=IncidentStatus.ESCALATED,
                outcome="escalated",
            )
            logger.warning(
                "Incident %s: ESCALATED (health check still failing after verification window)",
                incident_id,
            )

    except Exception as e:
        logger.error(
            "Unexpected error in recovery pipeline for incident %s: %s",
            incident_id,
            e,
            exc_info=True,
        )
        try:
            fs.update_incident(
                service_id,
                incident_id,
                status=IncidentStatus.FAILED,
                outcome="failed",
            )
        except Exception:
            logger.error("Failed to update incident status after pipeline error")


# ─── GET /health ────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health/readiness endpoint for Cloud Run."""
    return HealthResponse(status="ok", service="orchestrator")


# ─── GET /incidents (dashboard helper) ──────────────────────────────────────


@app.get("/incidents")
async def list_incidents(service_id: str | None = None, limit: int = 50):
    """List incidents — used by the dashboard or for debugging.

    If service_id is provided, returns incidents for that service.
    Otherwise, returns incidents across all services.
    """
    fs = get_firestore_client()
    if service_id:
        return fs.list_incidents(service_id, limit=limit)
    return fs.list_all_incidents(limit=limit)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )
