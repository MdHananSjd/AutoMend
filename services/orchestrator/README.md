# AutoMend Orchestrator

Recovery coordinator — receives Failure Events, calls the Diagnosis Agent, executes recovery actions via Cloud Run Admin API, verifies the fix, and logs everything to Firestore.

## Pipeline
```
POST /incidents → Firestore(received) → POST /diagnose → Firestore(diagnosing)
→ execute action → Firestore(action_taken) → poll /health → Firestore(recovered/failed/escalated)
```

## Recovery Actions
| Action | Cloud Run API Call |
|---|---|
| `rollback_to_last_good` | Traffic split to prior revision |
| `patch_env_var` | Deploy new revision with updated env var |
| `increase_memory_limit` | Deploy new revision with updated memory |
| `restart_instance` | Force new revision (same config) |
| `scale_down_instance` | Update min/max instance count |

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT_ID` | `automend-hackathon` | GCP project ID |
| `GCP_REGION` | `us-central1` | GCP region |
| `DIAGNOSIS_AGENT_URL` | `https://automend-diagnosis-...` | Diagnosis Agent base URL |
| `TARGET_SERVICE_URL` | `https://automend-target-.../health` | Target Service health URL |
| `TARGET_CLOUD_RUN_SERVICE` | `automend-target` | Cloud Run service name for Admin API |
| `DISABLE_AUTH` | `false` | Skip ID token auth (for local testing) |
| `DIAGNOSIS_TIMEOUT_SECONDS` | `10` | Timeout for diagnosis agent call |
| `VERIFICATION_WINDOW_SECONDS` | `60` | How long to poll health after action |

## Running locally
```bash
pip install -r requirements.txt
DISABLE_AUTH=true DIAGNOSIS_AGENT_URL=http://localhost:8082 TARGET_SERVICE_URL=http://localhost:8081/health uvicorn main:app --port 8080
```

## Running tests
```bash
python -m pytest tests/test_unit.py -v
```
