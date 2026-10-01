---
title: 'Story 1.1: Project scaffold and local stack'
type: 'feature'
created: '2026-10-01'
status: 'draft'
route: 'dispatch'
review_loop_iteration: 0
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

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Health OK | `GET /api/v1/health`, DB reachable | 200 `{status:"ok", version, db:"ok"}` | N/A |
| DB down | Postgres stopped | 503 problem+json `code: db_unavailable` | Health check fails; compose shows unhealthy |
| Unknown route | `GET /api/v1/nope` | 404 problem+json `code: not_found` | N/A |
| Boundary violation | A module imports `langgraph`, or another module's `domain`/`adapters` | Architecture test fails in CI | Merge blocked |

</frozen-after-approval>

## Open Questions

1. **Local Docker.** Docker isn't installed on this machine, so the "`docker compose up` passes healthchecks" criterion can't be run here.
   - **(a) Install Docker Desktop now.** Full local verification.
   - **(b) Verify natively here.** Run the API with `uv` against a disposable Postgres and the web app with `npm`, and validate `docker compose config` in CI only. The compose stack is first exercised in CI and on the VPS (Story 1.2).
   - **(c) Validate compose in CI.** Add a CI job that runs `docker compose up --wait` against the health endpoints. Combine with (b).
2. **Git and GitHub.** The folder isn't a git repository, and CI needs GitHub.
   - **(a) Run `git init` now, on `main`.** You add the GitHub remote. Planning artifacts and `_bmad/` are committed as the first commit.
   - **(b) Same as (a), but `_bmad*` and `.claude/` are gitignored.**
   - **(c) Use an existing GitHub repo.** Give its URL.

## Code Map

- Greenfield: no application code exists. The existing `_bmad/`, `_bmad-output/`, `.claude/`, `.agents/`, `.github/agents/`, `docs/` and `graft/` folders are tooling and planning; leave them unchanged.
- `.github/` -- holds agent files only; CI is added at `.github/workflows/ci.yml`.
- Layout source of truth: spine "Structural Seed" and "Design Paradigm" (layers `api/ application/ domain/ adapters/` per module).

## Tasks & Acceptance

**Execution:**
- [ ] `backend/pyproject.toml`, `backend/uv.lock` -- create a uv project with pinned deps plus dev tools (pytest, ruff, mypy, httpx, import-linter) -- reproducible builds
- [ ] `backend/app/{modules,orchestration,agents,platform}/`, `backend/app/main_api.py`, `backend/app/main_worker.py` -- skeleton packages. `main_worker.py` is a no-op loop placeholder that logs a start event -- spine layout (AD-1, AD-2)
- [ ] `backend/app/platform/config.py`, `platform/errors.py`, `platform/logging.py`, `platform/db.py` -- settings, problem+json handlers (404/500/503), JSON logger, async engine with a ping -- needed by health
- [ ] `backend/app/main_api.py` -- FastAPI app with `/api/v1/health` (version from env/build arg), OpenAPI served at `/api/v1/openapi.json` -- I/O matrix
- [ ] `backend/migrations/` -- Alembic init with an empty baseline revision that enables the `vector` extension -- later stories add tables
- [ ] `backend/tests/test_health.py`, `backend/tests/test_architecture.py` -- health matrix tests; import-linter contracts (only `orchestration` may import `langgraph`; no cross-module `domain`/`adapters` imports) -- AD-2, AD-5
- [ ] `backend/Dockerfile` -- slim Python 3.13 image running uvicorn, healthcheck -- compose
- [ ] `web/` -- create-next-app 16 (TS, Tailwind 4, App Router, ESLint), shadcn init, placeholder home page, `Dockerfile`, a `/healthz` route -- web skeleton
- [ ] `web/package.json` script `gen:api` -- openapi-typescript (or @hey-api/openapi-ts) generating into `web/src/lib/api` from the backend spec -- AD-16
- [ ] `compose.yaml`, `.env.example` -- `postgres` (pgvector image, volume, healthcheck), `api`, `web` with healthchecks and `restart: unless-stopped`; local profile -- local stack
- [ ] `evals/README.md`, `ops/README.md`, root `README.md`, `.gitignore`, `.editorconfig` -- purpose stubs and how to run -- structure
- [ ] `.github/workflows/ci.yml` -- jobs: backend (ruff, mypy, pytest with a Postgres service), web (lint, typecheck, build), compose config validate -- merge gate

**Acceptance Criteria:**
- Given a fresh clone, when the documented setup runs, then `postgres`, `api` and `web` start and pass healthchecks, and `GET /api/v1/health` returns 200 with the build version.
- Given the source tree, when inspected, then it matches the spine's Structural Seed and every dependency is pinned to the Stack table.
- Given the web app, when `npm run gen:api` runs against a running API, then a typed client appears in `web/src/lib/api` and the web build passes.
- Given a PR, when CI runs, then backend lint, typecheck and tests, web lint, typecheck and build, and the architecture contracts all run, and any failure fails the workflow.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run pytest` -- expected: all pass (DB-dependent tests use `PSA_DATABASE_URL`)
- `cd backend && uv run lint-imports` -- expected: contracts kept
- `cd web && npm run lint && npx tsc --noEmit && npm run build` -- expected: success
- `docker compose config` -- expected: valid (where Docker is available)
