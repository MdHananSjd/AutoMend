"""
AutoMend Orchestrator — Decision Client

Calls the Diagnosis Agent's POST /diagnose endpoint with a hard timeout.
Falls back to a deterministic rule-based decision if:
  - The call times out
  - The response is invalid
  - The network fails
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import config
from models import (
    ChosenAction,
    ActionParams,
    FailureEvent,
    FailureType,
    RecoveryDecision,
)

logger = logging.getLogger(__name__)


def _build_fallback_decision(failure_event: FailureEvent) -> RecoveryDecision:
    """Deterministic rule-based fallback when the Diagnosis Agent is unavailable.

    Maps each failure_type to the safest recovery action per the briefing.
    """
    logger.warning(
        "Using deterministic fallback for failure_type=%s on service %s",
        failure_event.failure_type.value,
        failure_event.service_id,
    )

    fallback_map: dict[FailureType, tuple[ChosenAction, ActionParams, str]] = {
        FailureType.CRASH_LOOP: (
            ChosenAction.ROLLBACK_TO_LAST_GOOD,
            ActionParams(target_revision=failure_event.last_known_good_revision),
            "Fallback: crash_loop defaults to rollback to last known good revision",
        ),
        FailureType.BAD_DEPLOY: (
            ChosenAction.ROLLBACK_TO_LAST_GOOD,
            ActionParams(target_revision=failure_event.last_known_good_revision),
            "Fallback: bad_deploy defaults to rollback to last known good revision",
        ),
        FailureType.ERROR_RATE_SPIKE: (
            ChosenAction.INCREASE_MEMORY_LIMIT,
            ActionParams(memory_mb=512),
            "Fallback: error_rate_spike defaults to increase memory limit",
        ),
        FailureType.MEMORY_LEAK: (
            ChosenAction.INCREASE_MEMORY_LIMIT,
            ActionParams(memory_mb=1024),
            "Fallback: memory_leak defaults to increase memory limit to 1024 MB",
        ),
        FailureType.HEALTH_CHECK_FAILURE: (
            ChosenAction.RESTART_INSTANCE,
            ActionParams(),
            "Fallback: health_check_failure defaults to restart instance",
        ),
        FailureType.DEPENDENCY_FAILURE: (
            ChosenAction.RESTART_INSTANCE,
            ActionParams(),
            "Fallback: dependency_failure defaults to restart instance",
        ),
    }

    action, params, reasoning = fallback_map.get(
        failure_event.failure_type,
        (
            ChosenAction.ROLLBACK_TO_LAST_GOOD,
            ActionParams(target_revision=failure_event.last_known_good_revision),
            "Fallback: unknown failure type, defaulting to rollback",
        ),
    )

    return RecoveryDecision(
        service_id=failure_event.service_id,
        diagnosed_cause=f"fallback-{failure_event.failure_type.value}",
        confidence=0.0,
        chosen_action=action,
        action_params=params,
        reasoning=reasoning,
    )


def _validate_decision(decision: dict[str, Any]) -> RecoveryDecision | None:
    """Validate that a raw decision dict conforms to the RecoveryDecision schema.

    Returns a validated RecoveryDecision, or None if invalid.
    """
    try:
        parsed = RecoveryDecision(**decision)
        # Extra check: chosen_action must be a valid enum value
        if not isinstance(parsed.chosen_action, ChosenAction):
            logger.warning("Invalid chosen_action: %s", parsed.chosen_action)
            return None
        return parsed
    except Exception as e:
        logger.warning("Failed to validate decision: %s", e)
        return None


async def get_diagnosis(failure_event: FailureEvent) -> RecoveryDecision:
    """Call the Diagnosis Agent's POST /diagnose endpoint.

    On timeout, network error, or invalid response, returns a deterministic
    fallback decision instead.
    """
    url = f"{config.DIAGNOSIS_AGENT_URL.rstrip('/')}/diagnose"
    payload = failure_event.model_dump(mode="json")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.DIAGNOSIS_TIMEOUT_SECONDS)
        ) as client:
            logger.info("Calling diagnosis agent at %s", url)
            response = await client.post(url, json=payload)

            if response.status_code != 200:
                logger.warning(
                    "Diagnosis agent returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return _build_fallback_decision(failure_event)

            raw_decision = response.json()
            validated = _validate_decision(raw_decision)
            if validated is None:
                logger.warning("Invalid decision from diagnosis agent: %s", raw_decision)
                return _build_fallback_decision(failure_event)

            logger.info(
                "Diagnosis: action=%s, cause=%s, confidence=%.2f",
                validated.chosen_action.value,
                validated.diagnosed_cause,
                validated.confidence,
            )
            return validated

    except httpx.TimeoutException:
        logger.warning(
            "Diagnosis agent timed out after %ds, using fallback",
            config.DIAGNOSIS_TIMEOUT_SECONDS,
        )
        return _build_fallback_decision(failure_event)

    except httpx.ConnectError as e:
        logger.warning("Cannot reach diagnosis agent: %s, using fallback", e)
        return _build_fallback_decision(failure_event)

    except Exception as e:
        logger.error("Unexpected error calling diagnosis agent: %s", e)
        return _build_fallback_decision(failure_event)
