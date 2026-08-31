# AutoMend — Person A Final Team Handoff Document

**Author:** Person A (Target Service & Watcher Lead)  
**Target Service:** `automend-target`  
**Watcher Service:** `automend-watcher`  
**Date:** September 1, 2026  

---

## 1. What I Own

Person A owns **ONLY** the components that fail and notice failure:
1. **Target Service**: FastAPI backend running on Cloud Run emitting structured JSON telemetry and hosting debug-gated failure triggers.
2. **Watcher**: Independent log/metric classification service running on Cloud Run that continuously queries GCP Cloud Logging/Monitoring, constructs Failure Events, and dispatches them to Person C's Orchestrator over REST.

Person A does **NOT** own or execute:
- Gemini / ADK root-cause diagnosis (Person B).
- Cloud Run Admin API recovery actions, Firestore audit logs, or Verification polling (Person C).

---

## 2. Target Service Specification

- **Cloud Run Service Name**: `automend-target`
- **URL Placeholder**: `https://automend-target-xxxxxx-uc.a.run.app`
- **Authentication**: `--allow-unauthenticated` (Publicly accessible for Orchestrator health polling).

### Available Endpoints
- `GET /` — Root endpoint returning `{"status": "ok", "message": "Target Service Operational"}`.
- `GET /health` — Post-recovery verification polling endpoint.
- `POST /debug/error-spike` — Triggers 100% 500 error rate spike.
- `POST /debug/leak-memory` — Triggers memory allocation leak (default 150MB).
- `POST /debug/hang` — Causes requests to stall and timeout (503 response).
- `POST /debug/crash` — Persists `/tmp/crash_loop.flag` and exits process to trigger crash loop on startup.
- `POST /debug/reset` — Clears all failure states and restores Target Service to healthy status.

### `/health` Response Payload (`200 OK` when healthy, `500` when unhealthy)
```json
{
  "status": "ok",
  "error_rate": 0.0,
  "memory_mb": 45
}
```

### Revision Identification
- Current revision ID is automatically supplied by Cloud Run via the standard `K_REVISION` environment variable (e.g. `automend-target-00002-xyz`) and embedded in all structured log lines.

---

## 3. Failure Types Matrix

| Failure Type | How Triggered | Observable Signal | Expected Watcher Classification |
|---|---|---|---|
| `crash_loop` | `POST /debug/crash` or deployment of revision with `/tmp/crash_loop.flag` | Startup log contains `"Crash loop state detected on startup"` or `restart_count >= 3` | `crash_loop` |
| `error_rate_spike` | `POST /debug/error-spike` + HTTP requests | Log entries contain `status_code >= 500` resulting in `derived_error_rate >= 0.20` | `error_rate_spike` |
| `memory_leak` | `POST /debug/leak-memory` | Log entry `event_type="memory_leak"` or container memory usage `>= 256MB` | `memory_leak` |
| `bad_deploy` | Deploy revision with `INTENTIONALLY_BROKEN=true` | Startup log contains `"Startup failed: Invalid configuration detected"` or `event_type="bad_deploy"` | `bad_deploy` |
| `health_check_failure` | `POST /debug/hang` | `/health` returns non-200 or logs contain `event_type="health_check_failure"` | `health_check_failure` |
| `dependency_failure` | Downstream connection error injection | Log message contains `"Connection refused"` or `event_type="dependency_failure"` | `dependency_failure` |

---

## 4. Failure Event Contract

The Watcher calls **Person C's Orchestrator**: `POST /incidents`

### Request Body (Failure Event)
```json
{
  "service_id": "automend-target",
  "revision_id": "automend-target-00002-bad",
  "timestamp": "2026-09-01T04:30:00.000Z",
  "failure_type": "crash_loop",
  "log_snippet": "{\"time\":\"2026-09-01T04:30:00Z\", \"level\":\"CRITICAL\", \"message\":\"Crash loop state detected on startup.\", \"service_id\":\"automend-target\", \"revision_id\":\"automend-target-00002-bad\", \"event_type\":\"crash_loop\"}",
  "metrics": {
    "error_rate": 0.0,
    "memory_mb": 45,
    "restart_count": 5
  },
  "last_known_good_revision": "automend-target-00001-good"
}
```

---

## 5. Last-Known-Good Revision (LKGR) Derivation

The Watcher determines `last_known_good_revision` as follows:
1. When scanning Cloud Logging entries for `automend-target`, Watcher inspects the structured log stream.
2. Log entries emitted during container startup include `status: "ready"` and `revision_id` when healthy.
3. The most recent revision prior to the current failing revision that successfully emitted a `"status": "ready"` startup log is tagged as `last_known_good_revision`.
4. If no previous healthy revision exists in log history, Watcher defaults `last_known_good_revision` to the current revision ID.

---

## 6. Orchestrator REST Integration

- **Watcher Config**: Environment variable `ORCHESTRATOR_URL=https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents`.
- **Authentication**: Service-to-service Cloud Run ID token authentication.
  - Watcher fetches an OIDC ID token for `https://automend-orchestrator-xxxxxx-uc.a.run.app`.
  - Header: `Authorization: Bearer <ID_TOKEN>`.
  - IAM Requirement: Watcher's Service Account (`automend-watcher-sa@YOUR_PROJECT.iam.gserviceaccount.com`) must have `roles/run.invoker` on Person C's Orchestrator service.
- **Request Timeout**: `5.0 seconds`.
- **Retry Behavior**: Exponential backoff on network errors or non-2xx responses (`MAX_RETRIES=3`, initial backoff `1.0s`, max backoff `8.0s`).
- **Expected Orchestrator Response**: `HTTP 202 Accepted`
  ```json
  {
    "incident_id": "inc-20260901-001",
    "status": "received"
  }
  ```

---

## 7. Test Commands for Team Verification

Person C can verify Person A's Watcher and Target Service handoff using these direct commands:

```bash
# 1. Verify Target Service is Healthy
curl -i https://automend-target-xxxxxx-uc.a.run.app/health

# 2. Inject Failure (e.g. Error Spike)
curl -i -X POST https://automend-target-xxxxxx-uc.a.run.app/debug/error-spike

# 3. Generate Traffic to Trigger 500 Logs
curl -i https://automend-target-xxxxxx-uc.a.run.app/

# 4. Check Watcher Logs to Confirm Failure Event Generation & POST Dispatch
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="automend-watcher"' --limit 10

# 5. Reset Target Service & Watcher State
curl -i -X POST https://automend-target-xxxxxx-uc.a.run.app/debug/reset
curl -i -X POST https://automend-watcher-xxxxxx-uc.a.run.app/reset
```

---

## 8. Troubleshooting Matrix

| Problem | Likely Cause | Command / Check | Fix |
|---|---|---|---|
| No logs visible in Watcher | `SERVICE_ID` env mismatch or no traffic | `gcloud logging read 'resource.type="cloud_run_revision"' --limit 5` | Ensure `SERVICE_ID=automend-target` in Watcher env |
| Watcher cannot query logs | Missing Logging Viewer IAM role | `gcloud projects get-iam-policy YOUR_PROJECT_ID --filter="automend-watcher-sa"` | Grant `roles/logging.viewer` to `automend-watcher-sa` |
| Watcher does not classify | Log payload format not matching rules | `curl -i https://automend-target-xxxxxx-uc.a.run.app/health` | Verify Target Service emits structured JSON logs |
| Duplicate incidents dispatched | Cooldown expired or state reset | `curl https://automend-watcher-xxxxxx-uc.a.run.app/health` | Adjust `COOLDOWN_SEC` in Watcher config (default 60s) |
| POST /incidents returns HTTP 401 | Missing Bearer token in request | Check Watcher logs for `Auth token retrieval failed` | Ensure `DISABLE_AUTH=false` and GCP credentials present |
| POST /incidents returns HTTP 403 | Service Account missing `roles/run.invoker` | `gcloud run services get-iam-policy automend-orchestrator` | Run `gcloud run services add-iam-policy-binding automend-orchestrator --member="serviceAccount:automend-watcher-sa@..." --role="roles/run.invoker"` |
| POST /incidents timeout | Orchestrator endpoint taking too long | Inspect Orchestrator response time | Ensure Orchestrator returns `202 Accepted` immediately before doing diagnosis |
| Cloud Run cold start delay | Zero minimum instances configured | `gcloud run services describe automend-target` | Set `--min-instances 1` on both Target Service and Watcher |
| Wrong revision ID reported | `K_REVISION` not set or hardcoded | Check `revision_id` in `/health` or log snippet | Let Cloud Run populate `K_REVISION` automatically |

---

## 9. Final Demo Sequence (Person A Responsibilities)

During the live 4-5 minute AutoMend demo, Person A performs the following exact actions:

1. **0:00 – Show Healthy Target Service**:
   - Call `curl https://automend-target-xxxxxx-uc.a.run.app/health`.
   - Point out `status: ok` and clean log stream.
2. **1:00 – Inject Mandatory Failure (Broken Revision / Crash Loop)**:
   - Execute broken revision deployment or trigger `POST /debug/crash`.
3. **1:30 – Show Watcher Detection**:
   - Display Watcher logs showing markers: `[DETECTED]` $\rightarrow$ `[CLASSIFIED: crash_loop]` $\rightarrow$ `[EVENT_BUILT]`.
4. **1:45 – Demonstrate Hand-off to Person C**:
   - Point out Watcher log marker `[SENDING_TO_ORCHESTRATOR]` followed by `[INCIDENT_ACCEPTED] (HTTP 202)`.
   - Announce: *"Person A handoff complete. Failure Event dispatched to Orchestrator."*
5. **3:30 – Verify Recovery**:
   - After Person C executes rollback, poll `curl https://automend-target-xxxxxx-uc.a.run.app/health` to confirm `status: ok`.
