"""
FastAPI transport for the Diagnosis Agent.

Endpoints (per the brief):
  POST /diagnose  — §4.2. Caller: Orchestrator (C). Request body is the
                     Failure Event, response is the Recovery Decision.
  GET  /health     — "Every service exposes a basic health/readiness
                     endpoint" (Shared Rules, §8).

All the actual logic lives in diagnose_service.py / validation.py, which
have no FastAPI/pydantic dependency and are unit-tested without this file
in the loop. This file is intentionally thin.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.diagnose_service import diagnose
from app.gemini_client import call_gemini

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AutoMend Diagnosis Agent")


# --- Request/response models -------------------------------------------------
# These mirror the frozen contract in §4.2 for FastAPI's request validation
# and OpenAPI docs. The actual enforcement of chosen_action/confidence rules
# happens in validation.py regardless of what pydantic lets through here.

class Metrics(BaseModel):
    error_rate: float = 0.0
    memory_mb: float = 0.0
    restart_count: int = 0


class FailureEvent(BaseModel):
    service_id: str
    revision_id: str
    timestamp: str
    failure_type: str
    log_snippet: str = ""
    metrics: Metrics
    last_known_good_revision: str = ""


class ActionParams(BaseModel):
    target_revision: str = ""
    env_key: str = ""
    env_value: str = ""
    memory_mb: float = 0


class RecoveryDecision(BaseModel):
    service_id: str
    diagnosed_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    chosen_action: str
    action_params: ActionParams
    reasoning: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/diagnose", response_model=RecoveryDecision)
def post_diagnose(event: FailureEvent) -> dict:
    try:
        decision = diagnose(event.model_dump(), llm_call=call_gemini)
    except ValueError as exc:
        # Malformed Failure Event from the Orchestrator — this is a caller
        # bug, not something a fallback should paper over.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return decision
