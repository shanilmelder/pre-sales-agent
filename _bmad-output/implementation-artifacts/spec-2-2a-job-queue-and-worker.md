---
title: 'Story 2.2 (Part A): Postgres job queue and worker'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '5937e3128872dcbaed1fbb61961b5a30b88f8d11'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing can run in the background. Parsing, extraction and every later agent need a job queue, and the `worker` process is still a placeholder that idles (`backend/app/main_worker.py`).

**Approach:** Add the AD-29 job layer in `app/platform/jobs/`: a typed registry, the `platform_jobs` table, enqueueing inside the caller's Unit of Work, `FOR UPDATE SKIP LOCKED` claiming, a lease with heartbeat, reclaiming, retries with backoff, and a `dead` state. Then make the worker claim and run jobs, and add it to compose.

## Boundaries & Constraints

**Always:**
- **Registry:** `platform/jobs/registry.py` maps each job type (`<module>.<verb>`) to:
  - a Pydantic payload model;
  - a priority class (`interactive` > `background`);
  - a timeout;
  - `max_attempts` and a backoff (exponential with a cap);
  - an async handler `(ctx, payload) -> None`.

  Modules register their job types at import, the way the trace catalogue does.
- **Enqueue:** `jobs.enqueue(uow, payload, *, opportunity_id=None, run_after=None)` inserts a row inside the caller's Unit of Work, so a rolled-back command enqueues nothing. Payloads are validated against the registry. An unknown type raises.
- **`platform_jobs` columns:** `id` (UUIDv7), `job_type`, `payload` (jsonb), `priority`, `status`, `attempts`, `run_after`, `lease_owner`, `lease_expires_at`, `last_error`, `opportunity_id` (nullable), `created_at`, `updated_at`.
  - `status` is one of `queued | running | succeeded | failed_retrying | dead`.
  - `last_error` is a short reason only, never customer content.
  - It has a partial index for claiming.
  - `psa_app` gets SELECT, INSERT and UPDATE grants, with no DELETE.
- **Claim:** one short transaction selects the next eligible job, ordered by priority, then `run_after`, then `created_at`, using `FOR UPDATE SKIP LOCKED`. A job is eligible if it is `queued` or `failed_retrying` with `run_after <= now()`, or `running` with an expired lease. The claim sets `running`, the lease owner and the expiry, and increments `attempts`.
- **Lease:** a heartbeat extends the lease while the handler runs, defaulting to a 30 s lease and a 10 s beat.
- **Finishing:**
  - Completion and failure update the row only if the worker still holds the lease, so a reclaimed job's late result is discarded.
  - Running the handler follows AD-25 commit rules: the handler opens its own Units of Work as it needs them, and the queue never holds a transaction open across the handler.
- **Exactly once:** a job killed mid-run is reclaimed after lease expiry. It runs again and completes exactly once (`succeeded` written once). Handlers must be idempotent, which is documented in the registry docstring.
- **Failure:**
  - An exception or timeout records `last_error` (exception class plus a short message) and sets `failed_retrying` with backoff.
  - When attempts are exhausted the job becomes `dead`, logged at ERROR as `jobs.dead` with job id and type. The Story 1.3 alert hooks onto this log later.
- **Worker:**
  - `main_worker.run` loops: claim, run, and when no job is ready, sleep with a short jittered poll (default 1 s, configurable). It honours its stop event and finishes or abandons the current job cleanly.
  - Concurrency is 1 job at a time per worker process, with the setting `PSA_WORKER_CONCURRENCY` reserved for later.
  - The `api` process never imports the claim loop. An import-linter contract or architecture test enforces this.
- **Compose:** a `worker` service from the same backend image (command `python -m app.main_worker`), with the `files` volume, the `psa_app` DB URL and `depends_on` postgres. Documented in `.env.example` and the compose header.
- **Logs:** ids, types, attempts and durations only.
- **Decided (2026-10-04):** Story 2.2 is split. Part A is this job layer, and Part B is the `intake.parse_source` job. Parsing, the extracted-text artifact, and the Parse failed pill with Retry are all in Part B. Idempotency, schedules and the real alert are deferred until after the demo.

**Never:**
- No `platform_idempotency` or `platform_schedules` yet: nothing uses them before Epic 5 and later. They're tracked as `[post-demo]`.
- No real alerting (that's Story 1.3).
- No LISTEN/NOTIFY wakeups. No job UI or admin API. No parsing. That's Part B, the first real job type.
- No Celery, Redis or any second queue technology (AD-7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Enqueue in UoW | Command enqueues, then commits | 1 `queued` row | N/A |
| Rolled back | Command enqueues, then raises | 0 rows | N/A |
| Unknown type | Payload class not registered | Raises; nothing inserted | N/A |
| Priority | One `background` job queued before one `interactive` job | `interactive` is claimed first | N/A |
| Two workers | 2 claimers, 1 eligible job | Exactly one claims it | N/A |
| Not yet | `run_after` in the future | Not claimed | N/A |
| Success | Handler returns | `succeeded`, lease cleared | N/A |
| Retry | Handler raises on attempt 1 of 3 | `failed_retrying`, `run_after` = now + backoff, `last_error` set | N/A |
| Timeout | Handler exceeds its timeout | Cancelled and treated as a failure | Retry or dead |
| Dead | Fails on the final attempt | `dead`, `jobs.dead` logged at ERROR | N/A |
| Killed worker | Lease expires mid-run | Reclaimed, runs again, `succeeded` once. The stale holder's finish is a no-op | N/A |
| Stop | Stop event while idle | Worker exits within one poll interval | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/main_worker.py` -- replace the idle loop with the claim and run loop. Keep `run(stop, ...)` testable and keep the signal handling. Update `tests/test_worker.py`.
- `backend/app/platform/jobs/` (new) -- `registry.py` (job type spec, `register`, lookup), `queue.py` (`enqueue`, `claim`, `heartbeat`, `complete`, `fail` with SQL Core statements), `runner.py` (run one claimed job with the timeout and heartbeat task), and `models.py` (the SQLAlchemy table, following `platform/files.py` and `trace/models.py`).
- `backend/app/platform/uow.py` -- `unit_of_work(engine)` is the edge commit for job steps. Only `uow.py` may call `.commit(` (`tests/test_architecture.py`).
- `backend/app/platform/config.py` -- add `worker_poll_s`, `job_lease_s` and `job_heartbeat_s` with the `PSA_` prefix.
- `backend/migrations/versions/20261004_0005_intake_sources.py` -- the pattern to follow, with its grants. The new revision is `0006_platform_jobs`.
- `backend/pyproject.toml` `[tool.importlinter]` and `tests/test_architecture.py` -- forbid `app.main_api` from importing `app.platform.jobs.runner`.
- `compose.yaml`, `.env.example`, `backend/Dockerfile` -- the image comment already says "`worker` overrides the command".
- `backend/tests/conftest.py` -- `db_url` and `sync_engine` fixtures. Tests run as `psa_app` against Postgres, with a test-only job type registered in the test module.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/jobs/*`, `config.py` -- the registry, queue, runner and settings
- [x] `backend/migrations/versions/20261004_0006_platform_jobs.py` -- the table, indexes and grants
- [x] `backend/app/main_worker.py` -- the claim and run loop
- [x] `backend/tests/test_jobs.py`, `test_worker.py`, `test_architecture.py` -- every matrix row as Postgres integration tests. The killed-worker row uses a short lease and an abandoned claim.
- [x] `compose.yaml`, `.env.example`, `pyproject.toml` (import contract) -- the worker service and its config

**Acceptance Criteria:**
- Given `docker compose --profile local up`, when the stack is healthy, then the `worker` container logs `worker.started` and idles without errors.
- Given CI, when it runs, then `ruff`, `mypy`, `lint-imports`, `alembic check` and `pytest` all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | ECH, BH | A handler that raises `CancelledError` itself is treated as worker shutdown: the job is released with its attempt refunded, the error escapes `run()` (it catches only `Exception`), and the worker exits | medium | `runner.py` except-CancelledError branch re-raises unless the heartbeat cancelled the handler; `_cancelling()` is 0 in this case | patch |
| 2 | BH | On SIGTERM the worker waits for the current job (up to `timeout_s` 300 s), but Docker sends SIGKILL after 10 s. The job is killed with its attempt counted and waits for lease expiry | medium | `run()` checks `stop` only between jobs; the release path exists but is only reached on task cancel | patch |
| 3 | ECH, BH | The heartbeat may be just below the lease (29/30), so one slow round trip loses the lease | low | `_heartbeat_inside_lease` only checks `<`; direct tightening to ≤ lease/2 | patch |
| 4 | BH | Blocking or CPU-bound handlers starve the loop, breaking the timeout and the heartbeat | low | The registry docstring doesn't forbid it; Story 2.2 Part B parsing must run in a subprocess. Direct docstring line | patch |
| 5 | VG | The heartbeat lease-lost branch (handler cancelled, `"lease_lost"`) is never exercised | medium | The only lease test uses `heartbeat_s=60`, so its lease_lost comes from `complete()` | patch (test) |
| 6 | VG | A failing heartbeat that should keep the job alive is untested | low | No test makes `q.heartbeat` raise | patch (test) |
| 7 | VG | `run_job` with an invalid stored payload or an unregistered type is untested | low | Only `enqueue` paths are tested | patch (test) |
| 8 | VG | The worker loop's `worker.job_error` survival path is untested | low | No test makes `run_job` raise inside `run()` | patch (test) |
| 9 | VG | Claim order within one priority (`run_after`, `created_at`) is untested | low | Only the priority key is tested; a cheap test | patch (test) |
| 10 | BH | Lease tests use sub-second sleeps and may flake on CI or Windows | low | `lease_s=0.1–0.3` with fixed sleeps; expiring the lease with an UPDATE is a direct change | patch (test) |
| 11 | BH | No README section on running the worker | low | `compose.yaml` refers to README for migrations; direct doc | patch |
| 12 | BH | `last_error` stores the first line of any exception message, and some (driver, HTTP, `KeyError`) can echo data | medium | The spec asks for "class plus a short message", which conflicts with "never customer content". Fixing it needs a new safe-message error type (public surface) | defer |
| 13 | ECH | A heartbeat failing for longer than the lease can let a rival reclaim the job, so two runs overlap | low | Needs the DB to be down for this worker only; handlers are idempotent | reject |
| 14 | ECH | The final attempt succeeds but `complete()` raises, so the reclaim marks it dead | low | Needs a DB failure at that exact moment | reject |
| 15 | ECH | `run_job` raising after the handler leaves the job running until the lease expires, then it re-runs | false | At-least-once delivery by design; handlers are documented idempotent | reject |
| 16 | ECH | A naive `run_after` datetime is misread | low | No caller passes one | reject |
| 17 | BH | Handlers can't mark a failure permanent | low | Story 2.2 Part B records permanent parse failures on its own row and returns normally | reject |
| 18 | BH | No CHECK ties `running` to the lease columns | low | Only `claim` sets `running`, always with both | reject |
| 19 | BH | With no job types the worker idles silently | low | Story 2.2 Part B registers the first type | reject |
| 20 | BH | The worker has no liveness healthcheck | low | Restart policy covers crashes; liveness is ops work for Story 1.3 | reject |
| 21 | BH | `worker_concurrency` is never read | false | The spec reserves the setting explicitly | reject |
| 22 | BH | No retention or requeue for finished and dead jobs | low | Growth is small in R1; ops tooling later | reject |
| 23 | BH | The test fixture leaves `dead` test rows in the local DB | low | Dev and test DB only | reject |
| 24 | BH | Retry backoff has no jitter | low | One worker in R1 | reject |
| 25 | BH | Test job types stay in the global registry for the whole session | low | Every test passes `job_types` explicitly | reject |
| 26 | VG | The compose CI job doesn't check the worker container | low | Manual compose check is in the spec's Acceptance | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run alembic upgrade head && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
