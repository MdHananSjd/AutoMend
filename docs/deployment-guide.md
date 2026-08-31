# AutoMend — Deployment Guide

Step-by-step guide for deploying all four services to Google Cloud Run.

## Prerequisites
- `gcloud` CLI installed and authenticated
- Docker installed
- Firebase CLI installed (`npm install -g firebase-tools`)
- GCP project with billing enabled

## 1. GCP Setup

Run the provisioning script:
```bash
bash scripts/setup-gcp.sh
```

This creates:
- Firestore database (Native mode, us-central1)
- Service accounts: `automend-orchestrator`, `automend-watcher`, `automend-diagnosis`
- IAM bindings for cross-service auth

### Manual IAM additions needed after setup script:
```bash
# Orchestrator needs to pull images when deploying new revisions
gcloud projects add-iam-policy-binding automend-hackathon \
  --member="serviceAccount:automend-orchestrator@automend-hackathon.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"

# Orchestrator needs to act as target service's SA
gcloud projects add-iam-policy-binding automend-hackathon \
  --member="serviceAccount:automend-orchestrator@automend-hackathon.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## 2. Deploy Target Service

```bash
gcloud run deploy automend-target \
  --source ./services/target-service \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --set-env-vars "DEBUG_MODE=true,SERVICE_ID=automend-target" \
  --project automend-hackathon
```

## 3. Deploy Watcher

```bash
gcloud run deploy automend-watcher \
  --source ./services/watcher \
  --region us-central1 \
  --no-allow-unauthenticated \
  --min-instances 0 \
  --service-account automend-watcher@automend-hackathon.iam.gserviceaccount.com \
  --set-env-vars "MOCK_MODE=false,DISABLE_AUTH=false,ORCHESTRATOR_URL=https://automend-orchestrator-247530183292.us-central1.run.app/incidents,GCP_PROJECT_ID=automend-hackathon,SERVICE_ID=automend-target" \
  --project automend-hackathon
```

## 4. Deploy Diagnosis Agent

```bash
gcloud run deploy automend-diagnosis \
  --source ./services/diagnosis-agent \
  --region us-central1 \
  --no-allow-unauthenticated \
  --min-instances 0 \
  --set-env-vars "GOOGLE_API_KEY=your-ai-studio-key" \
  --project automend-hackathon
```

## 5. Deploy Orchestrator

```bash
gcloud run deploy automend-orchestrator \
  --source ./services/orchestrator \
  --region us-central1 \
  --no-allow-unauthenticated \
  --min-instances 0 \
  --service-account automend-orchestrator@automend-hackathon.iam.gserviceaccount.com \
  --set-env-vars "DIAGNOSIS_AGENT_URL=https://automend-diagnosis-247530183292.us-central1.run.app,TARGET_SERVICE_URL=https://automend-target-247530183292.us-central1.run.app/health,TARGET_CLOUD_RUN_SERVICE=automend-target,GCP_PROJECT_ID=automend-hackathon,DISABLE_AUTH=false" \
  --project automend-hackathon
```

## 6. Grant Cross-Service Invoke Permissions

```bash
# Watcher → Orchestrator
gcloud run services add-iam-policy-binding automend-orchestrator \
  --region us-central1 \
  --member="serviceAccount:automend-watcher@automend-hackathon.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Orchestrator → Diagnosis Agent
gcloud run services add-iam-policy-binding automend-diagnosis \
  --region us-central1 \
  --member="serviceAccount:automend-orchestrator@automend-hackathon.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Orchestrator → Target Service (for health polling)
gcloud run services add-iam-policy-binding automend-target \
  --region us-central1 \
  --member="serviceAccount:automend-orchestrator@automend-hackathon.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## 7. Deploy Dashboard

```bash
cd dashboard
firebase deploy --only hosting --project automend-hackathon
```

## 8. Verify

```bash
TOKEN=$(gcloud auth print-identity-token)

# Health checks
curl -H "Authorization: Bearer $TOKEN" https://automend-target-247530183292.us-central1.run.app/health
curl -H "Authorization: Bearer $TOKEN" https://automend-orchestrator-247530183292.us-central1.run.app/health
curl -H "Authorization: Bearer $TOKEN" https://automend-watcher-247530183292.us-central1.run.app/health
curl -H "Authorization: Bearer $TOKEN" https://automend-diagnosis-247530183292.us-central1.run.app/health

# Trigger test failure
curl -X POST -H "Authorization: Bearer $TOKEN" https://automend-target-247530183292.us-central1.run.app/debug/error-spike
```

## Cost Guardrails
- **ALL services use `--min-instances=0`** — zero cost when idle
- Set a $1 billing budget alert at https://console.cloud.google.com/billing/budgets
- Free tier covers: 2M Cloud Run requests, 1 GiB Firestore, 10 GB Firebase Hosting per month
- Total projected cost for hackathon: **$0**
