# AML Transaction Monitoring - Makefile (macOS/Linux)
# All commands run via Poetry venv; no need for ruff/pytest/black/mypy on system PATH.
PORT ?= 8000
.PHONY: help install shell format lint test ci run ingest train run-rules reports serve dashboard stream synthetic kill-port verify-patch migrate makemigration test-postgres demo demo-down validate-register

help:
	@echo "Targets: install, shell, format, lint, test, ci, validate-register, test-postgres, run, ingest, train, run-rules, reports, serve, dashboard, stream, synthetic, kill-port, verify-patch, migrate, makemigration, demo, demo-down"

validate-register:
	@poetry run python scripts/validate_rule_register.py

install:
	@poetry install

shell:
	@echo "Note: Prefer 'poetry run make <target>' or 'poetry run aml <cmd>' so the venv is explicit; use 'poetry shell' only if you need an interactive subshell."
	@poetry shell

format:
	@poetry run black src tests scripts
	@poetry run ruff check src tests scripts --fix

lint:
	@poetry run ruff check src tests scripts
	@poetry run black --check src tests scripts
	@poetry run mypy src

test:
	@env -u DATABASE_URL poetry run pytest tests -v

test-ingest-rejects:
	@env -u DATABASE_URL poetry run pytest tests/test_ingest_rejects.py -v

test-adversarial:
	@env -u DATABASE_URL poetry run pytest tests/test_adversarial_evasion.py tests/test_ingest_rejects.py -v

test-determinism:
	@env -u DATABASE_URL poetry run pytest tests/test_determinism.py tests/test_run_rules.py -v -k "chunk or determinism or resume"

test-scenario:
	@env -u DATABASE_URL poetry run pytest tests/test_adversarial_evasion.py tests/test_determinism.py -v

ci: lint test validate-register

test-postgres:
	@poetry run pytest tests/test_postgres_smoke.py -v

run: ingest run-rules reports

ingest:
	@poetry run aml ingest data/synthetic/transactions.csv

train:
	@poetry run aml train

run-rules:
	@poetry run aml run-rules

reports:
	@poetry run aml generate-reports

serve:
	@AML_API_HOST=127.0.0.1 AML_API_PORT=$(PORT) poetry run aml serve-api

dashboard:
	@poetry run streamlit run scripts/dashboard.py

kill-port:
	@PIDS=$$(lsof -ti :$(PORT) 2>/dev/null); \
	if [ -n "$$PIDS" ]; then echo "Killing process(es) on port $(PORT): $$PIDS"; kill $$PIDS 2>/dev/null || true; else echo "No process using port $(PORT)"; fi

verify-patch:
	@$(MAKE) kill-port PORT=8001; \
	AML_ALLOW_SCHEMA_UPGRADE=true $(MAKE) run; \
	PORT=8001 $(MAKE) serve & \
	sleep 3; \
	AID=$$(curl -s http://127.0.0.1:8001/alerts | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id']) if d else exit(1)" 2>/dev/null) || exit 1; \
	echo "PATCH /alerts/$$AID"; \
	curl -s -w "\nHTTP_CODE:%{http_code}\n" -X PATCH "http://127.0.0.1:8001/alerts/$$AID" -H "Content-Type: application/json" -d '{"status":"closed","disposition":"false_positive"}'; \
	$(MAKE) kill-port PORT=8001

stream:
	@poetry run aml simulate-stream data/synthetic/transactions.csv --delay 0.5

synthetic:
	@poetry run python scripts/generate_synthetic_data.py

migrate:
	@poetry run alembic upgrade head

makemigration:
	@poetry run alembic revision --autogenerate -m "auto"

demo:
	@./scripts/demo.sh

demo-down:
	@./scripts/demo.sh --down
