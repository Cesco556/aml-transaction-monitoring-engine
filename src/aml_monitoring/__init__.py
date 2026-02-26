"""AML Transaction Monitoring MVP."""

import os
import subprocess

__version__ = "0.1.0"


# Audit-grade reproducibility: env > git describe > fallback
def _git_version() -> str | None:
    try:
        rev = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if rev.returncode == 0 and rev.stdout:
            return rev.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


RULES_VERSION = os.environ.get("AML_RULES_VERSION") or _git_version() or "1.0.0"
ENGINE_VERSION = "0.1.0"
