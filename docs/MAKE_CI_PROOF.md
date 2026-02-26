# CI proof artifact (procurement-grade)

**Command:** `./scripts/ci.sh`

**Result summary:**
- **ruff:** pass (check + format)
- **black:** pass (57 files unchanged)
- **mypy:** pass (35 source files, no issues)
- **pytest:** 91 passed, 2 skipped, exit 0

**Exit code:** 0

**Date/time of run:** 2025-02-23 (local; run after CI green per agent verification)

**Reproducibility:** From repo root, run `./scripts/ci.sh`. Requires Poetry on PATH (see README § Run CI locally). CI also runs rule register validation (`scripts/validate_rule_register.py`).

**Git:** Add this file to version control when the project is in a git repo: `git add docs/MAKE_CI_PROOF.md`.
