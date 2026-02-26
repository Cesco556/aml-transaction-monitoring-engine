# make ci output after RULES_VERSION patch

## Patch applied

- **`src/aml_monitoring/__init__.py`**: `RULES_VERSION` is now `os.environ.get("AML_RULES_VERSION") or _git_version() or "1.0.0"`. `_git_version()` runs `git describe --always --dirty` (with timeout 5s) and returns `None` if git is missing or fails.
- **`tests/test_config.py`**: Added `test_rules_version_respects_env()` — runs a subprocess with `AML_RULES_VERSION=2.0.0` and asserts `RULES_VERSION == "2.0.0"`.

## Run make ci locally

From the project root:

```bash
cd "/Users/cesco/Downloads/Fintech Projects /AML Transaction Monitoring Engine Project"
make ci
```

## Paste the output below

(Replace this line with the full terminal output of `make ci`.)

```
```
