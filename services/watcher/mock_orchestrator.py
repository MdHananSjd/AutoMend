import uuid
import logging
from fastapi import FastAPI, Response, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_orchestrator")

app = FastAPI(title="AutoMend Mock Orchestrator")

behavior_mode = "normal"  # Options: "normal", "error_500"

@app.get("/health")
async def health():
    return {"status": "mock_orchestrator_running"}

@app.post("/incidents")
async def receive_incident(request: Request):
    global behavior_mode
    body = await request.json()
    auth_header = request.headers.get("Authorization", "None")
    
    logger.info(f"[Mock Orchestrator] Received POST /incidents. Auth Header: {auth_header}")
    logger.info(f"[Mock Orchestrator] Payload: {body}")

    if behavior_mode == "error_500":
        logger.warning("[Mock Orchestrator] Simulating HTTP 500 Internal Server Error")
        return Response(status_code=500, content='{"error": "Simulated Orchestrator Failure"}', media_type="application/json")

    # Fixed UUID string conversion
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    return Response(
        status_code=202,
        content=f'{{"incident_id": "{incident_id}", "status": "received"}}',
        media_type="application/json"
    )

@app.post("/debug/set-mode")
async def set_mode(mode: str):
    global behavior_mode
    behavior_mode = mode
    return {"mock_orchestrator_mode": behavior_mode}