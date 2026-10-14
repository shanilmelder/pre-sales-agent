---
title: 'Story 5.2 (demo slice): workflows module, durable LangGraph execution and live run progress'
type: 'feature'
created: '2026-10-14'
status: 'done'
baseline_commit: 'a43a63cd21f2793c27ac041ea47f4e6c4847c599'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-1-auto-assessment-run.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Today `assessments` owns the specialist runs and tasks, and one job runs the agents with `asyncio.gather`. Nothing is checkpointed, and the web only learns about progress by polling. The architecture (AD-5, AD-6, AD-24, AD-30) gives runs to a `workflows` module, executes them as LangGraph graphs in the worker with a Postgres checkpointer, and streams progress to the browser.

**Approach:** Create `app/modules/workflows`, which owns runs, tasks, the start, retry and cancel commands, and progress. Move the existing run and task tables and code into it. Build a LangGraph graph per run in `app/orchestration/`: one node per task, parallel unless linked by `requires`, checkpointed with `thread_id = run_id`. Every node re-reads truth from `workflows`. Nodes write `workflows_progress` rows, and the API streams them per Opportunity over SSE. The Assessments tab updates live from that stream.

## Boundaries & Constraints

**Always:**
- **Decided (ownership):** `workflows` owns runs and tasks. Its commands are the only writers of run and task status. The tables are renamed in place (`assessments_runs` → `workflows_runs`, `assessments_tasks` → `workflows_tasks`), keeping ids and history. `assessments_assessments.run_id` becomes a plain UUID (no cross-module FK, like `estimates.source_run_id`). `assessments` keeps Assessments, Findings and `accept_assessment`. Other modules use `workflows` only through `application/public.py`, enforced by a new import-linter contract.
- **Decided (live progress):** included in 5.2.
- **Kept as-is:** the API paths and response shapes (`GET …/assessments`, `POST …/assessment-runs`, retry, cancel) are now served by `workflows` routes or composed from its public API. So are the status vocabulary (run `queued, running, succeeded, partially_failed, failed, cancelled`; task `queued, running, succeeded, failed, skipped`), the trace event names, the Story 5.1 automatic run, cancel, retry, the evals harness and the Estimate/Conflicts hand-offs.
- **Plan:** each task gets `requires uuid[]` (default empty) and each run gets `plan_version` (1). The graph is built from them. Today's three specialist tasks have no `requires`, so they run concurrently.
- **Process split:** only the worker builds and runs graphs. The api never imports `app.orchestration` or `langgraph`. The job handler reaches the graph runner through a hook the worker installs.
- **Checkpointer:** `AsyncPostgresSaver` on its own `AsyncConnectionPool`, with `autocommit=True`, `row_factory=dict_row`, `search_path=orchestration_checkpoints` and `LANGGRAPH_STRICT_MSGPACK=true`. Checkpoint state holds only IDs, counters and budgets.
- **Node:** re-read the task and run, and skip the node if the task is no longer pending or the run is cancelled. Then mark it running (a `workflows` command), load inputs via queries, and call `Agent.run` outside any Unit of Work. Submit via `assessments.accept_assessment`, then mark the task done (a `workflows` command). A test-only fixture agent and acceptor prove this wrapper.
- **Progress:** in the same Unit of Work as each task start, task end and run end, insert a `workflows_progress` row (non-audit: ids, `event_type`, `summary` with no customer text) and `NOTIFY` `{event_id, opportunity_id, source}`. A `platform_schedules` entry runs a daily job that deletes rows older than 30 days.
- **SSE:** `GET /api/v1/opportunities/{id}/events`, readable by Opportunity members. Frames follow AD-30 (`id`, `event`, `data{event_type, subject_type, subject_id, subject_version, occurred_at, summary}`) with `Last-Event-ID` replay and a keep-alive comment. The browser connects to a same-origin Next route handler that adds the bearer token and passes the stream through, following the `estimate-export` precedent. The Assessments tab refreshes on events and falls back to the existing polling when the stream fails.
- **Privacy:** logs, checkpoints, progress rows and frames contain IDs and typed codes only.

**Never:** No `platform_idempotency` table or node idempotency keys; conditional status transitions and LangGraph's pending writes give exactly-once results. No OpenTelemetry, `PSA_MAX_ACTIVE_RUNS` or queue position. No `interrupt()`, `waiting_for_human` or `timed_out`. No full versioned-plan editing or `start_run(run_type, trigger_ref, idempotency_key)`. No streaming of trace events (that is the Story 5.7 activity rail). No status renames. Red Team, Estimate draft and Gap detection are not moved.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | Queued run, 3 tasks | Three overlapping agent windows; 3 Assessments; run `succeeded`; checkpoint for `thread_id=run_id`; progress rows started ×3, ended ×3, run ended | N/A |
| Requires | Fixture: B requires A | B starts only after A `succeeded` | A fails → B never runs; run finishes per existing rules |
| Crash mid-run | One node done, worker killed, lease expires | Reclaimed job resumes the thread; done node not re-run; no duplicate Assessment rows | N/A |
| Accepted, not checkpointed | Task `succeeded` in DB, checkpoint lacks it | Node re-reads and skips | N/A |
| Job retry | Node raised on a non-final attempt | Only the failed node re-runs | Final attempt marks it `failed`, as today |
| Manual Retry | Finished run; Retry one task | Fresh invocation on the same thread runs only that task | N/A |
| Cancel | Cancel mid-run | In-flight agents cancelled; no node starts after | N/A |
| Migration | Existing runs, tasks and Assessments | Same ids readable through the unchanged API | Downgrade restores the old tables |
| Stream | Member opens Assessments tab during a run | Frames arrive as tasks start and end; tab updates without polling | Non-member 403/404 as other routes; dropped stream → polling |
| Replay | Reconnect with `Last-Event-ID` | Missed rows replayed in order, no duplicates | Unknown id → stream from now |
| Prune | Progress row aged 31 days | Deleted by the scheduled job | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/` -- source of the move. `domain/assessments.py:42-61,95` (statuses, `run_status`); `adapters/models.py:205-255` and `adapters/assessment_repository.py` (`lock_runs` :126, `run_in_progress` :220, `stale_runs` :259, `set_run_status` :272, `update_tasks` :323); `application/assessment.py` (`stale_after` :166, `queue_run` :174, `enqueue_run` :237, `requeue_task` :255, `cancel` :293, `fail_stale` :336, `finish_run` :357, `accept_assessment` :539 (stays), `_start` :795, `_task` :862, `_watch_cancel` :942, `_run` :956, job :1014); `application/assessments.py:263/283/326` (`start_run`, `retry_task`, `cancel_run`); `api/routes.py:93-159`. `finish_run` calls `estimates.build_from_assessments` (:329, :398) and `conflicts.detect_for_run` (:482); keep those hand-offs.
- Callers to repoint to `workflows.public`: gaps `application/detection.py:309-311` (`enqueue_run`), `estimates/application/estimates.py:239-249` (`run_in_progress`, `run_number`), `evals/harness.py:87,98,379-382` (job type, raw SQL table name), agents' `run_id` input (`agents/specialist/agent.py:59,131`).
- Trace: `platform/trace/catalogue.py:432-498` (names unchanged).
- Jobs: `platform/jobs/registry.py` (enqueue by payload class), `queue.py:70-90` (claim, lease reclaim), `main_worker.py:40,150-165` (job modules, poll loop: add the due-schedule enqueue here; open and close the checkpointer pool; install the graph runner). There is no scheduler today.
- `backend/app/orchestration/__init__.py` -- empty. New graph builder, node wrapper, checkpointer factory and runner (resume with `None` input when the thread has pending `next`; otherwise start fresh on the same thread).
- `backend/pyproject.toml` -- deps `langgraph==1.2.15`, `langgraph-checkpoint-postgres==3.1.3`, `psycopg-pool`. Langgraph contract :65-70; add a `workflows` public-API contract and add `workflows` to the other modules' contracts.
- Migrations (latest `0027_registry_eval_results`; CI downgrades to `0001_baseline`): `psa_app` cannot create schemas (`ops/postgres/init/10-app-role.sh`), so the owner creates schema `orchestration_checkpoints` and grants `psa_app` USAGE and CREATE. The worker's `saver.setup()` creates the library tables. Also renames, `requires`/`plan_version`, `workflows_progress`, `platform_schedules` with grants, and the CHECK and constraint renames.
- Auth: `identity/application/provisioning.py:135` (`CurrentPrincipal`); membership checks as in the assessments routes.
- Web: `web/src/lib/api/server.ts` (server-only bearer client); `web/src/app/api/opportunities/[id]/estimate-export/route.ts` (stream pass-through precedent); `web/src/proxy.ts` (check the matcher does not buffer the stream); `web/src/components/opportunities/specialist-assessments.tsx:640-762` (polling to replace); regenerate `web/src/lib/api/schema.d.ts` against a fresh backend.
- Tests: `tests/test_assessments_specialists.py` (`AgentGateway` :99 records windows; run, cancel and retry :1067-1294, auto-run :1346); `tests/test_intake_extraction.py` (`drain` :242, `_hidden_jobs` :139); `tests/test_architecture.py`; `tests/test_db_roles.py`; `web/src/components/opportunities/specialist-assessments.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `uv.lock` -- deps and import contracts
- [x] `backend/migrations/versions/20261014_0028_workflows.py` -- renames, plan columns, progress, schedules, checkpoint schema; clean downgrade
- [x] `backend/app/modules/workflows/{domain,adapters,application,api}/` -- moved run/task code, `public.py`, progress writer, prune job, SSE route
- [x] `backend/app/modules/assessments/**` -- keep Assessments and `accept_assessment`; drop the moved code; compose the view via `workflows.public`
- [x] `backend/app/modules/{gaps,estimates}/**`, `backend/app/evals/harness.py` -- repoint callers
- [x] `backend/app/platform/schedules/` + `backend/app/main_worker.py` -- due-schedule enqueue, checkpointer pool, runner install
- [x] `backend/app/orchestration/{graph,checkpointer,runner}.py` -- builder, node wrapper, resume-or-start
- [x] `backend/tests/test_orchestration.py`, `test_workflows_*.py` -- matrix rows: checkpoint holds IDs only, `requires`, crash/resume via kill and reclaim, SSE frames and replay, prune, migration round-trip
- [x] existing backend tests -- move or repoint without weakening
- [x] `web/src/app/api/opportunities/[id]/events/route.ts`, `specialist-assessments.tsx` (+ tests) -- stream proxy; live updates with polling fallback

**Acceptance Criteria:**
- Given the worker and the demo Opportunity, when Gaps are detected, then the automatic run finishes with three Assessments, the Assessments tab shows each task start and end live without a page refresh, and `orchestration_checkpoints` holds the run's checkpoints.
- Given CI, when it runs, then ruff, mypy, lint-imports, `alembic check` and up/down/up, pytest, and the web lint, typecheck, test and build all pass with no live model.

## Implementation Notes

- **Module split.** `workflows` owns runs/tasks (`domain/runs.py` statuses, `run_status`, `readiness`), `application/runs.py` (queue, enqueue, requeue, cancel, `fail_stale`, `finish_run` + Estimate/Conflict hand-offs, the `workflows.execute` job and the graph-runner hook), `tasks.py` (node commands `begin_task`, `lock_running_task`, `complete_task`, `fail_task`, `skip_blocked_task`), `progress.py` (rows + NOTIFY, prune job), `events.py` (SSE), `assessment_runs.py` (API commands + `GET …/assessments` composed with `assessments.agent_assessments`). All five routes live in `workflows/api/routes.py` with unchanged paths, operation ids and schemas (the regenerated `schema.d.ts` diff is additive only). `assessments` keeps Assessments, `load_inputs`, `accept_assessment` (now takes `opportunity_id`, `config_version_id`, never writes task status) and `current_sizings`/`current_assessment_snapshots`; it imports nothing from `workflows`.
- **Job type** renamed `assessments.run_assessment` → `workflows.execute` (migration renames queued rows; downgrade reverts). The system actor of automatic runs is now `workflows.execute`. Enum class names (`AssessmentRunStatus`, `AssessmentTaskStatus`, `TaskSkipReason`) kept for the API schema.
- **Graph.** `orchestration/graph.py`: one node per task; START→task when it requires none, a waiting edge from all its required tasks otherwise. A node never raises (LangGraph cancels siblings on a raise): it reports the error to the runner; on the final attempt it marks the task `failed`, else the task stays `running` and the handler raises so the job retries. After the graph returns, the handler re-reads task truth (unfinished tasks → retry, or fail-open on the final attempt). A task whose required task ended without succeeding is `skipped` (no `skip_reason`). Checkpoint state: `run_id` + `finished` task ids.
- **Runner.** `LangGraphRunner` resumes with `None` when `aget_state().next` is non-empty, else invokes fresh on the same thread, `durability="sync"`; `saver.setup()` runs lazily on first use so a worker starts while the DB is down. The worker opens one pool (`open_runner`) only when it claims `workflows.execute`; tests install a per-call pool (conftest autouse fixture).
- **Schedules.** `platform_schedules` + `platform/schedules/due.py`; the worker enqueues due schedules (of the job types it claims) about once a minute. Seeded: `workflows.prune_progress`, daily, 30-day retention.
- **Progress events:** `workflows.run.queued` (added so an automatic run appears live), `workflows.task.started`, `workflows.task.ended`, `workflows.run.ended`; summaries are `<agent_id> <status>` / `run <status>`.
- **Web.** `src/lib/opportunity-events.ts` (`useOpportunityEvents`, EventSource on the same-origin route; reconnects with `Last-Event-ID`); the section re-reads on each event and on (re)connect, and polls every 2 s only while the stream is not connected.
- **Step-3 audit:** added `test_a_manual_retry_runs_only_the_requeued_task_on_the_same_thread` (the Manual Retry matrix row had only indirect coverage).
- **Migration detail:** the 0017/0018 check constraints carry a doubled prefix (`ck_assessments_runs_ck_assessments_runs_status`); 0028 renames them to `ck_workflows_*` and back on downgrade.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-14; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | Stall notice never shows while the stream is connected; a lost run pulses forever (blind, edge, VG other) | medium | `specialist-assessments.tsx:758` returns on `live` before the `REVIEW_POLL_LIMIT_MS` check; a lost run sends no event | patch |
| 2 | Concurrent event-triggered re-reads: an older response can overwrite a newer view (blind, edge) | medium | Each event calls `reload.current()`; only `mutation` guards, and it changes only on local actions | patch |
| 3 | Resume skips a pending task whose node already completed (failed non-final, then crash) (edge) | medium | `runner.py` resumes with `None` whenever `snapshot.next` is set; the finished-with-`{}` node is not in `next` | patch: start fresh when a task is neither `finished` nor in `next` |
| 4 | Worker graph-runner install and schedule polling are never exercised; conftest autouse runner masks it (VG) | medium | `test_worker.py`/`test_jobs.py` never pass `workflows.execute`; no test drives `_enqueue_schedules` | patch: tests |
| 5 | Progress rows from cancel, retry and lost runs are unasserted (VG) | medium | Only the happy path asserts `workflows_progress` | patch: tests |
| 6 | Final-attempt fallback for tasks still unfinished after the graph is untested (VG) | medium | No test reaches `if unfinished:` in `_execute` | patch: test |
| 7 | `conninfo`/`listen_conninfo` duplicated, and other driver prefixes are not handled (blind, edge) | low | Same function in `events.py` and `checkpointer.py` | patch: one helper in `platform/db.py` using `make_url` |
| 8 | Catalogue docstrings still name the system actor `assessments.run_assessment` (edge) | low | `catalogue.py:429,494`; the actor is now `workflows.execute` | patch: docstrings |
| 9 | `error_code` maps every non-model error to `model_unavailable` (blind, edge) | low | Pre-existing: identical `error_code` in `assessment.py` at baseline :668 | defer |
| 10 | `psa_app` can update `plan_version`/`requires` (blind, edge) | false | `has_column_privilege('psa_app', …, 'UPDATE')` is false for both on the migrated DB (column grants from 0017 don't cover new columns) | reject |
| 11 | The stream route holds the request UoW open for the stream's life (blind) | false | `UoW` is `Depends(get_uow, scope="function")`: it commits and closes before the response is sent | reject |
| 12 | Replay orders by UUIDv7, so out-of-order commits can be skipped (blind, edge) | low | Real in theory, but the section re-reads the whole view on every (re)connect, so a skipped trigger loses no state | reject |
| 13 | Replay capped at 500 rows (blind, edge) | low | Same: reconnect triggers a full re-read | reject |
| 14 | One Postgres connection per open stream, opened even with no run in progress (blind, edge) | low | Real, but harmless at demo scale; a shared listener is new machinery | reject |
| 15 | Stream generator ends uncleanly on a DB blip mid-stream (edge) | low | EventSource reconnects by itself and the section polls meanwhile | reject |
| 16 | `saver.setup()` races across workers (edge) | low | One worker, `worker_concurrency` pinned to 1 | reject |
| 17 | `requires` cycles never start (edge) | low | Plans are built by code with no `requires` today; unreachable | reject |
| 18 | Final-attempt waiting tasks get `model_unavailable` (edge) | low | Waiting needs a prerequisite still pending on the final attempt; unlikely | reject |
| 19 | Checkpoints never pruned (blind) | low | A few small rows per run; growth is negligible | reject |
| 20 | Lost runs are noticed only on the next command (blind) | low | Pre-existing lazy `fail_stale`; the visible harm is covered by #1 | reject |
| 21 | Nothing-to-assess task rebuilds the Estimate (blind) | low | Pre-existing: baseline `_run` finished such runs the same way | reject |
| 22 | Cancelling a retried run rebuilds the Estimate (blind) | low | Pre-existing: baseline `cancel` :316-332 | reject |
| 23 | `requeue_task` accepts `cancelled` at the data layer; retry traced as a 1-agent start (blind) | low | Pre-existing: baseline `requeue_task` :272 | reject |
| 24 | Schedules checked only between jobs; due rows of other types locked (blind) | low | Daily prune delayed by at most a job; single worker | reject |
| 25 | Poll result applied after effect cleanup (edge, deletion) | low | React drops state set after unmount; the remaining case is covered by #2's sequence guard | reject |
| 26 | No tests for the cancel watcher, timeout fail-open or pruned `Last-Event-ID` (blind) | false | Covered by `test_cancel_stops_the_in_flight_calls…`, `test_a_cancelled_run_is_recorded_as_timed_out_only_on_the_final_attempt`, `test_an_unknown_last_event_id_streams_from_now` | reject |

## Design Notes

LangGraph keeps the writes of a superstep's successful nodes when a sibling raises, so a retry re-runs only the failed node. The DB re-read in each node covers the window between `accept_assessment` committing and the checkpoint write. Renaming the tables, rather than copying them, keeps ids, so the Assessments, the Estimates' `source_run_id`, Conflicts' `run_id` and model-call rows still line up.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks:**
- `docker compose up`, run the demo intake, and watch the Assessments tab update live. Kill the worker mid-run, restart it, and confirm the run completes with no duplicate Assessments.
