"""
AutoMend Orchestrator — Data Models

Pydantic models matching the §4 API contracts exactly.
These are the single source of truth for field names, types, and enum values.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class FailureType(str, Enum):
    CRASH_LOOP = "crash_loop"
    ERROR_RATE_SPIKE = "error_rate_spike"
    MEMORY_LEAK = "memory_leak"
    BAD_DEPLOY = "bad_deploy"
    HEALTH_CHECK_FAILURE = "health_check_failure"
    DEPENDENCY_FAILURE = "dependency_failure"


class ChosenAction(str, Enum):
    ROLLBACK_TO_LAST_GOOD = "rollback_to_last_good"
    PATCH_ENV_VAR = "patch_env_var"
    INCREASE_MEMORY_LIMIT = "increase_memory_limit"
    RESTART_INSTANCE = "restart_instance"
    SCALE_DOWN_INSTANCE = "scale_down_instance"


class IncidentStatus(str, Enum):
    RECEIVED = "received"
    DIAGNOSING = "diagnosing"
    ACTION_TAKEN = "action_taken"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    FAILED = "failed"
    ESCALATED = "escalated"


# Terminal states — no further processing should happen
TERMINAL_STATES = {
    IncidentStatus.RECOVERED,
    IncidentStatus.FAILED,
    IncidentStatus.ESCALATED,
}


# ─── §4.1 Failure Event (Watcher → Orchestrator, POST /incidents body) ──────

class Metrics(BaseModel):
    error_rate: float = 0.0
    memory_mb: int = 0
    restart_count: int = 0


class FailureEvent(BaseModel):
    """Incoming failure event from the Watcher (§4.1)."""
    service_id: str
    revision_id: str
    timestamp: str  # ISO8601
    failure_type: FailureType
    log_snippet: str = ""
    metrics: Metrics = Field(default_factory=Metrics)
    last_known_good_revision: str = ""


# ─── §4.2 Recovery Decision (Diagnosis Agent → Orchestrator) ────────────────

class ActionParams(BaseModel):
    """Action-specific parameters — only the relevant fields are populated."""
    target_revision: str = ""
    env_key: str = ""
    env_value: str = ""
    memory_mb: int = 512


class RecoveryDecision(BaseModel):
    """Recovery decision from the Diagnosis Agent (§4.2)."""
    service_id: str
    diagnosed_cause: str = "unknown"
    confidence: float = 0.0
    chosen_action: ChosenAction
    action_params: ActionParams = Field(default_factory=ActionParams)
    reasoning: str = ""


# ─── §4.6 Firestore Incident Document ───────────────────────────────────────

class IncidentTimestamps(BaseModel):
    received: Optional[str] = None
    diagnosing: Optional[str] = None
    action_taken: Optional[str] = None
    verifying: Optional[str] = None
    recovered: Optional[str] = None
    failed: Optional[str] = None
    escalated: Optional[str] = None


class Incident(BaseModel):
    """Full incident document stored in Firestore (§4.6).

    Document path: services/{service_id}/incidents/{incident_id}
    """
    failure_event: Optional[dict[str, Any]] = None
    recovery_decision: Optional[dict[str, Any]] = None
    action_taken: Optional[dict[str, Any]] = None
    verification_result: Optional[dict[str, Any]] = None
    outcome: Optional[str] = None  # "recovered" | "failed" | "escalated"
    status: IncidentStatus = IncidentStatus.RECEIVED
    timestamps: IncidentTimestamps = Field(default_factory=IncidentTimestamps)


# ─── Request / Response helpers ──────────────────────────────────────────────

class IncidentAccepted(BaseModel):
    """202 Accepted response from POST /incidents."""
    incident_id: str
    status: str = "received"


class HealthResponse(BaseModel):
    """Response from GET /health on the orchestrator itself."""
    status: str = "ok"
    service: str = "orchestrator"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def generate_incident_id() -> str:
    """Generate a unique incident ID (uuid4 hex)."""
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    """Current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()
