"""
AutoMend Orchestrator — Recovery Executor

Translates RecoveryDecision chosen_action values into Cloud Run Admin API calls
using the google-cloud-run Python client library.

All five recovery actions:
  1. rollback_to_last_good  → traffic split to prior revision
  2. patch_env_var           → deploy new revision with updated env var
  3. increase_memory_limit   → deploy new revision with updated memory limit
  4. restart_instance        → deploy new revision with same config (fresh containers)
  5. scale_down_instance     → update service min/max instance count
"""

from __future__ import annotations

import logging
from typing import Any

from google.cloud import run_v2
from google.cloud.run_v2 import types

from config import config
from models import ChosenAction, RecoveryDecision

logger = logging.getLogger(__name__)

# ─── Cloud Run client setup ──────────────────────────────────────────────────

_client: run_v2.ServicesClient | None = None


def _get_client() -> run_v2.ServicesClient:
    """Get or create the Cloud Run Services client."""
    global _client
    if _client is None:
        _client = run_v2.ServicesClient()
    return _client


def _get_service_name(service_id: str | None = None) -> str:
    """Build the full Cloud Run service resource name.

    Format: projects/{project}/locations/{region}/services/{service}
    """
    svc = service_id or config.TARGET_CLOUD_RUN_SERVICE
    return f"projects/{config.GCP_PROJECT_ID}/locations/{config.GCP_REGION}/services/{svc}"


def _get_current_service(service_name: str) -> run_v2.Service:
    """Fetch the current state of a Cloud Run service."""
    client = _get_client()
    return client.get_service(name=service_name)


def _build_traffic_targets(
    revision_name: str, percent: int = 100
) -> list[run_v2.types.TrafficTarget]:
    """Build a traffic target list routing all traffic to one revision."""
    return [
        run_v2.types.TrafficTarget(
            revision=revision_name,
            percent=percent,
            tag="latest" if percent == 100 else None,
        )
    ]


def _extract_revision_names(service: run_v2.Service) -> list[str]:
    """Extract all revision names from a service's current traffic config."""
    revisions = []
    for target in service.traffic:
        if target.revision:
            revisions.append(target.revision)
    return revisions


# ─── Recovery Actions ────────────────────────────────────────────────────────


def execute_rollback(decision: RecoveryDecision) -> dict[str, Any]:
    """Rollback: shift 100% of traffic to the target revision.

    This does NOT deploy a new revision — it only changes traffic routing.
    """
    service_name = _get_service_name()
    target_revision = decision.action_params.target_revision

    if not target_revision:
        raise ValueError("rollback_to_last_good requires action_params.target_revision")

    logger.info(
        "Rolling back %s to revision %s",
        config.TARGET_CLOUD_RUN_SERVICE,
        target_revision,
    )

    # Build the full revision resource name if not already fully qualified
    if not target_revision.startswith("projects/"):
        target_revision = (
            f"projects/{config.GCP_PROJECT_ID}/locations/{config.GCP_REGION}"
            f"/services/{config.TARGET_CLOUD_RUN_SERVICE}/revisions/{target_revision}"
        )

    client = _get_client()
    service = _get_current_service(service_name)

    update_mask = "traffic"
    service.traffic = _build_traffic_targets(target_revision, percent=100)

    operation = client.update_service(
        service=service,
        update_mask=update_mask,
    )
    result = operation.result()

    logger.info("Rollback complete. New traffic config: %s", result.traffic)

    return {
        "action": "rollback_to_last_good",
        "target_revision": target_revision,
        "service_name": service_name,
        "traffic": [
            {"revision": t.revision, "percent": t.percent}
            for t in result.traffic
        ],
    }


def execute_patch_env(decision: RecoveryDecision) -> dict[str, Any]:
    """Patch environment variable: deploy a new revision with the updated env var."""
    service_name = _get_service_name()
    env_key = decision.action_params.env_key
    env_value = decision.action_params.env_value

    if not env_key:
        raise ValueError("patch_env_var requires action_params.env_key")

    logger.info(
        "Patching env var %s=%s on %s",
        env_key,
        env_value,
        config.TARGET_CLOUD_RUN_SERVICE,
    )

    client = _get_client()
    service = _get_current_service(service_name)

    # Update the env var in the container spec
    for template in service.template.containers:
        # Find and update or append the env var
        found = False
        for env in template.env:
            if env.name == env_key:
                env.value = env_value
                found = True
                break
        if not found:
            template.env.append(
                run_v2.types.EnvVar(name=env_key, value=env_value)
            )

    # Force a new revision by clearing the revision name
    service.template.revision = ""

    update_mask = "template.containers.env"
    operation = client.update_service(
        service=service,
        update_mask=update_mask,
    )
    result = operation.result()

    new_revision = result.latest_ready_revision
    logger.info("Patch deployed. New revision: %s", new_revision)

    return {
        "action": "patch_env_var",
        "env_key": env_key,
        "env_value": env_value,
        "new_revision": new_revision,
    }


def execute_increase_memory(decision: RecoveryDecision) -> dict[str, Any]:
    """Increase memory limit: deploy a new revision with updated memory."""
    service_name = _get_service_name()
    memory_mb = decision.action_params.memory_mb

    if memory_mb <= 0:
        raise ValueError("increase_memory_limit requires action_params.memory_mb > 0")

    logger.info(
        "Increasing memory to %d MB on %s",
        memory_mb,
        config.TARGET_CLOUD_RUN_SERVICE,
    )

    client = _get_client()
    service = _get_current_service(service_name)

    # Update memory limit in container resources
    for template in service.template.containers:
        if template.resources is None:
            template.resources = run_v2.types.ResourceRequirements()
        if template.resources.limits is None:
            template.resources.limits = {}
        template.resources.limits["memory"] = f"{memory_mb}Mi"

    # Force a new revision
    service.template.revision = ""

    update_mask = "template.containers.resources"
    operation = client.update_service(
        service=service,
        update_mask=update_mask,
    )
    result = operation.result()

    new_revision = result.latest_ready_revision
    logger.info("Memory increase deployed. New revision: %s", new_revision)

    return {
        "action": "increase_memory_limit",
        "memory_mb": memory_mb,
        "new_revision": new_revision,
    }


def execute_restart(decision: RecoveryDecision) -> dict[str, Any]:
    """Restart: deploy a new revision with the same config (triggers fresh containers).

    There is no literal restart API — a restart is a redeploy with identical config.
    We force a new revision by clearing the revision name.
    """
    service_name = _get_service_name()

    logger.info("Restarting %s (forced redeploy)", config.TARGET_CLOUD_RUN_SERVICE)

    client = _get_client()
    service = _get_current_service(service_name)

    # Force a new revision by clearing the revision name
    service.template.revision = ""

    update_mask = "template.labels"
    operation = client.update_service(
        service=service,
        update_mask=update_mask,
    )
    result = operation.result()

    new_revision = result.latest_ready_revision
    logger.info("Restart deployed. New revision: %s", new_revision)

    return {
        "action": "restart_instance",
        "new_revision": new_revision,
    }


def execute_scale_down(decision: RecoveryDecision) -> dict[str, Any]:
    """Scale down: update min/max instance count on the service."""
    service_name = _get_service_name()
    memory_mb = decision.action_params.memory_mb  # Reusing for max instances if needed

    logger.info(
        "Scaling down %s",
        config.TARGET_CLOUD_RUN_SERVICE,
    )

    client = _get_client()
    service = _get_current_service(service_name)

    # Set scaling limits — reduce to 0 min, 1 max
    service.template.scaling = run_v2.types.RevisionScaling(
        min_instance_count=0,
        max_instance_count=1,
    )

    update_mask = "template.scaling"
    operation = client.update_service(
        service=service,
        update_mask=update_mask,
    )
    result = operation.result()

    logger.info(
        "Scale down complete. Min=%s, Max=%s",
        result.template.scaling.min_instance_count,
        result.template.scaling.max_instance_count,
    )

    return {
        "action": "scale_down_instance",
        "min_instances": result.spec.scaling.min_instance_count,
        "max_instances": result.spec.scaling.max_instance_count,
    }


# ─── Action dispatcher ──────────────────────────────────────────────────────


def execute_action(decision: RecoveryDecision) -> dict[str, Any]:
    """Execute the chosen recovery action.

    Dispatches to the appropriate handler based on the chosen_action enum.
    Returns a dict of what was actually executed (for the incident record).
    """
    dispatch = {
        ChosenAction.ROLLBACK_TO_LAST_GOOD: execute_rollback,
        ChosenAction.PATCH_ENV_VAR: execute_patch_env,
        ChosenAction.INCREASE_MEMORY_LIMIT: execute_increase_memory,
        ChosenAction.RESTART_INSTANCE: execute_restart,
        ChosenAction.SCALE_DOWN_INSTANCE: execute_scale_down,
    }

    handler = dispatch.get(decision.chosen_action)
    if handler is None:
        logger.error("Unknown action: %s", decision.chosen_action)
        return {
            "action": decision.chosen_action.value,
            "error": f"Unknown action: {decision.chosen_action}",
        }

    try:
        result = handler(decision)
        result["success"] = True
        return result
    except Exception as e:
        logger.error("Failed to execute action %s: %s", decision.chosen_action.value, e)
        return {
            "action": decision.chosen_action.value,
            "success": False,
            "error": str(e),
        }
