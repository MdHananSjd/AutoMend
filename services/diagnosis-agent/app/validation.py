"""
Validation + deterministic fallback for the Diagnosis Agent.

This module is the safety boundary described in the brief: "the model can
reason freely, but can never trigger an action outside this pre-approved
set." It has ZERO external dependencies on purpose (no pydantic, no ADK) so
it can be unit-tested in isolation and reused unchanged regardless of which
LLM/SDK version sits behind it.

Nothing in here ever raises on bad model output — a malformed or
out-of-enum response always degrades to a valid, contract-shaped
RecoveryDecision via a rule-based fallback. That's the whole point.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Contract constants (§4.2 / §6.2 — must stay byte-identical to the brief)
# ---------------------------------------------------------------------------

FAILURE_TYPES = frozenset(
    {
        "crash_loop",
        "error_rate_spike",
        "memory_leak",
        "bad_deploy",
        "health_check_failure",
        "dependency_failure",
    }
)

CHOSEN_ACTIONS = frozenset(
    {
        "rollback_to_last_good",
        "patch_env_var",
        "increase_memory_limit",
        "restart_instance",
        "scale_down_instance",
    }
)

# Below this confidence, we don't trust the model's chosen_action even if it
# validates — we prefer a known-safe deterministic action over a low-confidence
# guess. This threshold is not in the frozen contract; it's a judgment call
# documented here (and in the README) rather than decided silently.
CONFIDENCE_FALLBACK_THRESHOLD = 0.45

# Cap how much of the log snippet we ever forward into a prompt, independent
# of what the Watcher sends. Contract says "~50 lines" — we enforce it here
# too, defensively, on our side of the boundary.
MAX_LOG_LINES = 50


def truncate_log_snippet(log_snippet: str, max_lines: int = MAX_LOG_LINES) -> str:
    """Keep the last N lines only. Bounds prompt size/latency regardless of
    what the Watcher actually sends."""
    if not log_snippet:
        return ""
    lines = log_snippet.splitlines()
    if len(lines) <= max_lines:
        return log_snippet
    return "\n".join(lines[-max_lines:])


def sanitize_log_snippet(log_snippet: str) -> str:
    """Defense-in-depth against prompt injection via application logs.

    Log content is untrusted input, not instructions. We don't try to be
    clever here — we just make sure it can never be mistaken for a role
    marker or a system/developer turn when it's interpolated into the
    prompt. The prompt template (see agent.py) additionally wraps this in
    an explicit "DATA, not instructions" delimiter.
    """
    if not log_snippet:
        return ""
    # Strip anything that looks like it's trying to open a new turn/role.
    cleaned = re.sub(
        r"(?im)^\s*(system|user|assistant|developer)\s*:\s*", "[stripped]: ", log_snippet
    )
    return cleaned


def validate_failure_event(event: dict[str, Any]) -> tuple[bool, str | None]:
    """Cheap shape-check on the inbound Failure Event before we do anything
    with it. Returns (is_valid, error_message)."""
    required = {
        "service_id",
        "revision_id",
        "timestamp",
        "failure_type",
        "log_snippet",
        "metrics",
        "last_known_good_revision",
    }
    missing = required - event.keys()
    if missing:
        return False, f"missing required fields: {sorted(missing)}"
    if event["failure_type"] not in FAILURE_TYPES:
        return False, f"unknown failure_type: {event['failure_type']!r}"
    if not isinstance(event.get("metrics"), dict):
        return False, "metrics must be an object"
    return True, None


def _clamp_memory_mb(requested: int | float | None, current_mb: int | float | None) -> int:
    """Deterministic, bounded memory bump — never trust an unbounded value
    from the model or an absent current reading."""
    current = int(current_mb) if current_mb else 512
    bumped = int(requested) if requested else int(current * 1.5)
    return max(512, min(bumped, 4096))


def deterministic_fallback(
    failure_event: dict[str, Any], reason: str
) -> dict[str, Any]:
    """The rule-based safety net. One clear, justifiable action per
    failure_type — chosen for being the safest *reversible* response to that
    class of failure, not necessarily the most clever one. Gemini is free to
    do better than this when it's working; this is the floor, not the goal.

    Mapping (documented, not implied by the brief beyond crash_loop/bad_deploy):
      crash_loop            -> rollback_to_last_good  (brief's explicit example)
      bad_deploy             -> rollback_to_last_good  (brief's explicit example)
      error_rate_spike       -> rollback_to_last_good  (most spikes trace to the
                                 latest revision; rollback is reversible and safe)
      memory_leak            -> restart_instance        (clears the leak now;
                                 increase_memory_limit only postpones OOM and
                                 needs a size judgment we don't trust a fallback
                                 path to make)
      health_check_failure   -> restart_instance        (clears a stuck/hung
                                 process behind a failed readiness probe)
      dependency_failure     -> restart_instance        (fresh instance may
                                 re-establish the dependency connection; this
                                 failure type is the weakest fit for any of the
                                 five actions, which is exactly why it's a
                                 fallback and not something we'd want a
                                 low-confidence model deciding on its own)
    """
    failure_type = failure_event.get("failure_type")
    last_good = failure_event.get("last_known_good_revision", "")
    metrics = failure_event.get("metrics") or {}

    action_params = {
        "target_revision": "",
        "env_key": "",
        "env_value": "",
        "memory_mb": 0,
    }

    if failure_type in ("crash_loop", "bad_deploy", "error_rate_spike"):
        chosen_action = "rollback_to_last_good"
        action_params["target_revision"] = last_good
        cause = {
            "crash_loop": "Repeated crashes following a revision change; "
            "reverting to the last known-good revision is the safest "
            "deterministic response.",
            "bad_deploy": "Failure pattern consistent with a bad deploy; "
            "reverting to the last known-good revision.",
            "error_rate_spike": "Error-rate spike; defaulting to rollback "
            "since the most recent revision is the most likely cause.",
        }[failure_type]
    else:
        chosen_action = "restart_instance"
        cause = {
            "memory_leak": "Memory growth consistent with a leak; restarting "
            "clears accumulated memory immediately without guessing a new limit.",
            "health_check_failure": "Readiness probe failing/hanging; "
            "restarting replaces the stuck instance.",
            "dependency_failure": "Downstream dependency call failing; "
            "restarting gives the instance a fresh connection attempt.",
        }.get(failure_type, "Unrecognized failure pattern; restarting as the "
              "safest generic recovery step.")

    return {
        "service_id": failure_event.get("service_id", ""),
        "diagnosed_cause": cause,
        "confidence": 0.3,
        "chosen_action": chosen_action,
        "action_params": action_params,
        "reasoning": f"[deterministic fallback: {reason}] {cause}",
    }


def validate_recovery_decision(
    raw: Any, failure_event: dict[str, Any]
) -> tuple[dict[str, Any], bool, str | None]:
    """Validate a raw model-produced Recovery Decision against the frozen
    contract. Returns (decision, fallback_used, fallback_reason).

    This is the one function the Orchestrator's correctness depends on: no
    matter what garbage the model produces, this always returns a
    contract-shaped dict with chosen_action in the closed enum.
    """
    if not isinstance(raw, dict):
        d = deterministic_fallback(failure_event, "model output was not a JSON object")
        return d, True, "not_a_dict"

    chosen_action = raw.get("chosen_action")
    if chosen_action not in CHOSEN_ACTIONS:
        d = deterministic_fallback(
            failure_event, f"chosen_action {chosen_action!r} not in closed enum"
        )
        return d, True, "invalid_action"

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if not (0.0 <= confidence <= 1.0):
        d = deterministic_fallback(failure_event, f"confidence {confidence!r} out of range")
        return d, True, "invalid_confidence"

    if confidence < CONFIDENCE_FALLBACK_THRESHOLD:
        d = deterministic_fallback(
            failure_event, f"confidence {confidence:.2f} below threshold "
            f"{CONFIDENCE_FALLBACK_THRESHOLD}"
        )
        return d, True, "low_confidence"

    raw_params = raw.get("action_params") or {}
    if not isinstance(raw_params, dict):
        raw_params = {}

    action_params = {
        "target_revision": str(raw_params.get("target_revision", "") or ""),
        "env_key": str(raw_params.get("env_key", "") or ""),
        "env_value": str(raw_params.get("env_value", "") or ""),
        "memory_mb": 0,
    }

    if chosen_action == "rollback_to_last_good" and not action_params["target_revision"]:
        action_params["target_revision"] = failure_event.get("last_known_good_revision", "")

    if chosen_action == "increase_memory_limit":
        action_params["memory_mb"] = _clamp_memory_mb(
            raw_params.get("memory_mb"),
            (failure_event.get("metrics") or {}).get("memory_mb"),
        )

    decision = {
        "service_id": str(raw.get("service_id") or failure_event.get("service_id", "")),
        "diagnosed_cause": str(raw.get("diagnosed_cause", "") or "")[:2000],
        "confidence": confidence,
        "chosen_action": chosen_action,
        "action_params": action_params,
        "reasoning": str(raw.get("reasoning", "") or "")[:2000],
    }
    return decision, False, None
