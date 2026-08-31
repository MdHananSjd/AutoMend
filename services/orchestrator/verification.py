"""
AutoMend Orchestrator — Verification

After executing a recovery action, poll the target service's health endpoint
for a short window to confirm the fix worked.

Per the briefing: no automatic retry — if it's still unhealthy after the
verification window, mark it failed/escalated.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from config import config

logger = logging.getLogger(__name__)

# Map service_id → health URL (extend as more services are added)
_SERVICE_HEALTH_URLS: dict[str, str] = {}


def register_service_health_url(service_id: str, health_url: str) -> None:
    """Register a service's health check URL."""
    _SERVICE_HEALTH_URLS[service_id] = health_url


def _resolve_health_url(service_id: str | None = None) -> str:
    """Resolve the health check URL for a given service.

    Falls back to config.TARGET_SERVICE_URL if no mapping exists.
    """
    if service_id and service_id in _SERVICE_HEALTH_URLS:
        return _SERVICE_HEALTH_URLS[service_id]
    return f"{config.TARGET_SERVICE_URL.rstrip('/')}/health"


async def verify_health(service_id: str | None = None) -> dict[str, Any]:
    """Poll the target service's GET /health endpoint.

    Args:
        service_id: The specific service to verify. If None, uses the
                    default TARGET_SERVICE_URL from config.

    Checks every VERIFICATION_POLL_INTERVAL_SECONDS for up to
    VERIFICATION_WINDOW_SECONDS total.

    Returns:
        {
            "healthy": bool,
            "attempts": int,
            "response": dict | None,
            "error": str | None,
        }
    """
    url = _resolve_health_url(service_id)
    poll_interval = config.VERIFICATION_POLL_INTERVAL_SECONDS
    window = config.VERIFICATION_WINDOW_SECONDS

    logger.info(
        "Starting health verification for %s (poll every %ds for %ds)",
        url,
        poll_interval,
        window,
    )

    attempts = 0
    last_response = None
    last_error = None

    elapsed = 0.0
    while elapsed < window:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    body = response.json()
                    status = body.get("status", "unknown")

                    if status == "ok":
                        logger.info(
                            "Health check passed on attempt %d: %s",
                            attempts,
                            body,
                        )
                        return {
                            "healthy": True,
                            "attempts": attempts,
                            "response": body,
                            "error": None,
                        }
                    else:
                        logger.info(
                            "Health check returned non-ok status on attempt %d: %s",
                            attempts,
                            status,
                        )
                        last_response = body
                else:
                    logger.info(
                        "Health check returned HTTP %d on attempt %d",
                        response.status_code,
                        attempts,
                    )
                    last_error = f"HTTP {response.status_code}"

        except httpx.TimeoutException:
            logger.info("Health check timed out on attempt %d", attempts)
            last_error = "timeout"

        except httpx.ConnectError as e:
            logger.info("Health check connection failed on attempt %d: %s", attempts, e)
            last_error = str(e)

        except Exception as e:
            logger.warning("Unexpected error during health check: %s", e)
            last_error = str(e)

        # Wait before next attempt
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    # Verification window exhausted — service is still unhealthy
    logger.warning(
        "Health verification failed after %d attempts over %ds",
        attempts,
        window,
    )

    return {
        "healthy": False,
        "attempts": attempts,
        "response": last_response,
        "error": last_error or "verification window exhausted",
    }


def verify_health_sync(service_id: str | None = None) -> dict[str, Any]:
    """Synchronous wrapper for verify_health()."""
    return asyncio.run(verify_health(service_id=service_id))
