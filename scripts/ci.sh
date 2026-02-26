#!/usr/bin/env bash
# Run CI from repo root: install deps and run make ci. Use from your Cursor terminal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v poetry &>/dev/null; then
  echo "Poetry is not installed or not on PATH." >&2
  echo "Install it with (macOS/Linux):" >&2
  echo "  curl -sSL https://install.python-poetry.org | python3 -" >&2
  echo "Then ensure Poetry is on PATH (e.g. \$HOME/.local/bin) and re-run this script." >&2
  exit 1
fi

poetry install
poetry run make ci
