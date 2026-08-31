import json
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict

SERVICE_ID = os.getenv("SERVICE_ID", "target-service-dev")
REVISION_ID = os.getenv("K_REVISION", "dev-revision")

class StructuredJSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects for Google Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "service_id": SERVICE_ID,
            "revision_id": REVISION_ID,
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_record.update(record.extra_fields)
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def get_logger(name: str = "target-service") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJSONFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger

logger = get_logger()