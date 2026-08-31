import asyncio
import logging
import httpx
from typing import Dict, Any, Tuple
from app.config import Config

logger = logging.getLogger("watcher.orchestrator_client")

class OrchestratorClient:
    """Handles REST dispatch of Failure Events to the Orchestrator with Auth and Retry Backoff."""

    @staticmethod
    def _get_id_token(target_audience: str) -> str:
        """Fetches a Google OIDC ID token for Cloud Run IAM service-to-service auth."""
        if Config.DISABLE_AUTH:
            return "mock-local-token"
        
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
        
        auth_req = Request()
        token = id_token.fetch_id_token(auth_req, target_audience)
        return token

    @classmethod
    async def send_incident(cls, failure_event: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Sends POST /incidents with exponential backoff.
        Returns (success_boolean, response_dict_or_error_dict).
        """
        target_url = Config.ORCHESTRATOR_URL
        headers = {"Content-Type": "application/json"}

        if not Config.DISABLE_AUTH:
            try:
                # Audience is the base service URL without endpoint paths
                audience = target_url.rsplit("/incidents", 1)[0]
                token = cls._get_id_token(audience)
                headers["Authorization"] = f"Bearer {token}"
            except Exception as auth_err:
                logger.error(f"Failed to acquire Cloud Run ID token: {auth_err}")
                return False, {"error": "Authentication token retrieval failed", "details": str(auth_err)}

        backoff = Config.INITIAL_BACKOFF_SEC

        async with httpx.AsyncClient(timeout=Config.REQUEST_TIMEOUT_SEC) as client:
            for attempt in range(1, Config.MAX_RETRIES + 1):
                try:
                    logger.info(f"Posting incident to Orchestrator (Attempt {attempt}/{Config.MAX_RETRIES})...")
                    response = await client.post(target_url, json=failure_event, headers=headers)

                    if response.status_code == 202:
                        payload = response.json()
                        logger.info(f"Incident delivered successfully. Incident ID: {payload.get('incident_id')}")
                        return True, payload
                    else:
                        logger.warning(
                            f"Orchestrator returned non-202 status: {response.status_code}. Response: {response.text}"
                        )

                except (httpx.RequestError, httpx.TimeoutException) as req_err:
                    logger.warning(f"Network error on attempt {attempt}: {str(req_err)}")

                if attempt < Config.MAX_RETRIES:
                    logger.info(f"Backing off for {backoff:.2f} seconds before retry...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, Config.MAX_BACKOFF_SEC)

        logger.error(f"Exhausted all {Config.MAX_RETRIES} retry attempts. Failed to deliver incident.")
        return False, {"error": "Retry limit reached", "attempts": Config.MAX_RETRIES}