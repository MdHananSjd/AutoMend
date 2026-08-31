#!/usr/bin/env bash
# AutoMend — Demo Environment Reset Script (Person A)
set -e

TARGET_URL="${TARGET_URL:-http://localhost:8000}"
WATCHER_URL="${WATCHER_URL:-http://localhost:8080}"

echo "=== 1. Resetting Target Service Failure Injection State ==="
curl -s -X POST "${TARGET_URL}/debug/reset" || echo "Warning: Target Service reset failed."

echo "=== 2. Resetting Watcher Cooldown State ==="
curl -s -X POST "${WATCHER_URL}/reset" || echo "Warning: Watcher reset failed."

echo "=== 3. Verifying Target Service Health ==="
HEALTH_RESP=$(curl -s "${TARGET_URL}/health")
echo "Target Health: ${HEALTH_RESP}"

echo "=== Demo Environment Reset Complete ==="
