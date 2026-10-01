# Pre-Sales Agent

Agentic AI Presales Platform. A modular monolith: one Python backend (run as `api` and
`worker`), one Next.js web app, Postgres 18 with pgvector, all on Docker Compose. The
architecture is defined in
`_bmad-output/planning-artifacts/architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md`.

## Layout

```text
compose.yaml          local stack (postgres, api, web); prod services arrive in Story 1.2
.env.example          local settings template (copy to .env, never commit .env)
backend/              FastAPI app, uv project (Python 3.13)
  app/modules/        business modules, each with api/ application/ domain/ adapters/
  app/orchestration/  LangGraph graphs (the only package allowed to import langgraph)
  app/agents/         proposal-only agents
  app/platform/       config, errors (problem+json), logging (JSON), db, ...
  app/main_api.py     api process (HTTP only)
  app/main_worker.py  worker process (jobs only; placeholder until Epic 2)
  migrations/         Alembic (expand/contract only)
  tests/              pytest, including architecture boundary tests
web/                  Next.js 16 App Router + shadcn/ui; src/lib/api = generated client
evals/                agent reference sets (later)
ops/                  deploy, backup, runbooks, Caddyfile, Modelfiles (Story 1.2+)
```

## Prerequisites

- Docker with Compose v2+
- [uv](https://docs.astral.sh/uv/) 0.12+ (fetches Python 3.13 itself)
- Node 24 LTS and npm

## Run the local stack

```sh
cp .env.example .env
docker compose --profile local up --build --wait -d
set -a; . ./.env; set +a                 # POSTGRES_* for the owner URL below
# The api container runs as psa_app; only this command gets the owner URL.
docker compose --profile local exec -T \
  -e PSA_MIGRATIONS_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}" \
  api alembic upgrade head

curl http://localhost:8000/api/v1/health   # {"status":"ok","version":"...","db":"ok"}
curl http://localhost:3000/healthz         # {"status":"ok","version":"..."}
```

- Web: http://localhost:3000
- API docs: http://localhost:8000/api/v1/docs; spec at `/api/v1/openapi.json`
- Stop: `docker compose --profile local down` (add `-v` to drop the database volume)

### Database roles

Postgres has two roles. `POSTGRES_USER` owns the schema and runs Alembic
(`PSA_MIGRATIONS_DATABASE_URL`). `psa_app` is the least-privileged login role the api and
pytest connect as (`PSA_DATABASE_URL`, password `PSA_APP_DB_PASSWORD`). It is created by
`ops/postgres/init/10-app-role.sh`, which Postgres runs only when it initialises an empty
volume. Migrations grant it SELECT and INSERT only on `platform_trace_events` (the trace is
append-only) and SELECT, INSERT, UPDATE, DELETE on later tables.

**Existing local volume from before Story 1.4:** the init script has not run, so recreate
the volume once (this deletes local data), then re-apply migrations:

```sh
docker compose --profile local down -v
docker compose --profile local up --build --wait -d
# then the `alembic upgrade head` command from "Run the local stack" above
```

Also add `PSA_APP_DB_PASSWORD` and `PSA_MIGRATIONS_DATABASE_URL` to your `.env` and point
`PSA_DATABASE_URL` at `psa_app` (see `.env.example`).

All published ports bind to `127.0.0.1`. If Postgres is down, `/api/v1/health` returns
`503` problem+json with `code: db_unavailable` and the `api` container turns unhealthy.

## Backend

```sh
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run lint-imports                   # architecture contracts
uv run pytest                         # DB-backed tests are skipped without PSA_DATABASE_URL
# DB-backed tests: migrate as the owner, test as psa_app (values from .env.example)
PSA_MIGRATIONS_DATABASE_URL=postgresql+psycopg://psa:change-me-local-only@localhost:5432/psa \
  uv run alembic upgrade head
PSA_DATABASE_URL=postgresql+psycopg://psa_app:change-me-app-local-only@localhost:5432/psa \
  uv run pytest
uv run python -m app.main_api         # run the API outside Docker (port 8000)
```

Configuration is read only by `app/platform/config.py` from `PSA_*` environment variables.
Errors are RFC 9457 problem+json `{type, title, status, code, detail, instance}`.

Platform core (AD-3): every mutation goes through one path inside a request-scoped Unit of
Work (`app/platform/uow.py`, handler parameter `uow: UoW`): `authorize` (identity's
`application/public.py`), domain rules, `row_version` check (`app/platform/concurrency.py`,
`If-Match` required: 428 if missing, 412 on mismatch), write, then
`app.platform.trace.append(uow, ...)`. Commands never commit; only the edge does. Logs are
JSON lines and carry IDs only, never customer content.

## Web

```sh
cd web
npm ci
npm run dev                           # http://localhost:3000
npm run lint && npm run typecheck && npm run build
npm run gen:api                       # regenerate src/lib/api from a running API
```

`gen:api` reads `$PSA_API_URL/api/v1/openapi.json` (default `http://localhost:8000`), or a
URL or file passed after `--`. The web app talks to the backend only through the generated
client in `src/lib/api`. Commit the regenerated files; CI fails if they drift.

## CI

`.github/workflows/ci.yml` runs on every PR and on `main`:

- **backend**: ruff, mypy, import-linter contracts, then against a pgvector Postgres
  service: create `psa_app`, Alembic upgrade/downgrade/upgrade as the owner, `alembic
  check` (models match migrations), and pytest as `psa_app`.
- **web**: lint, typecheck, build.
- **compose**: brings up the local stack, checks both health endpoints and the build
  version, applies migrations, and checks the generated client is current.

Architecture rules enforced in CI: only `app/orchestration` may import `langgraph`, no
module imports another module's `domain` or `adapters` package, `app/platform` imports no
business module, and nothing outside `app/platform/uow.py` calls `.commit(`.
