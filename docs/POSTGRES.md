# Using PostgreSQL

The engine supports PostgreSQL for faster run-rules and production use. Same logic and results as SQLite; only the database changes.

## Quick start (local with Docker)

1. **Start PostgreSQL**
   ```bash
   docker-compose up -d
   ```
   Waits until Postgres is ready (or run `docker-compose up` and wait for "database system is ready").

2. **Set the database URL**
   ```bash
   export AML_DATABASE_URL="postgresql://aml:aml@127.0.0.1:5432/aml"
   ```
   (Or add to `.env` and source it.)

3. **Run migrations (create tables)**
   ```bash
   poetry run alembic upgrade head
   ```

4. **Use the app as usual**
   ```bash
   AML_ENV=dev poetry run aml ingest /path/to/transactions.csv
   AML_ENV=dev poetry run aml run-rules
   AML_ENV=dev poetry run aml build-network
   AML_ENV=dev poetry run aml generate-reports
   ```
   With `AML_DATABASE_URL` set, all commands use PostgreSQL.

## Without Docker

- Install PostgreSQL 14+ and create a database and user.
- Set `AML_DATABASE_URL` to your connection string, e.g.:
  - `postgresql://USER:PASSWORD@HOST:5432/DATABASE`
  - or `postgresql+psycopg2://...` if you need to specify the driver.
- Run `poetry run alembic upgrade head` once, then use the CLI/API as above.

## Switching back to SQLite

- Unset the variable: `unset AML_DATABASE_URL`
- The app will use the URL from config (e.g. `config/dev.yaml` → `sqlite:///./data/aml_dev.db`).

## Notes

- **First run**: Migrations create all tables and indexes (including `ix_transactions_account_ts`, `ix_transactions_account_ts_amount`). No need to copy data from SQLite unless you want to; you can re-ingest into Postgres.
- **High-risk country**: Use `AML_ENV=dev` or a config that replaces placeholder countries (XX/YY) with real ISO codes, or run-rules will fail validation.
