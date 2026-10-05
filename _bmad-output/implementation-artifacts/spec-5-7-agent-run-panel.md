---
title: 'Story 5.7 (demo slice): agent run panel with live timings'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: 'f34f317aefad13576daab0cad6a3a4164a78cd2e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A running assessment shows only one text line per agent ("Engineering Agent — Assessing…"). Stakeholders can't see how long each agent has been working or how long each took (FR-3, UX-DR10).

**Approach:** An **agent run panel** in the Specialist Assessments header shows one row per task of the latest run: the agent's role, a status pill, elapsed time that ticks while it runs (final duration once done) and a running dot.

## Boundaries & Constraints

**Always:**
- **Depends on:** Stories 5.8 + 5.9 demo slice (`assessments_runs`/`assessments_tasks` with `started_at`/`finished_at`, the Specialist Assessments section, Retry). Start once that PR is merged.
- **Placement (decided):** Assessments tab only. The panel replaces the per-agent text lines in the Specialist Assessments header; Overview is unchanged.
- **Live updates (decided):** keep the existing polling (2 s, paused while hidden, stops after 15 min). No SSE (none exists yet).
- **Read model:** each task gains `started_at` and `finished_at`; the run gains `queued_at` and `finished_at`. No migration (the columns exist). Elapsed time is computed in the browser (server clock skew ignored for the demo).
- **Rows (28px):** role name ("Engineering Agent"); status pill (Queued neutral, Running agent colour, Done green, Failed red with its reason and the existing **Retry**); elapsed time in tabular figures (`m:ss`, ticking each second while running, final duration when done or failed, blank before starting or when a failed task has no finish time, e.g. a lost run's); a running dot while running, static under `prefers-reduced-motion`. Queued rows say "Waiting for the worker".
- The panel shows for the latest run in any status (so finished durations stay visible); the run's status stays in the header.
- Keyboard and axe as in the Red Team list; read-only for sales representatives (no Retry).
- **Privacy:** no Requirement, Gap or Finding text in logs or trace.

**Never:** No Cancel (Story 5.5 demo slice), SSE, activity rail, queue position, Skip or Resolve, budget banner, run history, tab badge, or LangGraph code. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Timings | Engineering done, PM running, Security queued | API gives the timestamps; panel shows a final duration, a ticking time, and a blank with "Waiting for the worker" | N/A |
| Ticking | PM running, 65 s since `started_at` | Shows `1:05`, then `1:06` a second later without a fetch | N/A |
| Failed | Security failed `model_timeout` after 2:10 | Red pill with the reason, `2:10`, Retry for those who may start | N/A |
| Finished | Run succeeded | Every row Done with its duration; no running dot | N/A |
| Reduced motion | `prefers-reduced-motion: reduce` | Running dot static | N/A |
| Who | Sales rep reads | Rows and timings, no Retry | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/adapters/assessment_repository.py`: `RunRecord` (has `queued_at`, `finished_at`), `TaskRecord` (add `started_at`, `finished_at`; the row has them).
- `backend/app/modules/assessments/application/models.py`: `AssessmentTask`, `AssessmentRun` (add the timestamps). `application/assessments.py` `run_view` (fill them; a lost run's tasks keep their timestamps).
- `backend/tests/test_assessments_specialists_api.py`: extend the view assertions.
- `web/src/components/opportunities/specialist-assessments.tsx`: `SpecialistAssessmentsHeader` (~:332, the task lines to replace), polling in `SpecialistAssessmentsSection` (~:453). `web/src/lib/assessments.ts`: `taskLine`, `failureReason`, `RUN_STATUS_LABELS` (add an elapsed-time formatter, unit-tested). Reuse the existing status-pill styles and the `text-numeric` utility.
- Regenerate `web/src/lib/api/schema.d.ts` from a local uvicorn (not the Docker api).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/assessments/**` -- timestamps in the read model -- the panel needs them
- [x] `backend/tests/test_assessments_specialists_api.py` -- timestamps per task and run
- [x] Web: `schema.d.ts`, `lib/assessments.ts` formatter + tests, run panel rows with ticking timer and reduced-motion dot, tests (fake timers) with axe

**Acceptance Criteria:**
- Given the demo Opportunity with the worker running, when the presales engineer presses Run assessment, then each agent's row shows its status and elapsed time updating without a reload, and each finished row keeps its duration.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | `useNow` uses the mount-time clock when ticking starts (all three layers) | low | `useState(() => Date.now())` and the effect only sets `now` from the interval | patch: set `now` when ticking starts |
| 2 | Time keeps ticking after polling stalls (all three layers) | low | `useNow(assessing)` ignores `stalled`; the header says "reload" | patch: stop ticking when stalled, with a test |
| 3 | `taskElapsed` shows a duration for any task with `finished_at` (blind, VG other) | low | No status check; safe today only because retry resets the stamps | patch: status-gated, with unit cases |
| 4 | VG: retry response never checked for cleared stamps and re-stamped run | medium | Pre-verified gap; the panel depends on `reset`/`requeued` | patch: retry test extended |
| 5 | edge: `fail_stale` stamps `finished_at`, so a retried lost run shows hours-long durations | low | `fail_stale` calls `update_tasks(..., finished=True)`; the spec asks for blank | patch: lost tasks keep `finished_at` null |
| 6 | blind: a lost run reads failed with a null `finished_at`, against the docstring | low | `run_view` passes `record.finished_at` through | patch: docstring |
| 7 | blind: web lost-run fixture has a run `finished_at` the API never sends | low | `run()` helper sets `at(300)` for every finished status | patch: fixture `null` |
| 8 | blind: fake-timer test can leak timers; "no fetch" proof weak | low | `useRealTimers` inline; 1 s tick before any poll does show the tick needs no fetch | patch: `finally` (the "weak proof" part is false) |
| 9 | blind: import order in `assessments.test.ts` | low | `formatElapsed` out of order | patch |
| 10 | blind: `TaskStatusPill` copies the status-pill classes | low | Refactor only; no user-visible harm | reject |
| 11 | blind: elapsed time has no screen-reader context and status changes aren't announced | low | Axe is clean; adding live announcements adds complexity | reject |
| 12 | blind: no keyboard test for Retry | low | Native button, already covered by click tests from 5.8 + 5.9 | reject |
| 13 | blind: spec unfinished | false | Status is `in-review`; these sections fill during review | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`, deferred)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
