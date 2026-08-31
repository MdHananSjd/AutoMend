# AutoMend — Person A GCP Deployment Script for PowerShell (Target Service & Watcher)
$ErrorActionPreference = "Stop"

$GCP_PROJECT_ID = if ($env:GCP_PROJECT_ID) { $env:GCP_PROJECT_ID } else { "automend-demo" }
$GCP_REGION = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-central1" }
$TARGET_SERVICE_NAME = if ($env:TARGET_SERVICE_NAME) { $env:TARGET_SERVICE_NAME } else { "automend-target" }
$WATCHER_SERVICE_NAME = if ($env:WATCHER_SERVICE_NAME) { $env:WATCHER_SERVICE_NAME } else { "automend-watcher" }
$WATCHER_SA_NAME = if ($env:WATCHER_SA_NAME) { $env:WATCHER_SA_NAME } else { "automend-watcher-sa" }
$ORCHESTRATOR_URL = if ($env:ORCHESTRATOR_URL) { $env:ORCHESTRATOR_URL } else { "https://automend-orchestrator-xxxxxx-uc.a.run.app/incidents" }
$ORCHESTRATOR_SERVICE_NAME = if ($env:ORCHESTRATOR_SERVICE_NAME) { $env:ORCHESTRATOR_SERVICE_NAME } else { "automend-orchestrator" }

Write-Host "=== 1. Setting GCP Project and Region ===" -ForegroundColor Green
gcloud config set project $GCP_PROJECT_ID
gcloud config set run/region $GCP_REGION

Write-Host "=== 2. Creating Watcher Service Account ===" -ForegroundColor Green
try {
    gcloud iam service-accounts create $WATCHER_SA_NAME --display-name="AutoMend Watcher Service Account"
} catch {
    Write-Host "Service account $WATCHER_SA_NAME already exists or creation skipped."
}

$WATCHER_SA_EMAIL = "${WATCHER_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

Write-Host "=== 3. Assigning IAM Roles to Watcher Service Account ===" -ForegroundColor Green
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID --member="serviceAccount:${WATCHER_SA_EMAIL}" --role="roles/logging.viewer"
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID --member="serviceAccount:${WATCHER_SA_EMAIL}" --role="roles/monitoring.viewer"

Write-Host "=== 4. Deploying Target Service to Cloud Run ===" -ForegroundColor Green
Set-Location services/target-service
gcloud run deploy $TARGET_SERVICE_NAME `
    --source . `
    --region $GCP_REGION `
    --platform managed `
    --allow-unauthenticated `
    --min-instances 1 `
    --set-env-vars "DEBUG_MODE=true,SERVICE_ID=${TARGET_SERVICE_NAME}"
Set-Location ../..

$TARGET_URL = gcloud run services describe $TARGET_SERVICE_NAME --region $GCP_REGION --format 'value(status.url)'
Write-Host "Target Service Deployed at: $TARGET_URL" -ForegroundColor Yellow

Write-Host "=== 5. Deploying Watcher to Cloud Run ===" -ForegroundColor Green
Set-Location services/watcher
gcloud run deploy $WATCHER_SERVICE_NAME `
    --source . `
    --region $GCP_REGION `
    --platform managed `
    --no-allow-unauthenticated `
    --min-instances 1 `
    --service-account $WATCHER_SA_EMAIL `
    --set-env-vars "GCP_PROJECT_ID=${GCP_PROJECT_ID},SERVICE_ID=${TARGET_SERVICE_NAME},ORCHESTRATOR_URL=${ORCHESTRATOR_URL},MOCK_MODE=false,DISABLE_AUTH=false,POLL_INTERVAL_SEC=5,COOLDOWN_SEC=60"
Set-Location ../..

$WATCHER_URL = gcloud run services describe $WATCHER_SERVICE_NAME --region $GCP_REGION --format 'value(status.url)'
Write-Host "Watcher Deployed at: $WATCHER_URL" -ForegroundColor Yellow

Write-Host "=== 6. Granting Watcher roles/run.invoker on Orchestrator Service ===" -ForegroundColor Green
try {
    gcloud run services add-iam-policy-binding $ORCHESTRATOR_SERVICE_NAME `
        --region $GCP_REGION `
        --member="serviceAccount:${WATCHER_SA_EMAIL}" `
        --role="roles/run.invoker"
} catch {
    Write-Host "Note: Grant run.invoker on Orchestrator once Orchestrator Cloud Run service is created." -ForegroundColor Yellow
}

Write-Host "=== Person A Deployment Complete ===" -ForegroundColor Green
