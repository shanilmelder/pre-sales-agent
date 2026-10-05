---
title: 'Story 5.1 (demo slice): queue the assessment run automatically after Gap detection'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '201f92a4a2322571770110993a1c3cecab6f9d4d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-5-cancel-run.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every other step of the pipeline queues the next one itself (extraction → Gap detection → Estimate draft → Red Team), but the specialist assessment only runs when someone presses **Run assessment**, so a fresh Opportunity has no Assessments until a person remembers to.

**Approach:** Every successful Gap detection also queues an assessment run of the Opportunity, in the same Unit of Work that queues the Estimate draft. **Run assessment** stays for manual re-runs, with Retry and Cancel unchanged.

## Boundaries & Constraints

**Always:**
- **Depends on:** Stories 5.8 + 5.9, 5.7 and 5.5 demo slices (merged or stacked).
- **Trigger (decided):** `gaps.accept_gap_detection`, after the detection succeeds, calls a new `assessments.enqueue_run(uow, opportunity_id)` through `assessments.application.public` (function-level import, as for `estimates.enqueue_draft`, to avoid a circular import). Also when the detection found 0 Gaps.
- **`enqueue_run`:** under the run lock, fails stale runs first (`fail_stale`); if a run of the Opportunity is already `queued` or `running`, it adds nothing and returns that run's id (logged as coalesced; the running run keeps the inputs it read). Otherwise it queues a run exactly like **Run assessment** (one task per agent, one job), with the trace `assessments.assessment_run.started` attributed to the system actor `assessments.run_assessment`. It never raises a conflict, so it never fails the Gap detection.
- **Manual button kept (decided):** **Run assessment**, Retry and Cancel behave as before (409 while a run is queued or running).
- **Web copy (decided):** the empty state becomes "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected." (like the Red Team's "…after the Estimate is drafted"). Opening the tab while an automatic run is queued or running shows the run panel and polls, as for a manual run.
- **Privacy:** no Requirement, Gap or Finding text in logs or trace.

**Never:** No new migration, no trigger from extraction, the Estimate draft or Requirement edits, no queueing a second run behind a running one, no change to the Red Team or Estimate chain, no LangGraph code. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Auto | A Gap detection succeeds; no run exists | One run `queued` with three tasks and one `assessments.run_assessment` job, in the detection's Unit of Work; trace `…assessment_run.started` by the system; Estimate draft still queued | N/A |
| No Gaps | Detection succeeds with 0 Gaps | A run is still queued | N/A |
| Coalesce queued | A run is already `queued` | No new run or job; detection succeeds | N/A |
| Coalesce running | A run is `running` | No new run or job; detection succeeds | N/A |
| Stale | A lost run past `stale_after()` | It is failed first, then a new run is queued | N/A |
| Detection fails | Detection ends `failed` | No run queued | N/A |
| Manual still works | No run in progress; Run assessment | 201, as before; 409 while the automatic run is queued | N/A |
| End to end | Extraction → detection → drain jobs | Three Assessments stored without anyone pressing Run assessment | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/application/detection.py:296-302` — where `accept_gap_detection` queues `estimates.enqueue_draft`; add `assessments.enqueue_run` next to it (function-level import, same comment pattern). Module docstring step 4 mentions the new hand-off.
- `backend/app/modules/assessments/application/assessment.py` — `queue_run` (inserts run + tasks + job + started trace; takes an `Actor`), `fail_stale`, `_SYSTEM` (the system actor), `lock_runs` via `repo`. Add `enqueue_run` here, modelled on `review.enqueue_review` (`application/review.py:108-120`: lock, `fail_stale`, coalesce, queue, log).
- `backend/app/modules/assessments/application/public.py` — export `enqueue_run` (as `enqueue_review` is exported).
- Import-linter: gaps may use assessments only through its public API (`backend/pyproject.toml:120-138`); unchanged.
- Web: `web/src/lib/assessments.ts` `NO_ASSESSMENT` (empty-state copy) and its tests.
- **Tests that will change:** the specialist tests' `prepared` helper (`backend/tests/test_assessments_specialists.py`, via `tests.test_estimates_draft.detected`) runs a Gap detection, which will now queue a run, so `started(...)` would hit 409. Either have the tests use the automatically queued run, or monkeypatch `enqueue_run` off in `prepared` for the tests that start runs by hand — keep each existing test's intent. `tests/test_intake_extraction.py` `_hidden_jobs` already hides `assessments_assessment.enqueue` and retires `assessments.run_assessment` jobs. Check `test_gaps_detection*`, `test_estimates_draft*` and Red Team tests that count jobs or trace events after a detection.
- New tests: `enqueue_run` rows of the matrix in `test_assessments_specialists.py`; the "Detection fails" and "Auto" rows next to the detection tests; the end-to-end row with the fake gateways.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/assessments/application/{assessment,public}.py` -- `enqueue_run` -- coalescing, stale handling, system actor
- [x] `backend/app/modules/gaps/application/detection.py` -- queue the run after a successful detection
- [x] `backend/tests/**` -- matrix rows; adjust existing tests broken by the new automatic run without weakening them
- [x] `web/src/lib/assessments.ts` (+ tests) -- empty-state copy

**Acceptance Criteria:**
- Given the demo Opportunity with the worker running, when its sources are extracted and Gaps detected, then the assessment runs by itself and the Assessments tab shows the three agents' results without anyone pressing Run assessment.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- `enqueue_run` (`application/assessment.py`): `lock_runs` → `fail_stale` → `run_in_progress` (coalesce, logged `assessments.assessment_run_coalesced`) → `queue_run(…, _SYSTEM)` (logged `assessments.assessment_run_queued`). Exported through `public.py`; `accept_gap_detection` calls it right after `estimates.enqueue_draft` (function-level import). The "outdated" detection branch (a newer detection already succeeded) queues neither, as before.
- Tests: `test_assessments_specialists.py` gets an autouse `_no_auto_run` that stubs `public.enqueue_run` (the entry point the detection uses) so the existing hand-started tests keep their intent; a test requesting the `auto_run` fixture keeps the real behaviour. `_api.py` imports both fixtures. Red Team `events()` narrowed to `assessments.red_team%` (it counted every `assessments.*` event, now including the run-started one).
- New tests: detection queues a run with/without Gaps (system actor, Estimate draft still queued) and a failed detection queues none (`test_gaps_detection.py`); coalesce queued/running, stale, manual 409-then-201, end to end (`test_assessments_specialists.py`); web test for opening the tab with a queued run.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap — the last found no verification gaps):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | "Never fails the Gap detection" holds only for conflicts; a DB error in `enqueue_run` rolls back the detection (blind, edge claim) | low | Same Unit of Work, as with `estimates.enqueue_draft` | patch: docstrings say so |
| 2 | `AssessmentsAssessmentRunStarted` docstring says the actor is always a person (VG other) | low | The automatic run traces the system actor | patch: docstring |
| 3 | Red Team `events()` filter narrowed to `assessments.red_team%` hides stray events (blind, edge) | low | Weaker than before | patch: exclude only assessment-run events |
| 4 | No test runs a second detection through `accept_gap_detection` while the automatic run is queued (blind) | low | Coalescing tested only by calling `enqueue_run` | patch: test |
| 5 | Coalescing with a running run (or a retry-requeued one) leaves newer Gaps unassessed with no marker (blind, edge ×2) | low | True; the intent decided "no queueing a second run behind a running one", and the user accepted this trade-off when choosing the trigger | reject (intent excludes it; follow-up run flag offered to the user) |
| 6 | Empty-state copy promises an automatic run for Opportunities detected before this change, or whose detection failed (blind, edge) | low | True; copy decided in the intent; changing it needs detection state in the view | reject |
| 7 | No test for an outdated detection queueing nothing (blind) | low | Pre-existing early return, unchanged | reject |
| 8 | `_no_auto_run` stub returns a random id (blind) | low | Return value unused | reject |
| 9 | New web test can't tell an automatic run from a manual one (blind) | false | The read model is the same by design; the test covers opening the tab mid-run | reject |
| 10 | Automatic and manual runs log different event names (blind) | low | Logs only | reject |
| 11 | Spec sections unfinished (blind) | false | Filled during review | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`, deferred)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
