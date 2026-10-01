---
title: 'Story 1.1: Project scaffold and local stack'
type: 'feature'
created: '2026-10-01'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '481fdb4d1989dedcfbedb51dda94ddddbedb4c09'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The repository holds only planning artifacts. Every later story needs the agreed modular-monolith layout, pinned versions, a local stack and a CI gate to build on.

**Approach:** Scaffold the monorepo following the architecture spine (backend FastAPI modular monolith, Next.js 16 web with shadcn/ui, compose with Postgres+pgvector), add `/api/v1/health`, OpenAPI → TS client generation, and a GitHub Actions CI pipeline that includes architecture-boundary tests.

## Boundaries & Constraints

**Always:** Pin versions exactly as in the spine's Stack table: Python 3.13, FastAPI 0.142.2, Pydantic 2.13.5, SQLAlchemy 2.1.1, Alembic 1.20.0, psycopg 3.3.6, PostgreSQL 18.6 via `pgvector/pgvector:0.8.6-pg18-trixie`, Node 24 LTS, Next.js 16.3.8, React 19.3.0, Tailwind 4.3.3, shadcn CLI 4.21.0. Use `uv` for Python and npm for web. Config comes only through `platform.config` (pydantic-settings, `PSA_` prefix). Errors use problem+json. Logs are JSON and contain IDs only.

**Never:** No business modules, tables, auth, Ollama, worker logic, LangGraph or deployment config. Those belong to Stories 1.2+ and Epic 2. Directories are created empty, with a `README.md`/`__init__.py` that names their purpose. No secrets committed; `.env.example` only.

**Decisions:** Verification is local and full. Docker Desktop is installed (Docker 29.8.1, Compose v5.5.1). `docker compose up --wait` with the local profile, plus the DB-up health test against the compose Postgres, must pass on this machine before review. CI also runs the compose job.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Health OK | `GET /api/v1/health`, DB reachable | 200 `{status:"ok", version, db:"ok"}` | N/A |
| DB down | Postgres stopped | 503 problem+json `code: db_unavailable` | Health check fails; compose shows unhealthy |
| Unknown route | `GET /api/v1/nope` | 404 problem+json `code: not_found` | N/A |
| Boundary violation | A module imports `langgraph`, or another module's `domain`/`adapters` | Architecture test fails in CI | Merge blocked |

</frozen-after-approval>

## Code Map

- Git: repo on `main`, remote `origin` = GitHub `shanilmelder/pre-sales-agent`, one commit (`Initial`) with tooling and planning. `.gitignore` ignores only `/graft/`; append to it, don't replace it. Work on a feature branch `story/1-1-project-scaffold`.
- Toolchain here: uv 0.12.2 (fetches Python 3.13), Node 24.14.1/npm, Docker at `C:\Users\esm\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe` (not yet on this session's PATH; call it by full path or prepend that dir).
- Greenfield: no application code exists. The existing `_bmad/`, `_bmad-output/`, `.claude/`, `.agents/`, `.github/agents/`, `docs/` and `graft/` folders are tooling and planning; leave them unchanged.
- `.github/` -- holds agent files only; CI is added at `.github/workflows/ci.yml`.
- Layout source of truth: spine "Structural Seed" and "Design Paradigm" (layers `api/ application/ domain/ adapters/` per module).

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- create a uv project with pinned deps plus dev tools (pytest, ruff, mypy, httpx, import-linter) -- reproducible builds
- [x] `backend/app/{modules,orchestration,agents,platform}/`, `backend/app/main_api.py`, `backend/app/main_worker.py` -- skeleton packages. `main_worker.py` is a no-op loop placeholder that logs a start event -- spine layout (AD-1, AD-2)
- [x] `backend/app/platform/config.py`, `platform/errors.py`, `platform/logging.py`, `platform/db.py` -- settings, problem+json handlers (404/500/503), JSON logger, async engine with a ping -- needed by health
- [x] `backend/app/main_api.py` -- FastAPI app with `/api/v1/health` (version from env/build arg), OpenAPI served at `/api/v1/openapi.json` -- I/O matrix
- [x] `backend/migrations/` -- Alembic init with an empty baseline revision that enables the `vector` extension -- later stories add tables
- [x] `backend/tests/test_health.py`, `backend/tests/test_architecture.py` -- health matrix tests; import-linter contracts (only `orchestration` may import `langgraph`; no cross-module `domain`/`adapters` imports) -- AD-2, AD-5
- [x] `backend/Dockerfile` -- slim Python 3.13 image running uvicorn, healthcheck -- compose
- [x] `web/` -- create-next-app 16 (TS, Tailwind 4, App Router, ESLint), shadcn init, placeholder home page, `Dockerfile`, a `/healthz` route -- web skeleton
- [x] `web/package.json` script `gen:api` -- openapi-typescript (or @hey-api/openapi-ts) generating into `web/src/lib/api` from the backend spec -- AD-16
- [x] `compose.yaml`, `.env.example` -- `postgres` (pgvector image, volume, healthcheck), `api`, `web` with healthchecks and `restart: unless-stopped`; local profile -- local stack
- [x] `evals/README.md`, `ops/README.md`, root `README.md`, `.gitignore`, `.editorconfig` -- purpose stubs and how to run -- structure
- [x] `.github/workflows/ci.yml` -- jobs: backend (ruff, mypy, pytest with a Postgres service), web (lint, typecheck, build), compose (`up --wait` + curl both health endpoints) -- merge gate

**Acceptance Criteria:**
- Given a fresh clone, when the documented setup runs, then `postgres`, `api` and `web` start and pass healthchecks, and `GET /api/v1/health` returns 200 with the build version.
- Given the source tree, when inspected, then it matches the spine's Structural Seed and every dependency is pinned to the Stack table.
- Given the web app, when `npm run gen:api` runs against a running API, then a typed client appears in `web/src/lib/api` and the web build passes.
- Given a PR, when CI runs, then backend lint, typecheck and tests, web lint, typecheck and build, and the architecture contracts all run, and any failure fails the workflow.

## Implementation Notes

- Non-spine deps are pinned exactly to the locked resolution: pydantic-settings 2.15.0, uvicorn 0.54.0; dev pytest 9.1.1, ruff 0.16.9, mypy 2.3.1, httpx 0.28.1, import-linter 2.15. SQLAlchemy uses the `asyncio` extra (2.1 no longer pulls greenlet by default). Web deps are all exact (`.npmrc` `save-exact`); shadcn 4.21.0 is also a runtime dep because the generated `globals.css` imports `shadcn/tailwind.css`. shadcn init used the `base-nova` preset with the `neutral` base color.
- Client generation: `openapi-typescript` 7.13.0 writes `web/src/lib/api/schema.d.ts`; `openapi-fetch` 0.17.0 provides the typed client (`src/lib/api/client.ts`). The generated file is committed; the CI compose job regenerates it and fails on drift.
- `npm run typecheck` is `next typegen && tsc --noEmit`, because `LayoutProps` and route types are generated and `tsc` on a fresh clone otherwise fails. The spec's `npx tsc --noEmit` passes once a build or typegen has run.
- Architecture: import-linter enforces "only orchestration imports langgraph" and "platform does not depend on modules/orchestration/agents". The cross-module `domain`/`adapters` rule cannot be expressed generically in import-linter, so `tests/test_architecture.py` enforces both rules with an AST scan (relative imports resolved) and self-tests the checker against synthetic violations.
- psycopg's async driver cannot run on the Windows Proactor loop. Tests pass a `SelectorEventLoop` factory to the TestClient; `python -m app.main_api` does the same. Containers run uvicorn on Linux unaffected.
- Compose has three services, all under the `local` profile; no `migrate` service yet (deployment topology is Story 1.2). Migrations run with `docker compose --profile local exec api alembic upgrade head`, which CI also does.
- Request middleware sets/echoes `X-Request-ID` and logs one JSON line per request (method, path, status, duration, request_id). uvicorn's access log is disabled and its loggers route through the JSON formatter. Exceptions are logged by type only.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter, edge-case-hunter, verification-gap.

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | VG, BH, ECH | 500 responses lack `X-Request-ID` and `http.request` log | medium | VG reproduced it: `call_next` raises in BaseHTTPMiddleware and ServerErrorMiddleware writes the 500 outside it | patch |
| 2 | VG, BH | JsonFormatter privacy (type-only exceptions) untested | medium | No test touches JsonFormatter; caplog bypasses it, so an AD-20 regression would pass CI | patch |
| 3 | VG, BH | CI web `/healthz` version not asserted | low | `curl -fsS` checks only 2xx; the API step uses `jq -e`; trivial mirror | patch |
| 4 | BH, ECH | Geist sans never applied (`--font-sans` self-reference) | low | `globals.css:10` `--font-sans: var(--font-sans)`; `layout.tsx:6` declares `--font-geist-sans` | patch |
| 5 | BH | OpenAPI 503 declared `application/json`, sent as problem+json | medium | `schema.d.ts` types the 503 under `application/json`; the handler uses `PROBLEM_JSON`; misleads the AD-16 generated client | patch |
| 6 | ECH | Orchestration/agents may import module `domain`/`adapters` unchecked | medium | `find_violations` sets `own_module` only under `app.modules`; spine line 32 binds orchestration and agents to `public.py` | patch |
| 7 | BH, ECH | `env`/`log_level` free strings | low | Direct correction to `Literal` types | patch |
| 8 | BH | `python -m app.main_api` binds 0.0.0.0 | low | Contradicts the README loopback statement; direct correction | patch |
| 9 | BH, ECH | Unescaped credentials in compose DSN | low | Breaks with `@:/#%` in the password; local only; comment in `.env.example` | patch |
| 10 | ECH | `PSA_DATABASE_URL` port independent of `PSA_POSTGRES_PORT` | low | Host-side tools hit the wrong port if only one is changed; comment fix | patch |
| 11 | ECH | CI concurrency cancels earlier main runs | low | Group `ci-refs/heads/main` with `cancel-in-progress: true`; direct correction | patch |
| 12 | BH, ECH | Untrusted `X-Request-ID` echoed without bounds | low | JSON-encoded in logs (no injection); servers cap header size; fix adds a guard | reject |
| 13 | BH, ECH | Browser cannot reach the API (no `NEXT_PUBLIC_`, no CORS) | false | No browser caller exists; the client is only reachable server-side today. The app shell and BFF arrive in Story 1.5 | reject |
| 14 | BH, ECH | Default DB URL silently used outside local | low | No non-local env exists until Story 1.2; fix adds a validator | reject |
| 15 | BH, ECH | Import-time side effects; configure_logging drops caplog handlers | maybe-false | No current test uses caplog together with `create_app`; would be low | reject |
| 16 | BH | Liveness and readiness merged; web blocked when the DB is down | false | The frozen I/O matrix requires the health check to fail when the DB is down and compose to show unhealthy | reject |
| 17 | BH | Healthcheck duplicated in Dockerfile and compose | low | Drift risk only; no behaviour defect | reject |
| 18 | BH | Untested 422 detail and 405 `Allow` passthrough; 422 empty-`loc` text | low | Edge cases unlikely in a scaffold with no request bodies | reject |
| 19 | BH | Web has no unit tests | low | Spec requires lint, typecheck and build only | reject |
| 20 | BH, ECH | Base images and actions use floating tags | low | Stack table pins Python 3.13 and Node 24, which the tags honour; digest deploys are Story 1.2 | reject |
| 21 | BH | problem `type` URI not resolvable | low | Cosmetic until clients exist | reject |
| 22 | BH | Spec Verification still says `npx tsc --noEmit` | low | Fix edits this build's spec | reject |
| 23 | BH | Spec Code Map contains a local Docker path | low | Fix edits this build's spec | reject |
| 24 | BH | Baseline downgrade `DROP EXTENSION`; no migration round trip | low | No vector columns exist yet; round trip verified manually | reject |
| 25 | ECH | Unknown status code crashes the HTTPStatus lookup | false | No code path raises a non-standard status | reject |
| 26 | ECH | Pool exhaustion reported as `db_unavailable` | maybe-false | Would be low; no load path in the scaffold | reject |
| 27 | ECH | `extra` keys can overwrite `ts`/`level`/`event` | low | Fix adds a guard; no caller does it | reject |
| 28 | ECH | `gen-api.mjs` gives an opaque error on a bad path | low | Developer-only; fix adds a branch | reject |
| 29 | ECH | `next/font/google` needs network at build | false | Offline builds aren't required; the build passed in Docker and CI-like runs | reject |
| 30 | ECH | import-linter langgraph contract uses a fixed source list | false | The AST scan in `test_architecture.py` covers all of `app/` and runs in CI pytest | reject |
| 31 | ECH | Cross-module rule not in import-linter alone | false | Enforced by the pytest AST scan in the CI backend job; documented in Implementation Notes | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run pytest` -- expected: all pass (DB-dependent tests use `PSA_DATABASE_URL`)
- `cd backend && uv run lint-imports` -- expected: contracts kept
- `cd web && npm run lint && npx tsc --noEmit && npm run build` -- expected: success
- `docker compose --profile local up --wait -d` then `curl localhost:8000/api/v1/health` and the web `/healthz` -- expected: all healthy, 200 with version
- `PSA_DATABASE_URL=<compose postgres> uv run pytest` -- expected: DB-up health test passes; stopping postgres gives 503 `db_unavailable`
