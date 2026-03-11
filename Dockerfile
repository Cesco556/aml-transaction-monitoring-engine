# === Stage 1: Builder ===
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* ./
RUN poetry lock --no-update && poetry install --no-interaction --no-root --only main

# === Stage 2: Runtime ===
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

# Non-root user
RUN groupadd --gid 1000 aml && \
    useradd --uid 1000 --gid aml --shell /bin/bash --create-home aml

# Copy virtualenv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY src ./src
COPY config ./config
COPY scripts ./scripts
COPY .streamlit .streamlit/
COPY alembic.ini ./
COPY alembic ./alembic

# Pre-create models dir for ML artifacts
RUN mkdir -p /app/models && chown -R aml:aml /app

USER aml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "aml_monitoring.api:app", "--host", "0.0.0.0", "--port", "8000"]
