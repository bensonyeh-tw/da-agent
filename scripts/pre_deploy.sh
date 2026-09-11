#!/usr/bin/env bash
# Pre-deployment validation hook for Cymbal Operations Agent
set -euo pipefail

echo "========================================="
echo "  Cymbal Operations Agent: Pre-Deploy    "
echo "========================================="

# 1. Check Required Environment Variables
echo "[1/4] Validating environment variables..."
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-benson-data-elevate}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
echo "  GOOGLE_CLOUD_PROJECT: ${PROJECT_ID}"
echo "  GOOGLE_CLOUD_LOCATION: ${LOCATION}"

# 2. Verify Database Provisioning
echo "[2/4] Verifying database resources and schemas..."
uv run python scripts/provision_databases.py

# 3. Run Code Quality / Lint Checks
echo "[3/4] Running code quality and lint checks..."
uv run --extra lint ruff check app/ tests/

# 4. Run Unit and Integration Tests
echo "[4/4] Running unit and integration tests..."
export INTEGRATION_TEST="TRUE"
uv run pytest tests/unit tests/integration/test_server_e2e.py

echo "========================================="
echo "  Pre-Deploy Validation PASSED!          "
echo "========================================="
