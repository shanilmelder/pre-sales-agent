---
title: 'Story 1.4 (Part A): Platform core primitives'
type: 'feature'
created: '2026-10-01'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'b6beaf3ac39f5d3dd2ac554742b70be4dd4e1188'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every later story mutates state, but nothing yet provides the one mutation path (AD-3): a request-scoped Unit of Work, the append-only trace, central authorization, optimistic concurrency and typed problem+json errors.

**Approach:** Add `platform.uow`, `platform.trace` (table, catalogue, `append`), `platform.concurrency` (`row_version`, `If-Match`, 412), and the `identity` module's action catalogue and `authorize`. Map every new error to problem+json, and unit-test and integration-test each piece. Auth0 sign-in is Part B (deferred-work.md).

## Boundaries & Constraints

**Always:** Commands take the UoW as their first argument and never commit, and only the edge commits. Trace rows are written only by `platform.trace.append`. Event names follow `<module>.<entity>.<past_tense_verb>` and action names follow `<module>.<entity>.<verb>`, both regex-checked. IDs are UUIDv7. Times are `timestamptz` UTC. `platform` imports nothing from `modules`. Other modules reach identity only through `identity/application/public.py`.

**Never:** No Auth0, JWT, users table, roles table, HTTP endpoints for business features, or web changes. No new runtime dependencies. No UPDATE or DELETE grant on `platform_trace_events` for the application role.

**Decisions:** Separate DB roles. Migrations run as the owner role (`POSTGRES_USER`) via a new `PSA_MIGRATIONS_DATABASE_URL`. A login role `psa_app` (password `PSA_APP_DB_PASSWORD`) is created by a Postgres init script and used by `api` through `PSA_DATABASE_URL`. Migrations grant it SELECT, INSERT on `platform_trace_events`, and default privileges give it SELECT, INSERT, UPDATE, DELETE on later tables. The spec keeps its full scope (about 1,700 tokens) because the user accepted that.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Request succeeds | Handler writes via UoW | Committed once after the handler returns, before the response | N/A |
| Handler raises | Any exception inside the UoW | Rolled back; nothing persisted, including trace rows | Mapped problem+json |
| Unknown event payload | Payload class not in catalogue | `append` raises before any write | Programming error (500) |
| Authorized | Actor role grants action | `authorize` returns None | N/A |
| Denied | No granting role, or agent/system actor with no grant | Raises `ForbiddenError` | 403 `forbidden` |
| If-Match missing | Write without header | Rejected | 428 `if_match_required` |
| Version mismatch | `If-Match: "3"`, row at 4, or a concurrent update (`StaleDataError`) | Rejected, nothing written | 412 `row_version_mismatch` |
| Trace tamper | App role runs UPDATE/DELETE on `platform_trace_events` | Postgres refuses | `InsufficientPrivilege` |

</frozen-after-approval>

## Code Map

- `backend/app/platform/errors.py` -- `ProblemError` subclasses map automatically; add `ForbiddenError`, `IfMatchRequiredError` (428), `RowVersionMismatchError` (412), and a `StaleDataError` → 412 handler in `install_error_handlers`. Add 428 to `_HTTP_CODES`.
- `backend/app/platform/db.py` -- `create_engine`, `ping`; add `Base` (DeclarativeBase with a naming convention).
- `backend/app/main_api.py` -- `create_app` keeps `app.state.engine`; no routes added.
- `backend/migrations/env.py` -- `target_metadata = None`; set it to `Base.metadata` and import the trace models.
- `backend/migrations/versions/20261001_0001_baseline.py` -- the new revision `0002` revises it.
- `compose.yaml` (postgres env/volume, api `PSA_DATABASE_URL` at line 40), `.env.example`, `.github/workflows/ci.yml` (backend job: Postgres service, `PSA_DATABASE_URL` at line 35, `alembic upgrade head` step; compose job runs `exec api alembic upgrade head`), `README.md` -- all assume one role today.
- `backend/tests/conftest.py` -- `make_client`, `BACKEND_OPTIONS` (Windows selector loop), `PSA_DATABASE_URL` skip pattern; reuse these for DB tests.
- `backend/tests/test_architecture.py` -- AST `find_violations`; extend it with a "no `.commit(` outside `platform/uow.py`" rule.
- `backend/pyproject.toml` -- import-linter: platform must not import modules (already enforced).
- FastAPI 0.142 supports `Depends(..., scope="function")`, so the code after `yield` runs before the response is sent. Use it so commit failures become problem+json errors.
- Python 3.13 has no `uuid.uuid7`; implement it (RFC 9562) in `platform/ids.py`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/ids.py` -- `new_id() -> UUID` (UUIDv7) -- AD conventions
- [x] `backend/app/platform/actor.py` -- frozen `Actor(type: Literal["user","agent","system"], id: str)` -- shared by trace and identity without breaking the platform → modules ban
- [x] `backend/app/platform/uow.py` -- `UnitOfWork` (wraps `AsyncSession`; no public commit), `unit_of_work(engine)` async context manager (commit on success, rollback on error), FastAPI dependency `get_uow` with `scope="function"` -- AD-25
- [x] `backend/app/platform/trace/{__init__,catalogue,models,writer}.py` -- table model; `TracePayload` base with `event_type: ClassVar[str]`; `CATALOGUE` registry seeded with `IdentityUserProvisioned` (no fields; Part B may extend it); `append(uow, *, actor, payload, subject_type, subject_id, opportunity_id=None, workflow_run_id=None, subject_version=None) -> UUID` -- AD-12
- [x] `backend/app/platform/concurrency.py` -- `RowVersioned` mixin (`row_version`, `version_id_col`), `etag(v)`, `parse_if_match(header) -> int`, `check_row_version(expected, row)` -- AD-11
- [x] `backend/app/platform/errors.py` -- new error types and handlers (see Code Map)
- [x] `backend/app/modules/identity/{__init__.py,actions.py,domain/roles.py,domain/policy.py,application/authorize.py,application/public.py}` -- `Action` StrEnum (`identity.user.assign_role`, `identity.user.remove_role`); `Role` StrEnum (the nine roles); `POLICY: Mapping[Action, frozenset[Role]]` (both actions → platform administrator); `Principal(actor, roles)`; `authorize(actor: Principal, action, resource: Resource | None = None)`; `public.py` re-exports them -- AD-15
- [x] `backend/migrations/versions/20261001_0002_platform_trace.py`, `backend/migrations/env.py` -- trace table, indexes `(opportunity_id, occurred_at)` and `(subject_type, subject_id)`, grants and default privileges for `psa_app` (see Decisions); env.py uses `migrations_database_url` when set
- [x] `backend/app/platform/config.py`, `ops/postgres/init/10-app-role.sh`, `compose.yaml`, `.env.example`, `.github/workflows/ci.yml`, `README.md` -- `migrations_database_url: str | None` setting; init script creates `psa_app` from `PSA_APP_DB_PASSWORD`; compose mounts it into `/docker-entrypoint-initdb.d` and points api at `psa_app` and Alembic at the owner; CI creates the role in the backend job before migrating and tests as `psa_app`; README notes `docker compose down -v` for existing volumes
- [x] `backend/tests/test_uow.py`, `test_trace.py`, `test_concurrency.py`, `test_authorize.py`, `test_errors.py`, `test_ids.py`, `test_architecture.py` -- every I/O matrix row; DB tests skip without `PSA_DATABASE_URL`, and use a temporary versioned table for the 412 race

**Acceptance Criteria:**
- Given the catalogues, when tests run, then every event type and action name matches its naming regex and every payload model rejects extra fields.
- Given a test route that uses `get_uow` and appends a trace event, when it returns 200, then exactly one trace row exists with UUIDv7 `id`, `opportunity_id = null` and a UTC `occurred_at`.
- Given CI, when it runs, then ruff, mypy strict, lint-imports, `alembic upgrade head` and pytest pass, including the DB-backed tests.

## Implementation Notes

- Past-tense check: the verb's last word must end in `ed` or appear in a small irregular list (`built, done, lost, made, run, sent, won`). `subject_id` is a UUID column. `occurred_at` is set in Python (UTC), and the engine sets the session `timezone=UTC`.
- `parse_if_match`: a missing or blank header gives 428. `*`, lists, weak tags and junk give 412 (a failed `If-Match` per RFC 9110). `StaleDataError` maps to 412 without leaking SQL.
- Migration 0002 fails with a clear message if `psa_app` does not exist. Its grants: SELECT and INSERT on the trace table, then default privileges (SELECT, INSERT, UPDATE, DELETE on tables; USAGE, SELECT on sequences).
- Until Story 1.2's `migrate` service, the compose `api` container also carries `PSA_MIGRATIONS_DATABASE_URL` (the owner), so `exec api alembic upgrade head` keeps working.
- `.gitattributes` keeps `*.sh` as LF, because `core.autocrlf=true` would otherwise break the init script in Linux containers.
- Not verified locally: the init script ran only through a syntax check, because there was no psql or Docker in the implementing session, and the CI role step assumes the runner has `psql`. The local verification role was created with equivalent SQL.
- Trace rows that tests commit persist, because the app role cannot delete them. Tests filter by a unique `subject_id`.
- Verified: ruff, ruff format, mypy strict, lint-imports, an Alembic downgrade/upgrade round trip as the owner, and pytest as `psa_app` (94 passed, 0 skipped).

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | ECH | Race test never hits commit-time `StaleDataError` | medium | `trace.append` runs an ORM-enabled `insert(TraceEvent)` through `session.execute`, which autoflushes the dirty `item` inside the handler. The `scope="function"` commit path is therefore untested | patch |
| 2 | VG, BH | Default privileges on later tables and sequences unverified; no test that psa_app cannot CREATE | medium | Only trace-table privileges are tested. Removing the `ALTER DEFAULT PRIVILEGES` lines leaves the suite green | patch |
| 3 | BH | api container holds the owner DB credentials | medium | `compose.yaml` api env carries `PSA_MIGRATIONS_DATABASE_URL` with `POSTGRES_PASSWORD`, which undoes the least-privilege role decision for the running app | patch |
| 4 | BH, ECH | Migrations silently fall back to psa_app's URL | low | `_url()` falls back to `database_url` (psa_app). On PG18 psa_app has no CREATE, so the upgrade fails with an unclear privilege error. A `current_user` guard is direct | patch |
| 5 | VG | UTC session setting of the app engine unobserved | low | The test reads through `sync_engine`, which sets UTC itself. Removing it from `create_engine` stays green | patch |
| 6 | BH | `If-Match: *` docstring cites RFC 9110 wrongly | low | RFC 9110 §13.1.1 says `*` matches any current representation. Rejecting it is a deliberate choice; the RFC claim is false | patch |
| 7 | ECH | Leading-zero ETags (`"03"`) accepted | low | `_ETAG_RE` `\d{1,18}`; direct regex correction | patch |
| 8 | BH, ECH | Returned (not raised) error responses still commit | low | `unit_of_work` commits on any normal return. Not reachable today (all errors are raised `ProblemError`); documenting "raise, never return" is direct | patch |
| 9 | BH | No `alembic check` in CI | low | Model and migration are synchronised by hand; a one-line CI step catches drift | patch |
| 10 | BH | Unused `ACTOR_TYPES` constant | low | `trace/models.py` defines it, and nothing reads it; delete | patch |
| 11 | BH, ECH | Past-tense check is a heuristic (`need`, `seed` pass) | low | The `endswith("ed")` rule is real; stating it as a heuristic in the docstring is direct; a stricter rule adds complexity | patch |
| 12 | BH | `register` extra-fields branch untested | low | No test registers a non-forbid payload; trivial test | patch |
| 13 | VG | Migration comment names the wrong ordering | low | Default privileges apply to objects created later, so the relevant order is after `create_table` | patch |
| 14 | ECH | `ALTER DEFAULT PRIVILEGES` lacks `FOR ROLE` | low | Applies to `current_user`, which is always the owner by design (and #4 enforces it). Unlikely; reject | reject |
| 15 | BH | psa_app granted TEMPORARY in prod | false | PostgreSQL grants TEMPORARY to PUBLIC on every database by default; the grant adds nothing | reject |
| 16 | BH | Commit guard misses `session.begin()`/`getattr` | low | `begin()` raises once the session has autobegun; deliberate evasion is unlikely; fix adds rules | reject |
| 17 | BH | `occurred_at` has two sources; index has no tiebreaker | low | Same host for api and DB; UUIDv7 `id` already orders ties; no named harm | reject |
| 18 | BH, ECH | `RowVersioned` `__mapper_args__` can be overridden | low | No subclass exists; fix adds a guard | reject |
| 19 | BH | ETag not exposed via CORS | false | No browser caller or GET resource exists; web uses a server-side client (BFF in Story 1.5) | reject |
| 20 | ECH | Multiple separate `If-Match` headers | low | Clients send one; fix adds a branch | reject |
| 21 | ECH | UUIDv7 not monotonic within one millisecond | low | RFC 9562 allows it; ordering uses `occurred_at`/ms; fix adds state | reject |
| 22 | ECH | Rollback failure masks the original error | low | Python chains the original as `__context__`; a dropped connection is a 500 either way | reject |
| 23 | ECH | Invalid `Actor.type` gives an opaque 500 | false | Type is a `Literal` checked by mypy strict; a loud failure on an unreachable programming error is correct | reject |
| 24 | BH | `database_url` default is owner-style; bare-number ETag accepted; `_SEGMENT` duplicated | low | Local default only; harmless leniency; `platform` cannot import `identity` | reject |

## Design Notes

`Principal` is identity's actor: a platform `Actor` plus roles loaded at the edge. Because roles are loaded at the edge, role changes take effect on the user's next request. `authorize` is pure. Resource-scoped rules (owner, collaborators) arrive with Story 1.7 and go in `policy.py`.

```python
async def assign_role(uow: UnitOfWork, actor: Principal, ...) -> None:
    authorize(actor, Action.USER_ASSIGN_ROLE)
    ...                                  # rules, row_version, write
    await trace.append(uow, actor=actor.actor, payload=RoleAssigned(...), ...)
```

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports` -- expected: clean
- `docker compose --profile local up --wait -d postgres` then `cd backend && uv run alembic upgrade head && uv run alembic downgrade 0001_baseline && uv run alembic upgrade head` -- expected: round trip succeeds
- `cd backend && PSA_DATABASE_URL=<app-role url> uv run pytest` -- expected: all pass, none skipped
