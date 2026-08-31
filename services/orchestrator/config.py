"""
AutoMend Orchestrator — Configuration

Loads environment variables with sensible defaults.
"""

from __future__ import annotations

import os


class Config:
    """Application configuration from environment variables."""

    # GCP
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "automend-hackathon")
    GCP_REGION: str = os.getenv("GCP_REGION", "us-central1")

    # Service URLs — swap these for real URLs once A and B deploy
    DIAGNOSIS_AGENT_URL: str = os.getenv(
        "DIAGNOSIS_AGENT_URL",
        "https://automend-diagnosis-placeholder-uc.a.run.app",
    )
    TARGET_SERVICE_URL: str = os.getenv(
        "TARGET_SERVICE_URL",
        "https://automend-target-placeholder-uc.a.run.app",
    )

    # Timeouts and polling
    DIAGNOSIS_TIMEOUT_SECONDS: float = float(os.getenv("DIAGNOSIS_TIMEOUT_SECONDS", "10"))
    VERIFICATION_POLL_INTERVAL_SECONDS: float = float(os.getenv("VERIFICATION_POLL_INTERVAL_SECONDS", "5"))
    VERIFICATION_WINDOW_SECONDS: float = float(os.getenv("VERIFICATION_WINDOW_SECONDS", "60"))

    # Cloud Run Admin API — the service to manage
    # This is the Target Service's Cloud Run service name (not the URL)
    TARGET_CLOUD_RUN_SERVICE: str = os.getenv("TARGET_CLOUD_RUN_SERVICE", "automend-target")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8080"))


config = Config()
