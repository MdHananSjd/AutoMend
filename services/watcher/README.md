# AutoMend Watcher

Cloud Logging classifier that detects failures on the Target Service and dispatches Failure Events to the Orchestrator.

## How it works
1. Polls Cloud Logging every `POLL_INTERVAL_SEC` (default 10s) for entries from the target service
2. Parses `jsonPayload` fields (status_code, event_type, path, message)
3. Classifies failure type using rule-based logic in `classifier.py`
4. On positive match, POSTs a Failure Event to the Orchestrator with ID token auth
5. Cooldown tracker prevents duplicate dispatches for the same failure signature

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `SERVICE_ID` | `target-service-dev` | Cloud Run service name to query logs for |
| `GCP_PROJECT_ID` | `my-gcp-project` | GCP project ID |
| `ORCHESTRATOR_URL` | `http://localhost:8080/incidents` | Orchestrator POST /incidents URL |
| `MOCK_MODE` | `true` | Use mock data instead of real Cloud Logging |
| `DISABLE_AUTH` | `true` | Skip ID token auth (for local testing) |
| `POLL_INTERVAL_SEC` | `10` | Seconds between log polls |
| `COOLDOWN_SEC` | `60` | Cooldown between duplicate incident dispatches |

## Running locally
```bash
pip install -r requirements.txt
MOCK_MODE=true MOCK_SCENARIO=error_rate_spike uvicorn app.main:app --port 8080
```

## Running tests
```bash
python -m pytest tests/test_classifier.py -v
```
