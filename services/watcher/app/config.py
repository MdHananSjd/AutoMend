import os

class Config:
    # Service Identity & Endpoints
    SERVICE_ID = os.getenv("SERVICE_ID", "target-service-dev")
    PROJECT_ID = os.getenv("GCP_PROJECT_ID", "my-gcp-project")
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080/incidents")
    
    # Run & Auth Configuration
    MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"
    DISABLE_AUTH = os.getenv("DISABLE_AUTH", "true").lower() == "true"
    POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "10"))
    COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "60"))
    
    # Retry & Network Settings
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    INITIAL_BACKOFF_SEC = float(os.getenv("INITIAL_BACKOFF_SEC", "1.0"))
    MAX_BACKOFF_SEC = float(os.getenv("MAX_BACKOFF_SEC", "8.0"))
    REQUEST_TIMEOUT_SEC = float(os.getenv("REQUEST_TIMEOUT_SEC", "5.0"))
    
    # Detection Thresholds
    ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "0.20"))
    MEMORY_MB_THRESHOLD = int(os.getenv("MEMORY_MB_THRESHOLD", "256"))
    CRASH_RESTART_THRESHOLD = int(os.getenv("CRASH_RESTART_THRESHOLD", "3"))
    CONSECUTIVE_HEALTH_FAILURES = int(os.getenv("CONSECUTIVE_HEALTH_FAILURES", "3"))