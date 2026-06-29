# Praxis Agents OS — Backend API

FastAPI backend for the Praxis Agents OS platform.

## Dev setup

```bash
# Install all dependencies (including dev group)
uv sync

# Run locally
uv run python main.py
# or directly via uvicorn
uv run uvicorn main:app --reload --port 8080
```

## Notes

- The API binds to `0.0.0.0:8080` in Docker; locally it defaults to port `8000` when run via `python main.py`.
- Environment variables are loaded from `.env` (see `.env.example` for required keys).

## Database migrations

Alembic owns database schema changes for this service. Migrations are run
explicitly from `apps/api`; the API does not apply migrations at startup.

Required runtime environment variables, including `DATABASE_URL`, `SECRET_KEY`,
`ENCRYPTION_KEY`, and `INTERNAL_SCHEDULE_TRIGGER_SECRET`, must be present when
running Alembic because the model registry imports the normal application
settings.

Apply all migration heads:

```bash
uv run alembic upgrade heads
```

Create a public/core-schema migration:

```bash
uv run alembic revision --autogenerate \
  --head core@head \
  --version-path alembic/versions/core \
  -m "describe core schema change"
```

Create an app-schema migration:

```bash
uv run alembic revision --autogenerate \
  --head app@head \
  --version-path alembic/versions/app \
  -m "describe app schema change"
```

Check that the current models match the migration state:

```bash
uv run alembic check
```
