MOCK_SCENARIOS = {
    "healthy": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 35, "restart_count": 0},
        "logs": [
            {"message": "Request processed successfully", "status_code": 200, "path": "/"},
            {"message": "Request processed successfully", "status_code": 200, "path": "/health"}
        ]
    },
    "error_rate_spike": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.85, "memory_mb": 40, "restart_count": 0},
        "logs": [
            {"message": "Request failure observed", "status_code": 500, "path": "/api/data", "event_type": "error_rate_spike"},
            {"message": "Request failure observed", "status_code": 500, "path": "/api/data"}
        ]
    },
    "memory_leak": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 850, "restart_count": 0},
        "logs": [
            {"message": "Failure injected", "event_type": "memory_leak"}
        ]
    },
    "crash_loop": {
        "current_revision": "rev-002",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 0, "restart_count": 5},
        "logs": [
            {"message": "Crash loop state detected on startup. Crashing immediately.", "event_type": "crash_loop"}
        ]
    },
    "bad_deploy": {
        "current_revision": "rev-003",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 0, "restart_count": 0},
        "logs": [
            {"message": "Startup failed: Invalid configuration detected", "event_type": "bad_deploy"}
        ]
    },
    "health_check_failure": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.0, "memory_mb": 40, "restart_count": 0},
        "logs": [
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"},
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"},
            {"message": "Health check probe failed", "status_code": 500, "path": "/health"}
        ]
    },
    "dependency_failure": {
        "current_revision": "rev-001",
        "last_known_good_revision": "rev-001",
        "metrics": {"error_rate": 0.1, "memory_mb": 40, "restart_count": 0},
        "logs": [
            {"message": "Database error: Connection refused to 10.0.0.5", "event_type": "dependency_failure"}
        ]
    }
}