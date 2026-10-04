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
curl -I http://localhost:3000/             # 307 to /auth/login?returnTo=%2F (no session)
```

The `.env.example` Auth0 values are placeholders: the stack builds and starts, and the
health checks pass, but signing in needs a real tenant (see "Auth0 tenant setup" below).
An existing `.env` from before Story 1.4 Part B needs the `AUTH0_*` and `APP_BASE_URL`
lines from `.env.example`; compose refuses to start without them.

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

### Worker

The `worker` process (`app/main_worker.py`, AD-29) claims background jobs from the Postgres
queue table `platform_jobs` one at a time and runs them; the api only enqueues. It needs the
schema migrated (`alembic upgrade head`, see above) and connects as `psa_app`. In compose it
is the `worker` service (same backend image, `python -m app.main_worker`) and logs
`worker.started` when up: `docker compose --profile local logs -f worker`. Outside Docker:

```sh
cd backend
PSA_DATABASE_URL=postgresql+psycopg://psa_app:change-me-app-local-only@localhost:5432/psa \
  uv run python -m app.main_worker     # Ctrl+C to stop
```

On Windows it runs on the selector event loop (psycopg's async driver cannot use the
Proactor loop). On SIGTERM/SIGINT it cancels the current job and returns it to the queue.
Settings: `PSA_WORKER_POLL_S` (idle poll, default 1 s, jittered), `PSA_WORKER_CONCURRENCY`
(reserved, must be 1), `PSA_JOB_LEASE_S` (default 30 s; a dead worker's job is reclaimed
after it expires) and `PSA_JOB_HEARTBEAT_S` (default 10 s, at most half the lease).

Job types: `intake.parse_source` (Story 2.2 Part B) turns each added Source version into
plain text. Each file is parsed in a child process (`python -m
app.modules.intake.adapters.parse_cli`) with a wall-clock limit `PSA_PARSE_TIMEOUT_S`
(default 120 s, at most 600) and, on Linux, `RLIMIT_AS` `PSA_PARSE_MAX_MEMORY_MB` (default
1024) and `RLIMIT_CPU`. Parsers: stdlib for `.txt`, `.eml`, `.docx`, in-house `.vtt`, and
`pypdf` (BSD) for `.pdf`; `.msg` is not parsed yet (`not_supported`).

### ModelGateway

`app/platform/model_gateway/` (AD-8) is the only path to a model: host Ollama's native
`/api/chat` with `format` set to the output model's JSON Schema, validation and bounded
retries, a priority-aware slot limit, and one `platform_model_calls` row per call. Settings:
`PSA_OLLAMA_URL` (default `http://127.0.0.1:11434`), `PSA_MODEL_PROFILE_CHAT` (`demo-chat` =
`gpt-oss:120b-cloud`, or `local-chat` = `qwen3:8b`), `PSA_MODEL_SLOTS`,
`PSA_MODEL_MAX_RETRIES` and `PSA_MODEL_TIMEOUT_S`. `demo-chat` sends prompt text to Ollama's
cloud: until IT approves it, use it only with sample or anonymised Opportunities.

Host Ollama setup: set `OLLAMA_NUM_PARALLEL` on the host to at least `PSA_MODEL_SLOTS`. The
`api` and `worker` containers reach it at `host.docker.internal`; on Linux the host Ollama
must listen beyond loopback for that (`OLLAMA_HOST=0.0.0.0`). Host-side commands (smoke,
worker outside Docker) should use `PSA_OLLAMA_URL=http://127.0.0.1:11434`, not the
`host.docker.internal` value from `.env`. Smoke check (needs `ollama serve`, `ollama signin`
for cloud models, and a migrated database):

```sh
cd backend
PSA_OLLAMA_URL=http://127.0.0.1:11434 \
PSA_DATABASE_URL=postgresql+psycopg://psa_app:change-me-app-local-only@localhost:5432/psa \
  uv run python -m app.platform.model_gateway.smoke   # prints `ok` with tokens and latency
```

## Authentication (Auth0)

Auth0 (EU tenant) handles authentication only; roles live in `identity`, not in Auth0
RBAC. The web app (`@auth0/nextjs-auth0` v4, `web/src/proxy.ts`) mounts `/auth/login`,
`/auth/callback` and `/auth/logout`, sends visitors without a session to Universal Login
and returns them to the page they asked for. `/healthz` and static assets stay public.
Server components call the API through `web/src/lib/api/server.ts`, which sends the
user's access token for the API audience as `Authorization: Bearer`.

The API validates every token with PyJWT against the tenant's JWKS (RS256 only, `iss` =
`https://$AUTH0_DOMAIN/`, `aud` = `$AUTH0_AUDIENCE`, `exp`). The first valid token for an
unknown `sub` provisions a platform user with no roles and appends
`identity.user.provisioned` to the trace. `GET /api/v1/me` returns `{id, name, email,
roles}`. A user with no roles sees only "You're signed in, but you don't have access yet.
Ask an administrator to assign a role." Failures are problem+json: 401 `token_missing`,
`token_expired` or `token_invalid` (with `WWW-Authenticate: Bearer`), and 503
`auth_unavailable` when the JWKS can't be fetched. Sign out (avatar menu) ends the app
session and the Auth0 session.

### Auth0 tenant setup

1. Create a tenant in the **EU** region.
2. **Applications > Create Application > Regular Web Application.** In its settings:
   - Allowed Callback URLs: `http://localhost:3000/auth/callback`
   - Allowed Logout URLs: `http://localhost:3000`
   - Copy the Domain, Client ID and Client Secret.
3. **APIs > Create API.** Identifier: `https://api.pre-sales-agent` (any URI works; it
   becomes `AUTH0_AUDIENCE`), signing algorithm RS256. Turn on "Allow Offline Access" so
   sessions can refresh their access token. Leave RBAC off.
4. **Actions > Library > Create Action > Build from scratch**, trigger "Login / Post
   Login", with this code, then Deploy and add it to the Post Login trigger
   (**Actions > Triggers > post-login**). The API reads name and email only from these
   namespaced access-token claims; a token without the email claim is rejected with 401
   `token_invalid`.

   ```js
   exports.onExecutePostLogin = async (event, api) => {
     const namespace = "https://pre-sales-agent/";
     if (event.user.email) {
       api.accessToken.setCustomClaim(`${namespace}email`, event.user.email);
       api.accessToken.setCustomClaim(`${namespace}name`, event.user.name || event.user.email);
     }
   };
   ```

5. Put the values in your local `.env` (never commit it):

   ```sh
   AUTH0_DOMAIN=<tenant>.eu.auth0.com
   AUTH0_AUDIENCE=https://api.pre-sales-agent
   AUTH0_CLIENT_ID=<client id>
   AUTH0_CLIENT_SECRET=<client secret>
   AUTH0_SECRET=<output of: openssl rand -hex 32>
   APP_BASE_URL=http://localhost:3000
   ```

6. Restart the stack (`docker compose --profile local up --build --wait -d`) and open
   http://localhost:3000. A new user sees the no-access message until an administrator
   assigns a role (Story 1.6).

Running the API outside Docker, export `PSA_AUTH0_DOMAIN` and `PSA_AUTH0_AUDIENCE` (the
same values as `AUTH0_DOMAIN` and `AUTH0_AUDIENCE`).

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
- **compose**: brings up the local stack with the placeholder Auth0 values, checks both
  health endpoints and the build version, checks that `/` redirects to sign-in and that
  `/api/v1/me` without a token is 401, applies migrations, and checks the generated
  client is current.

Architecture rules enforced in CI: only `app/orchestration` may import `langgraph`, no
module imports another module's `domain` or `adapters` package, `app/platform` imports no
business module, and nothing outside `app/platform/uow.py` calls `.commit(`.
