#!/usr/bin/env bash
# Start the API (if not already running) and open the Streamlit dashboard.
# Run this script in your own terminal so the servers run on your machine and
# http://localhost:8501 works in your browser.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export AML_CONFIG_PATH="${AML_CONFIG_PATH:-config/default.yaml}"
export AML_ENV="${AML_ENV:-dev}"
export AML_API_PORT="${AML_API_PORT:-8001}"
export AML_DASHBOARD_API="${AML_DASHBOARD_API:-http://127.0.0.1:8001}"
API_PORT=8001

# Check if API is already up
if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${API_PORT}/health" 2>/dev/null | grep -q 200; then
  echo "API already running on port ${API_PORT}."
else
  echo "Starting API on port ${API_PORT} in the background..."
  poetry run aml serve-api &
  API_PID=$!
  echo "Waiting for API to be ready..."
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s -o /dev/null "http://127.0.0.1:${API_PORT}/health" 2>/dev/null; then
      echo "API is up."
      break
    fi
    sleep 1
  done
fi

echo ""
echo "Starting dashboard. Open in your browser: http://localhost:8501"
echo "API docs: http://127.0.0.1:${API_PORT}/docs"
echo ""
poetry run streamlit run scripts/dashboard.py --server.port 8501
