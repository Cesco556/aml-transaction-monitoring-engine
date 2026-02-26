#!/usr/bin/env bash
# Demo script: start Docker stack, seed data, run rules, demonstrate API and reproduce-run.
# Idempotent and safe to rerun. Use --down to stop the stack when done.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

API_KEY="${API_KEY:-dev_key}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

if [[ "${1:-}" == "--down" ]]; then
  echo "Stopping stack (docker compose down)..."
  docker compose down
  echo "Demo stack stopped."
  exit 0
fi

echo "Checking Docker daemon..."
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable. Start Docker Desktop (or the Docker daemon) and try again." >&2
  exit 1
fi
echo "Docker daemon OK."

mkdir -p reports
echo "Starting stack (docker compose up -d --build)..."
docker compose up -d --build

echo "Waiting for API to be ready..."
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "$BASE_URL/alerts" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -sf "$BASE_URL/alerts" >/dev/null 2>&1; then
  echo "API did not become ready in time. Check: docker compose logs api" >&2
  exit 1
fi
echo "API is ready."

echo "Running Alembic migrations in api container..."
docker compose exec -T api poetry run alembic upgrade head
echo "Migrations done."

echo "Seeding synthetic data and generating alerts/network..."
docker compose exec -T api poetry run python scripts/generate_synthetic_data.py
docker compose exec -T api poetry run aml ingest data/synthetic/transactions.csv
docker compose exec -T api poetry run aml build-network
docker compose exec -T api poetry run aml run-rules
echo "Seed and rules done."

echo "Generating SAR reports (into reports/)..."
docker compose exec -T api poetry run aml generate-reports
echo "Reports done."

echo "Fetching first alert to get ALERT_ID and CORRELATION_ID..."
ALERTS_JSON="$(curl -s "$BASE_URL/alerts?limit=1")"
ALERT_ID="$(echo "$ALERTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id']) if d else exit(1)")"
CORRELATION_ID="$(echo "$ALERTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['correlation_id']) if d else exit(1)")"
echo "  ALERT_ID=$ALERT_ID CORRELATION_ID=$CORRELATION_ID"

echo "PATCH /alerts/$ALERT_ID (authenticated) to set disposition and status..."
curl -sf -X PATCH "$BASE_URL/alerts/$ALERT_ID" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"status":"closed","disposition":"false_positive"}' >/dev/null
echo "  Alert updated."

echo "POST /cases to create a demo case..."
CASE_RESPONSE="$(curl -s -X POST "$BASE_URL/cases" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{\"alert_ids\":[$ALERT_ID],\"priority\":\"HIGH\",\"assigned_to\":\"analyst1\",\"note\":\"Demo case\"}")"
CASE_ID="$(echo "$CASE_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")"
echo "  CASE_ID=$CASE_ID"

echo "Running reproduce-run for CORRELATION_ID (output in reports/)..."
REPRO_FILE="demo_repro_${CORRELATION_ID}.json"
docker compose exec -T api poetry run aml reproduce-run "$CORRELATION_ID" "/app/reports/$REPRO_FILE"
echo "  Wrote reports/$REPRO_FILE"

echo ""
echo "========== Demo summary =========="
echo "  ALERT_ID:       $ALERT_ID"
echo "  CORRELATION_ID: $CORRELATION_ID"
echo "  CASE_ID:        $CASE_ID"
echo "  SAR reports:    reports/ (JSON and CSV from generate-reports)"
echo "  Reproduce bundle: reports/$REPRO_FILE"
echo "  Dashboard:      http://127.0.0.1:8501"
echo "=================================="
echo "Stack is still running. To stop: ./scripts/demo.sh --down"
