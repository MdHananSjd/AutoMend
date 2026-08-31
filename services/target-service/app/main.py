import json
import time
import os
import sys
import asyncio
from fastapi import FastAPI, Request, Response, HTTPException
from app.logger import logger
from app.state import state

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
CRASH_FLAG_FILE = "/tmp/crash_loop.flag"

app = FastAPI(title="AutoMend Target Service", version="1.0.0")

@app.on_event("startup")
async def startup_event() -> None:
    # 1. Bad Deploy Scenario
    # Triggered by deploying a new revision with this environment variable set
    if os.getenv("INTENTIONALLY_BROKEN") == "true":
        logger.critical(
            "Startup failed: Invalid configuration detected", 
            extra={"extra_fields": {"event_type": "bad_deploy", "failure_state": "active"}}
        )
        sys.exit(1)

    # 2. Crash Loop Scenario
    # Persists across immediate container process restarts via the in-memory /tmp volume
    if os.path.exists(CRASH_FLAG_FILE):
        logger.critical(
            "Crash loop state detected on startup. Crashing immediately.", 
            extra={"extra_fields": {"event_type": "crash_loop", "failure_state": "active"}}
        )
        sys.exit(1)

    logger.info(
        "Target Service initialized",
        extra={"extra_fields": {"event": "startup", "status": "ready"}},
    )

@app.middleware("http")
async def failure_injection_middleware(request: Request, call_next):
    if request.url.path.startswith("/debug/"):
        return await call_next(request)

    if state.is_hanging:
        logger.warning(
            "Endpoint hang simulated", 
            extra={"extra_fields": {"event_type": "health_check_failure", "failure_state": "active"}}
        )
        await asyncio.sleep(30)
        return Response(status_code=503, content=json.dumps({"error": "Service Unavailable (Hang)"}))

    if state.is_error_spike and request.url.path != "/health":
        start_time = time.time()
        duration_ms = round((time.time() - start_time) * 1000, 2)
        log_payload = {
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "duration_ms": duration_ms,
            "event_type": "error_rate_spike",
            "failure_state": "active"
        }
        logger.error("Request failure observed", extra={"extra_fields": log_payload})
        return Response(
            status_code=500,
            content=json.dumps({"error": "Internal Server Error (Injected)"}),
            media_type="application/json"
        )

    start_time = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)

    log_payload = {
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    }

    if response.status_code >= 500:
        logger.error("Request failure observed", extra={"extra_fields": log_payload})
    else:
        logger.info("Request processed successfully", extra={"extra_fields": log_payload})

    return response

@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "Target Service Operational"}

@app.get("/health")
async def health() -> Response:
    status_str = "ok" if state.is_healthy else "unhealthy"
    payload = {
        "status": status_str,
        "error_rate": state.forced_error_rate,
        "memory_mb": state.get_memory_usage_mb(),
    }

    status_code = 200 if state.is_healthy else 500
    if not state.is_healthy:
        logger.error("Health check probe failed", extra={"extra_fields": payload})

    return Response(
        content=json.dumps(payload),
        status_code=status_code,
        media_type="application/json",
    )

def require_debug_mode():
    if not DEBUG_MODE:
        raise HTTPException(status_code=403, detail="Debug endpoints disabled.")

@app.post("/debug/error-spike")
async def trigger_error_spike():
    require_debug_mode()
    state.is_error_spike = True
    state.forced_error_rate = 1.0
    state.is_healthy = False
    logger.warning("Failure injected", extra={"extra_fields": {"event_type": "error_rate_spike", "failure_state": "active"}})
    return {"status": "error_rate_spike triggered"}

@app.post("/debug/leak-memory")
async def trigger_leak_memory(mb_to_leak: int = 150):
    require_debug_mode()
    if mb_to_leak > 500:
        mb_to_leak = 500 
    
    chunk = b'a' * (1024 * 1024 * mb_to_leak)
    state.allocated_memory.append(chunk)
    state.is_healthy = False
    
    current_mem = state.get_memory_usage_mb()
    logger.warning("Failure injected", extra={"extra_fields": {"event_type": "memory_leak", "failure_state": "active", "metrics": {"memory_mb": current_mem}}})
    return {"status": "memory_leak triggered", "leaked_mb": mb_to_leak, "current_memory_mb": current_mem}

@app.post("/debug/hang")
async def trigger_hang():
    require_debug_mode()
    state.is_hanging = True
    state.is_healthy = False
    logger.warning("Failure injected", extra={"extra_fields": {"event_type": "health_check_failure", "failure_state": "active"}})
    return {"status": "health_check_failure triggered"}

@app.post("/debug/crash")
async def trigger_crash():
    require_debug_mode()
    logger.critical("Failure injected: initiating crash loop", extra={"extra_fields": {"event_type": "crash_loop", "failure_state": "active"}})
    # Write flag to in-memory file system to persist the crash state across container process restarts
    with open(CRASH_FLAG_FILE, "w") as f:
        f.write("crash")
    os._exit(1)

@app.post("/debug/reset")
async def reset_service():
    require_debug_mode()
    state.reset()
    if os.path.exists(CRASH_FLAG_FILE):
        os.remove(CRASH_FLAG_FILE)
    logger.info("Service state reset", extra={"extra_fields": {"event_type": "reset", "failure_state": "inactive"}})
    return {"status": "service reset to healthy state"}