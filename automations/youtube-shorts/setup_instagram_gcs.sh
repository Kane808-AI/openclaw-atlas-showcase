#!/bin/bash
# One-time setup: create GCS bucket for Instagram Reels video staging
# Run this ONCE to enable the Instagram Reels upload leg of the pipeline.
#
# Requires: automation@example.com authenticated in gcloud
#   Run: gcloud auth login --account automation@example.com
#
# What this does:
#   1. Creates gs://showcase-instagram-staging in us-central1
#   2. Grants atlas-automation SA objectAdmin on that bucket
#   3. Verifies the SA can upload a test object

set -e

BUCKET="showcase-instagram-staging"
PROJECT="showcase-gcp-project"
SA="showcase-automation@showcase-gcp-project.iam.gserviceaccount.com"
SA_KEY="$HOME/.openclaw/credentials/google/brand75-service-account.json"
REGION="US"

echo "==> Checking active gcloud account..."
ACTIVE=$(gcloud config get-value account 2>/dev/null)
echo "    Active account: $ACTIVE"
if [[ "$ACTIVE" != "automation@example.com" ]]; then
  echo ""
  echo "ERROR: Run this first:"
  echo "  gcloud auth login --account automation@example.com"
  exit 1
fi

echo "==> Creating bucket gs://$BUCKET (if not exists)..."
if gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT" &>/dev/null; then
  echo "    Bucket already exists — skipping create"
else
  gcloud storage buckets create "gs://$BUCKET" \
    --project="$PROJECT" \
    --location="$REGION" \
    --uniform-bucket-level-access
  echo "    Bucket created"
fi

echo "==> Granting $SA objectAdmin on gs://$BUCKET..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"
echo "    IAM binding applied"

echo "==> Granting $SA signBlob on its own service account (for signed URLs)..."
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="$PROJECT"
echo "    signBlob permission applied"

echo "==> Verifying upload with service account key..."
/Users/example/.openclaw/venv/google/bin/python3 - <<'EOF'
import pathlib, sys
from google.cloud import storage
from google.oauth2 import service_account
import datetime

sa_file = pathlib.Path.home() / ".openclaw/credentials/google/brand75-service-account.json"
credentials = service_account.Credentials.from_service_account_file(
    str(sa_file),
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
client = storage.Client(project="showcase-gcp-project", credentials=credentials)
bucket = client.bucket("showcase-instagram-staging")
blob = bucket.blob("instagram/_test_probe.txt")
blob.upload_from_string(b"probe", content_type="text/plain")
url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(minutes=5), method="GET", credentials=credentials)
blob.delete()
print("    Upload + signed URL + delete: OK")
print("    Test URL was:", url[:80] + "...")
EOF

echo ""
echo "Setup complete. Instagram GCS staging is ready."
