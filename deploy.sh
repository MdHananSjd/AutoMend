#!/usr/bin/env bash
# AutoMend — Person A GCP Deployment Script (Target Service & Watcher)
set -e

# Configuration (Override via environment variables if desired)
GCP_PROJECT_ID="${GCP_PROJECT_ID:-automend-demo}"
GCP_REGION="${GCP_REGION:-us-central1}"
TARGET_SERVICE_NAME="${TARGET_SERVICE_NAME:-automend-target}"
WATCHER_SERVICE_NAME="${WATCHER_SERVICE_NAME:-automend-watcher}"
WATCHER_SA_NAME="${WATCHER_SA_NAME:-automend-watcher-sa}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents}"

echo "=== 1. Setting GCP Project and Region ==="
gcloud config set project "$GCP_PROJECT_ID"
gcloud config set run/region "$GCP_REGION"

echo "=== 2. Creating Watcher Service Account ==="
gcloud iam service-accounts create "$WATCHER_SA_NAME" \
    --display-name="AutoMend Watcher Service Account" || true

WATCHER_SA_EMAIL="${WATCHER_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

echo "=== 3. Assigning IAM Roles to Watcher Service Account ==="
# Grant Cloud Logging Viewer
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${WATCHER_SA_EMAIL}" \
    --role="roles/logging.viewer"

# Grant Cloud Monitoring Viewer
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${WATCHER_SA_EMAIL}" \
    --role="roles/monitoring.viewer"

echo "=== 4. Deploying Target Service to Cloud Run ==="
cd services/target-service
gcloud run deploy "$TARGET_SERVICE_NAME" \
    --source . \
    --region "$GCP_REGION" \
    --platform managed \
    --allow-unauthenticated \
    --min-instances 1 \
    --set-env-vars "DEBUG_MODE=true,SERVICE_ID=${TARGET_SERVICE_NAME}"
cd ../..

TARGET_URL=$(gcloud run services describe "$TARGET_SERVICE_NAME" --region "$GCP_REGION" --format 'value(status.url)')
echo "Target Service Deployed at: $TARGET_URL"

echo "=== 5. Deploying Watcher to Cloud Run ==="
cd services/watcher
gcloud run deploy "$WATCHER_SERVICE_NAME" \
    --source . \
    --region "$GCP_REGION" \
    --platform managed \
    --no-allow-unauthenticated \
    --min-instances 1 \
    --service-account "$WATCHER_SA_EMAIL" \
    --set-env-vars "GCP_PROJECT_ID=${GCP_PROJECT_ID},SERVICE_ID=${TARGET_SERVICE_NAME},ORCHESTRATOR_URL=${ORCHESTRATOR_URL},MOCK_MODE=false,DISABLE_AUTH=false,POLL_INTERVAL_SEC=5,COOLDOWN_SEC=60"
cd ../..

WATCHER_URL=$(gcloud run services describe "$WATCHER_SERVICE_NAME" --region "$GCP_REGION" --format 'value(status.url)')
echo "Watcher Deployed at: $WATCHER_URL"

echo "=== 6. Granting Watcher roles/run.invoker on Orchestrator Service ==="
ORCHESTRATOR_SERVICE_NAME="${ORCHESTRATOR_SERVICE_NAME:-automend-orchestrator}"
gcloud run services add-iam-policy-binding "$ORCHESTRATOR_SERVICE_NAME" \
    --region "$GCP_REGION" \
    --member="serviceAccount:${WATCHER_SA_EMAIL}" \
    --role="roles/run.invoker" || echo "Note: Grant run.invoker on Orchestrator once Orchestrator Cloud Run service is created."

echo "=== Person A Deployment Complete ==="
