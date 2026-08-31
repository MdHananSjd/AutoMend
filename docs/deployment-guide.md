# Chunk 6 — Person A Deployment & Verification Guide (Google Cloud Run)

This guide documents the exact GCP Cloud Run deployment process, IAM configurations, demo reliability tuning, and step-by-step verification checklist for Person A (**Target Service** and **Watcher**).

---

## 1. Target Service Deployment

The Target Service (`automend-target`) is deployed to Google Cloud Run as a public endpoint so that Person C's Orchestrator can perform post-recovery health polling (`GET /health`).

### Environment Variables
- `DEBUG_MODE=true` — Enables debug failure injection endpoints (`/debug/error-spike`, `/debug/leak-memory`, `/debug/hang`, `/debug/crash`, `/debug/reset`).
- `SERVICE_ID=automend-target` — Identifies the service in structured JSON log entries.

### Exact Deployment Command
```bash
cd services/target-service
gcloud run deploy automend-target \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 1 \
  --set-env-vars "DEBUG_MODE=true,SERVICE_ID=automend-target"
```

---

## 2. Watcher Service Account & IAM Setup

The Watcher requires read access to Google Cloud Logging/Monitoring to detect failures, and authorization to invoke the Orchestrator's `POST /incidents` REST endpoint using Cloud Run ID token authentication (`roles/run.invoker`).

### Minimum IAM Principles
Watcher requires ONLY:
1. `roles/logging.viewer` on the GCP Project (to read Cloud Run log streams).
2. `roles/monitoring.viewer` on the GCP Project (to fetch metric statistics).
3. `roles/run.invoker` on the Orchestrator Cloud Run service.

Watcher does **NOT** receive:
- `roles/run.admin` (Infrastructure control is owned by Person C).
- Firestore write/read access.
- Gemini / ADK API access.

### Exact IAM Setup Commands
```bash
# 1. Create Dedicated Service Account
gcloud iam service-accounts create automend-watcher-sa \
  --display-name="AutoMend Watcher Service Account"

# 2. Grant Logging Viewer
gcloud projects add-iam-policy-binding YOUR_GCP_PROJECT_ID \
  --member="serviceAccount:automend-watcher-sa@YOUR_GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.viewer"

# 3. Grant Monitoring Viewer
gcloud projects add-iam-policy-binding YOUR_GCP_PROJECT_ID \
  --member="serviceAccount:automend-watcher-sa@YOUR_GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/monitoring.viewer"

# 4. Grant Invoker Permission on Orchestrator
gcloud run services add-iam-policy-binding automend-orchestrator \
  --region us-central1 \
  --member="serviceAccount:automend-watcher-sa@YOUR_GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

---

## 3. Watcher Deployment

The Watcher (`automend-watcher`) runs on Cloud Run as an internal background process bound to `automend-watcher-sa`.

### Environment Variables
- `GCP_PROJECT_ID=YOUR_GCP_PROJECT_ID`
- `SERVICE_ID=automend-target`
- `ORCHESTRATOR_URL=https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents`
- `MOCK_MODE=false` — Enables real GCP Cloud Logging fetching.
- `DISABLE_AUTH=false` — Enables Google Cloud Run OIDC ID token generation for Person C handoff.
- `POLL_INTERVAL_SEC=5` — High frequency polling for quick demo feedback.
- `COOLDOWN_SEC=60` — Prevents duplicate incident storms for the same failure signature.

### Exact Deployment Command
```bash
cd services/watcher
gcloud run deploy automend-watcher \
  --source . \
  --region us-central1 \
  --platform managed \
  --no-allow-unauthenticated \
  --min-instances 1 \
  --service-account automend-watcher-sa@YOUR_GCP_PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars "GCP_PROJECT_ID=YOUR_GCP_PROJECT_ID,SERVICE_ID=automend-target,ORCHESTRATOR_URL=https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents,MOCK_MODE=false,DISABLE_AUTH=false,POLL_INTERVAL_SEC=5,COOLDOWN_SEC=60"
```

---

## 4. Demo Reliability & Timing Analysis

To ensure a seamless live demonstration without unexpected delays:

| Metric / Parameter | Configured Value | Explanation |
|---|---|---|
| **Min Instances (`--min-instances`)** | `1` | Eliminates Cloud Run cold-start latency (0s container spin-up overhead). |
| **Polling Interval (`POLL_INTERVAL_SEC`)** | `5 seconds` | Watcher checks GCP logs every 5 seconds. |
| **Detection Window** | `Recent 100 entries (~5 min)` | Evaluates latest active log entries to capture freshly injected errors. |
| **Expected Detection Latency** | `~5 to 10 seconds` | Time from triggering `/debug/*` endpoint to Watcher classification. |
| **Expected Handoff Latency** | `~1 to 2 seconds` | Time for Watcher to fetch ID token, construct payload, and hit `POST /incidents`. |
| **Total Person A Latency** | **`~6 to 12 seconds`** | Fast and predictable demo response time. |

---

## 5. Step-by-Step Verification Checklist

Follow these verification steps in order to confirm the full Person A implementation before handing off to Person C:

### Step 1: Verify Target Cloud Run Service Health
```bash
TARGET_URL=$(gcloud run services describe automend-target --region us-central1 --format 'value(status.url)')
curl -i "$TARGET_URL/"
```
**Expected Output:**
`HTTP/1.1 200 OK`
`{"status":"ok","message":"Target Service Operational"}`

---

### Step 2: Verify `/health` Endpoint
```bash
curl -i "$TARGET_URL/health"
```
**Expected Output:**
`HTTP/1.1 200 OK`
`{"status": "ok", "error_rate": 0.0, "memory_mb": <int>}`

---

### Step 3: Trigger Injected Failure (Error Spike)
```bash
curl -i -X POST "$TARGET_URL/debug/error-spike"
```
**Expected Output:**
`HTTP/1.1 200 OK`
`{"status": "error_rate_spike triggered"}`

Generate traffic to register 500 responses:
```bash
curl -i "$TARGET_URL/"
```
**Expected Output:**
`HTTP/1.1 500 Internal Server Error`
`{"error": "Internal Server Error (Injected)"}`

---

### Step 4: Verify Logs in Cloud Logging
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="automend-target"' --limit 5 --format json
```
**Expected Output:** JSON log stream containing `"event_type": "error_rate_spike"`, `"status_code": 500`, and severity `ERROR`.

---

### Step 5: Verify Watcher Log Processing
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="automend-watcher"' --limit 10
```
**Expected Output:** Log entry stating: `Failure classified: error_rate_spike. Dispatching to Orchestrator...`

---

### Step 6: Verify Watcher Authentication & Handoff (`POST /incidents`)
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="automend-watcher" AND textPayload:"Incident"' --limit 5
```
**Expected Output:**
`Incident inc-xxxxxx acknowledged by Orchestrator.`

---

### Step 7: Reset Target Service to Healthy State
```bash
curl -i -X POST "$TARGET_URL/debug/reset"
curl -i "$TARGET_URL/health"
```
**Expected Output:**
`HTTP/1.1 200 OK`
`{"status": "service reset to healthy state"}`
`{"status": "ok", "error_rate": 0.0, "memory_mb": <int>}`

---

## 6. Troubleshooting Commands

If issues occur during GCP deployment or testing:

1. **Check Target Service Logs:**
   ```bash
   gcloud run services logs tail automend-target --region us-central1
   ```

2. **Check Watcher Logs:**
   ```bash
   gcloud run services logs tail automend-watcher --region us-central1
   ```

3. **Verify Watcher Service Account IAM Bindings:**
   ```bash
   gcloud projects get-iam-policy YOUR_GCP_PROJECT_ID \
     --flatten="bindings[].members" \
     --format="table(bindings.role)" \
     --filter="bindings.members:automend-watcher-sa"
   ```

4. **Verify Orchestrator Endpoint direct access using ID token:**
   ```bash
   TOKEN=$(gcloud auth print-identity-token)
   curl -i -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"service_id":"automend-target","revision_id":"rev-001","timestamp":"2026-08-31T12:00:00Z","failure_type":"error_rate_spike","log_snippet":"test","metrics":{"error_rate":0.8,"memory_mb":50,"restart_count":0},"last_known_good_revision":"rev-001"}' \
     https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents
   ```
