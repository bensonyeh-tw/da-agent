#!/usr/bin/env bash
# Post-deployment validation hook for Cymbal Operations Agent
set -euo pipefail

echo "========================================="
echo "  Cymbal Operations Agent: Post-Deploy   "
echo "========================================="

SERVICE_URL="${1:-${APP_URL:-http://localhost:8000}}"
echo "Target Service URL: ${SERVICE_URL}"

# 1. Health Probe Verification
echo "[1/3] Verifying service liveness /health..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/health" || echo "000")
if [ "$HTTP_STATUS" -eq 200 ]; then
    echo "  Liveness check: SUCCESS (HTTP 200)"
else
    echo "  Liveness check: FAILED (HTTP ${HTTP_STATUS})"
    exit 1
fi

# 2. A2A Agent Card Verification
echo "[2/3] Verifying A2A Agent Card discovery..."
AGENT_CARD_URL="${SERVICE_URL}/a2a/app/.well-known/agent-card.json"
CARD_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${AGENT_CARD_URL}" || echo "000")
if [ "$CARD_STATUS" -eq 200 ]; then
    echo "  A2A Agent Card: SUCCESS (HTTP 200)"
else
    echo "  A2A Agent Card: FAILED (HTTP ${CARD_STATUS})"
    exit 1
fi

# 3. Bigtable MCP Toolbox Endpoint Smoke Check
echo "[3/3] Smoke checking Database Toolbox MCP Endpoint..."
BIGTABLE_URL="${BIGTABLE_MCP_URL:-https://mcp-toolbox-bigtable-364623295357.us-central1.run.app}"
MCP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BIGTABLE_URL}" || echo "000")
echo "  Database Toolbox MCP endpoint status: HTTP ${MCP_STATUS}"

echo "========================================="
echo "  Post-Deploy Validation PASSED!         "
echo "========================================="
