#!/usr/bin/env bash
# Run once per terminal (or add to your shell profile) so this project's terminal is ready.
# Usage: source scripts/setup_terminal.sh   OR   ./scripts/setup_terminal.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
  echo "Error: pyproject.toml not found. Run this from the AML project root." >&2
  exit 1
fi

# Ensure Poetry is on PATH (common install paths)
export PATH="$HOME/.local/bin:$HOME/.poetry/bin:$PATH"
if ! command -v poetry &>/dev/null; then
  echo "Poetry not found. Install from https://python-poetry.org/docs/#installation" >&2
  exit 1
fi

poetry install --no-interaction
echo "Deps installed. Activate the env with: poetry shell"
echo "Then run: make ci"
# If sourced, drop into poetry shell; if executed, just exit 0
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  exec poetry shell
fi
