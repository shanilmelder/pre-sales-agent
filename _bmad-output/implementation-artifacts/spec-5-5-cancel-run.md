---
title: 'Story 5.5 (demo slice): cancel an assessment run'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: 'eb75cbbfcd188ac84935c57b6e88b0123e034006'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-7-agent-run-panel.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** There is no way to stop an assessment run that was started by mistake or is taking too long; it holds the model slots and blocks a new run until it ends (FR-63, UX-DR10).

**Approach:** A **Cancel run** button in the agent run panel, confirmed first, stops a queued or running run: Assessments already completed stay, and the unfinished tasks are marked skipped.

## Boundaries & Constraints

**Always:**
- **Depends on:** Stories 5.8 + 5.9 demo slice and the Story 5.7 demo slice (the run panel). Start once 5.7 is merged.
- **Statuses:** run gains `cancelled`; task gains `skipped`. Migration `0018_assessments_cancel` widens both CHECK constraints (grants unchanged).
- **Command:** `POST /opportunities/{id}/assessment-runs/{run_id}/cancel` (action `assessments.assessment.start`: owner and collaborators except sales representatives). Only the latest run, while `queued` or `running`; otherwise 409 `assessment_not_in_progress`. In one Unit of Work under the run lock: unfinished tasks → `skipped`, run → `cancelled` (`finished_at` set), trace `assessments.assessment_run.cancelled` (actor the user; `skipped_count`, `succeeded_count`). Assessments already accepted stay current.
- **Worker side:** a reply arriving after cancel is discarded (acceptance already requires the task to be `running`). While the agents work, the handler re-reads the run every 2 s and cancels its in-flight calls once the run is `cancelled`, so model slots free up; it then ends without error. A queued job for a cancelled run is skipped. A cancelled run never becomes `succeeded`, `partially_failed` or `failed` afterwards (stale handling and final-attempt failure leave it alone).
- **Web:** **Cancel run** in the run panel header, only while queued or running and only when `can_start`. It opens a confirm dialog "Cancel this run? Completed results are kept." (Confirm / Keep running), returns focus after closing, and announces the result politely. Skipped rows: neutral pill, duration if the task had started. Header for a cancelled run: "Cancelled — completed results kept". A cancelled run can't be retried; **Run assessment** starts a new one. Read-only for sales representatives.
- **Privacy:** no Requirement, Gap or Finding text in logs or trace.

**Never:** No pause/resume, Skip button, decisions or `waiting_for_human`, budget stops, cancelling a single task, or LangGraph code. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cancel running | PM and Security running, Engineering succeeded | Run `cancelled`; PM and Security `skipped`; Engineering's Assessment stays current; trace event | N/A |
| Late reply | A fake agent replies after cancel | Nothing stored; task stays `skipped`; run stays `cancelled` | N/A |
| Slots freed | Fake gateway blocks until cancelled | In-flight calls are cancelled within ~2 s; the job ends without error | N/A |
| Cancel queued | Run queued, job not started | Run `cancelled`, all tasks `skipped`; the job later skips it | N/A |
| Final attempt | Cancel during a job's final attempt | Run stays `cancelled` (not failed) | N/A |
| Not running | Cancel a finished or older run | 409 `assessment_not_in_progress` | N/A |
| Who | Sales rep cancels / reads | 403 / 200 | N/A |
| Rerun | Run assessment after a cancel | A new run starts (no 409) | N/A |
| Dialog | Keep running | Nothing sent; focus back on Cancel run | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/domain/assessments.py`: `AssessmentRunStatus`, `AssessmentTaskStatus`, `run_status` (a cancelled run is set directly, never derived).
- `backend/app/modules/assessments/application/assessment.py`: `_run` (`asyncio.gather` of `_task`s; add the 2 s cancel watcher that cancels the gathered tasks), `_start` (already skips a run not in progress), `finish_run` (already a no-op for a finished run), `accept_assessment` (already requires `running`), `_fail_open` and `fail_stale` (must not touch a cancelled run; they already filter by in-progress statuses, so verify).
- `backend/app/modules/assessments/application/assessments.py`: `retry_task` as the pattern for `cancel_run`; `run_view` (a cancelled run is never "lost"). `retry_task` must refuse a cancelled run (409 `assessment_task_not_failed`): a task that failed before the cancel would otherwise let `requeue_task` (which moves the run from any status to `queued`) revive it.
- `adapters/assessment_repository.py` (`update_tasks`, `set_run_status`, `lock_runs`), `adapters/models.py` + migration `0018_assessments_cancel` (revises `0017_assessments_specialists`), `application/models.py`, `application/public.py`, `api/routes.py` (`_responses` variant keys).
- `backend/app/platform/errors.py` (`AssessmentInProgressError` → `AssessmentNotInProgressError`), `platform/trace/catalogue.py` (`AssessmentsAssessmentRunStarted` pattern); `web/src/lib/trace.ts` `EVENT_LABELS`.
- Don't change the job runner (`platform/jobs/runner.py:134-163` shows how handler cancellation already works).
- Web: `app/opportunities/actions.ts` (`retryAssessmentTask` → `cancelAssessmentRun`, with tests), the run panel from 5.7 in `components/opportunities/specialist-assessments.tsx`, `components/ui/dialog.tsx`. Regenerate `schema.d.ts` from a local uvicorn.
- Tests: extend `backend/tests/test_assessments_specialists.py` / `_api.py` (`AgentGateway`, `_Hanging`, `drain`, `retry`) and `specialist-assessments.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/assessments/**`, migration 0018, errors, catalogue -- cancel command and route, statuses, cancel watcher
- [x] `backend/tests/test_assessments_specialists*.py` -- every matrix row (fake gateway, Postgres)
- [x] Web: `schema.d.ts`, `cancelAssessmentRun` + tests, Cancel button and confirm dialog, skipped rows and cancelled header, trace label, tests with axe

**Acceptance Criteria:**
- Given an assessment running on the demo Opportunity, when the presales engineer presses Cancel run and confirms, then the remaining agents stop within seconds, finished Assessments stay, and Run assessment is available again.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- `cancel` (in `application/assessment.py`) skips running tasks with `finished_at` stamped (they keep a duration) and queued tasks without it, then sets the run `cancelled` + `finished_at`; `succeeded_count` is read back after the updates, so a reply accepted just before the cancel (serialised on the task row) counts as kept.
- `cancel_run` runs `fail_stale` first, so a lost run reads and stays `failed` and can't be cancelled (409).
- Watcher: `_run` gathers `asyncio.create_task`s; `_watch_cancel` re-reads the run every `CANCEL_POLL_S` (2.0 s) and cancels them. After the gather, a watcher hit (or any error while the run is already `cancelled`) ends the handler without raising, so the job completes and no retry is queued.
- Route returns 200 (not 201): it changes an existing run. Response key `4093` / `4222` added to `_DESCRIBED`.
- Web: after a successful cancel, focus moves to **Run assessment** (Cancel run unmounts); Keep running returns focus to Cancel run through the Base UI dialog trigger.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | VG: the "task error after the cancel" branch is untested | medium | Pre-verified; the `_Blocking` and timeout tests never reach it | patch: parametrized test |
| 2 | Post-gather `_cancelled()` read unguarded (blind, edge) | low | A database error replaces `errors[0]` in the retry/fail paths | patch: guarded read |
| 3 | A cancel landing after the post-gather check still re-raises (edge, edge claim) | low | `finish_run` no-ops for a cancelled run, then `raise errors[0]` | patch: re-check before each raise |
| 4 | A cancel after every task finished but before `finish_run` records a completed run as cancelled (edge) | low | Run is still `running` until `_run`'s final UoW | patch: 409 when no task is unfinished |
| 5 | Confirm dropped silently while `busy` (blind, edge) | low | `act()` returns early with no message | patch: trigger and Confirm disabled while busy |
| 6 | Focus rule matches any `<section>` (blind, edge) | low | `closest("section")` isn't scoped to this section | patch: section ref |
| 7 | A 409 on cancel is silent and drops focus (blind) | low | Conflict branch re-reads only; Cancel run unmounts | patch: announce and refocus |
| 8 | Freed-slots test relies on real 2 s sleeps (blind) | low | `< CANCEL_POLL_S + 1.5` on shared CI | patch: patched poll interval |
| 9 | 409 description for retry doesn't mention cancelled runs (blind) | low | `_DESCRIBED[4092]` | patch: description |
| 10 | Downgrade sets every cancelled run `failed` and skipped tasks `model_timeout`; downgrade untested (blind, edge, VG) | low | True; rollback isn't on the demo path | defer |
| 11 | Cancel trace event has no `failed_count` (blind) | low | Spec defines the payload as skipped and succeeded counts | reject |
| 12 | Header says "completed results kept" when none completed (edge) | low | Spec's exact copy | reject |
| 13 | Dialog open when a poll ends the run (blind) | low | Rare; handling adds complexity | reject |
| 14 | Cancel 404 says "no access" (edge) | low | Needs a run id that isn't the Opportunity's; rare | reject |
| 15 | Watcher opens a UoW every 2 s (blind) | low | One short read per running job; worker concurrency 1 | reject |
| 16 | `schema.d.ts` missing from the diff (blind) | false | Left out of the review diff on purpose (generated); it is in the tree | reject |
| 17 | `_Blocking` duplicates `_Hanging` (blind) | low | Test helpers only | reject |
| 18 | Untested: concurrent cancels, accept/cancel race, watcher read failure, cancel during backoff (blind) | low | Serialised by the run lock and the task row lock | reject |
| 19 | Cancel run renders without a handler (blind) | low | The section always wires it | reject |
| 20 | Skipped duration includes backoff idle time (edge) | low | Only after a failed non-final attempt; cosmetic | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`, deferred)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
