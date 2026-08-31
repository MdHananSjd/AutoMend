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


async def verify_health() -> dict[str, Any]:
    """Poll the target service's GET /health endpoint.

    Checks every VERIFICATION_POLL_INTERVAL_SECONDS for up to
    VERIFICATION_WINDOW_SECONDS total.

    Returns:
        {
            "healthy": bool,
            "attempts": int,
            "response": dict | None,  # last health response if available
            "error": str | None,      # last error if all attempts failed
        }
    """
    url = f"{config.TARGET_SERVICE_URL.rstrip('/')}/health"
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


def verify_health_sync() -> dict[str, Any]:
    """Synchronous wrapper for verify_health().

    Used when the caller is not async.
    """
    return asyncio.run(verify_health())
