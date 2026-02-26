# API (and CLI) image; run migrations then uvicorn via docker-compose or CMD.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* ./
# Regenerate lock if pyproject.toml changed (e.g. after adding streamlit) so install succeeds
RUN poetry lock --no-update && poetry install --no-interaction --no-root

COPY src ./src
COPY config ./config
COPY scripts ./scripts
COPY .streamlit .streamlit/
COPY alembic.ini ./
COPY alembic ./alembic

# Default: run API (migrations expected to be run by compose or prior step)
CMD ["uvicorn", "aml_monitoring.api:app", "--host", "0.0.0.0", "--port", "8000"]
