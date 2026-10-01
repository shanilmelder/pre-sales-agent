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
docker compose --profile local exec api alembic upgrade head   # baseline: enables pgvector

curl http://localhost:8000/api/v1/health   # {"status":"ok","version":"...","db":"ok"}
curl http://localhost:3000/healthz         # {"status":"ok","version":"..."}
```

- Web: http://localhost:3000
- API docs: http://localhost:8000/api/v1/docs; spec at `/api/v1/openapi.json`
- Stop: `docker compose --profile local down` (add `-v` to drop the database volume)

All published ports bind to `127.0.0.1`. If Postgres is down, `/api/v1/health` returns
`503` problem+json with `code: db_unavailable` and the `api` container turns unhealthy.

## Backend

```sh
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run lint-imports                   # architecture contracts
uv run pytest                         # DB-up health test is skipped without PSA_DATABASE_URL
PSA_DATABASE_URL=postgresql+psycopg://psa:change-me-local-only@localhost:5432/psa uv run pytest
uv run python -m app.main_api         # run the API outside Docker (port 8000)
```

Configuration is read only by `app/platform/config.py` from `PSA_*` environment variables.
Errors are RFC 9457 problem+json `{type, title, status, code, detail, instance}`. Logs are
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

- **backend**: ruff, mypy, import-linter contracts, Alembic upgrade and pytest against a
  pgvector Postgres service.
- **web**: lint, typecheck, build.
- **compose**: brings up the local stack, checks both health endpoints and the build
  version, applies migrations, and checks the generated client is current.

Architecture rules enforced in CI: only `app/orchestration` may import `langgraph`, and no
module imports another module's `domain` or `adapters` package.
