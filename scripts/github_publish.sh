#!/usr/bin/env bash
# Publish this project to GitHub.
# Usage: bash scripts/github_publish.sh [REPO_NAME]
#   REPO_NAME defaults to aml-transaction-monitoring-engine if omitted.

cd "/Users/cesco/Downloads/Fintech Projects /AML Transaction Monitoring Engine Project"
REPO_NAME="${1:-aml-transaction-monitoring-engine}"

# 1) Prereqs
git --version
command -v gh >/dev/null && gh --version || echo "gh not installed"

# 2) Init git
git init

# 3) Create .gitignore ONLY if it doesn't exist
if [ ! -f .gitignore ]; then
  cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
.venv/
env/
.env
*.egg-info/
.eggs/
dist/
build/

# Tooling / OS
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.DS_Store
EOF
fi

# 4) Commit green state (won't error if nothing to commit)
git add -A
git commit -m "Initial commit: AML monitoring engine (CI green)" || echo "Nothing to commit (or commit failed). Check git status."

# 5) Create repo + push (choose ONE path)

# Path A (best): GitHub CLI
if command -v gh >/dev/null; then
  gh auth status || gh auth login
  gh repo create "$REPO_NAME" --public --source . --remote origin --push
else
  echo "gh not installed. Use Path B."
fi

# Path B (manual): create empty repo on GitHub, then run:
# git remote add origin <URL>
# git branch -M main
# git push -u origin main

# 6) Verify + CI proof
./scripts/ci.sh
git remote -v || true
