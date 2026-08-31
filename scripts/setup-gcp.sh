#!/usr/bin/env bash
# AutoMend — GCP Infrastructure Setup Script
# Run this once before deploying any services.
# Prerequisites: gcloud CLI installed and authenticated (gcloud auth login)
set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-automend-hackathon}"
PROJECT_NAME="AutoMend"
REGION="${GCP_REGION:-us-central1}"

# Service account names
ORCHESTRATOR_SA="automend-orchestrator"
WATCHER_SA="automend-watcher"
DIAGNOSIS_SA="automend-diagnosis"

# ─── Step 1: Create GCP Project ─────────────────────────────────────────────
echo "▶ Creating GCP project: ${PROJECT_ID}"
if gcloud projects describe "${PROJECT_ID}" &>/dev/null; then
  echo "  ✓ Project already exists"
else
  gcloud projects create "${PROJECT_ID}" --name="${PROJECT_NAME}"
  echo "  ✓ Project created"
fi

gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

# ─── Step 2: Link billing account ───────────────────────────────────────────
echo ""
echo "▶ Linking billing account"
echo "  ⚠ You need to run this manually with your billing account ID:"
echo "    gcloud billing projects link ${PROJECT_ID} --billing-account=YOUR_BILLING_ACCOUNT_ID"
echo "  Find your billing account ID with: gcloud billing accounts list"
echo ""

# ─── Step 3: Enable required GCP APIs ───────────────────────────────────────
echo "▶ Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}"
echo "  ✓ APIs enabled"

# ─── Step 4: Create Firestore database (Native mode) ────────────────────────
echo ""
echo "▶ Creating Firestore database (Native mode, ${REGION})"
if gcloud firestore databases describe --project="${PROJECT_ID}" &>/dev/null; then
  echo "  ✓ Firestore database already exists"
else
  gcloud firestore databases create --location="${REGION}" --project="${PROJECT_ID}"
  echo "  ✓ Firestore database created"
fi

# ─── Step 5: Create service accounts ────────────────────────────────────────
echo ""
echo "▶ Creating service accounts..."

for SA_NAME in "${ORCHESTRATOR_SA}" "${WATCHER_SA}" "${DIAGNOSIS_SA}"; do
  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "  ✓ ${SA_NAME} already exists"
  else
    gcloud iam service-accounts create "${SA_NAME}" \
      --display-name="AutoMend $(echo ${SA_NAME} | sed 's/automend-//' | sed 's/\b./\U&/g')" \
      --project="${PROJECT_ID}"
    echo "  ✓ ${SA_NAME} created"
  fi
done

# ─── Step 6: Grant IAM roles ────────────────────────────────────────────────
echo ""
echo "▶ Granting IAM roles..."

ORC_SA_EMAIL="${ORCHESTRATOR_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
WAT_SA_EMAIL="${WATCHER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
DIA_SA_EMAIL="${DIAGNOSIS_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

# Orchestrator needs: Firestore read/write + Cloud Run admin
echo "  Granting ${ORCHESTRATOR_SA} → roles/datastore.user"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${ORC_SA_EMAIL}" \
  --role="roles/datastore.user" \
  --condition=None

echo "  Granting ${ORCHESTRATOR_SA} → roles/run.admin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${ORC_SA_EMAIL}" \
  --role="roles/run.admin" \
  --condition=None

# Watcher needs: invoke the orchestrator (granted after orchestrator is deployed)
# Diagnosis agent needs: nothing on project level (orchestrator invokes it)
echo ""
echo "  ℹ After deploying services, run these to grant invoke permissions:"
echo "    gcloud run services add-iam-policy-binding automend-orchestrator \\"
echo "      --region=${REGION} \\"
echo "      --member=\"serviceAccount:${WAT_SA_EMAIL}\" \\"
echo "      --role=\"roles/run.invoker\""
echo ""
echo "    gcloud run services add-iam-policy-binding automend-diagnosis \\"
echo "      --region=${REGION} \\"
echo "      --member=\"serviceAccount:${ORC_SA_EMAIL}\" \\"
echo "      --role=\"roles/run.invoker\""

# ─── Step 7: Set billing budget alert ───────────────────────────────────────
echo ""
echo "▶ Billing budget alert"
echo "  ⚠ Set a budget alert manually to avoid surprise charges:"
echo "    Go to: https://console.cloud.google.com/billing/budgets"
echo "    Create a budget of \$1 for project ${PROJECT_ID}"
echo "    Set alerts at 50% and 90%"

# ─── Step 8: Download service account key for local development ──────────────
echo ""
echo "▶ Generating local credentials file..."
KEY_FILE="$(pwd)/service-account-key.json"
gcloud iam service-accounts keys create "${KEY_FILE}" \
  --iam-account="${ORC_SA_EMAIL}" \
  --project="${PROJECT_ID}"
export GOOGLE_APPLICATION_CREDENTIALS="${KEY_FILE}"
echo "  ✓ Key written to ${KEY_FILE}"
echo "  ⚠ Add service-account-key.json to .gitignore!"

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  ✓ GCP infrastructure ready!"
echo ""
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Firestore: Native mode, ${REGION}"
echo ""
echo "  Next steps:"
echo "  1. Link your billing account (see Step 2 above)"
echo "  2. Set a \$1 billing budget alert"
echo "  3. Deploy services with: gcloud run deploy ..."
echo "══════════════════════════════════════════════════════════════"
