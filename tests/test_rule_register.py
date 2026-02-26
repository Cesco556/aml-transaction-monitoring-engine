"""Tests for rule register validation (CI governance)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_rule_register_valid_from_repo_root() -> None:
    """Running validate_rule_register.py from repo root must succeed (current repo state)."""
    root = _repo_root()
    result = subprocess.run(
        [sys.executable, "scripts/validate_rule_register.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def test_rule_register_fails_when_missing(tmp_path: Path) -> None:
    """When docs/rule_register.csv is missing, validator exits non-zero."""
    root = _repo_root()
    script = root / "scripts" / "validate_rule_register.py"
    # Run script with cwd=temp dir so it looks for docs/rule_register.csv in temp (missing)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
