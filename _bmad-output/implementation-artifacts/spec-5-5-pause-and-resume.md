---
title: 'Story 5.5 (pause and resume): a run waits for a person when an Agent is disabled'
type: 'feature'
created: '2026-10-23'
status: 'in-progress'
baseline_commit: '6a38bd5e8360caffdf029249f1bc521a0197b6d4'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-2-durable-langgraph-execution.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-5-cancel-run.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When an Agent is disabled, its task is silently skipped (Story 7.1), so nobody decides whether the run should go on without it. Runs can't wait for a person, and the cancel/retry demo slice left pause and resume as `[post-demo]` (FR-17, AD-7).

**Approach:** A task whose Agent is disabled or `eval_only` asks a person instead of skipping. Its node calls LangGraph `interrupt()`, the run becomes `waiting_for_human` with one open decision, and **Continue without** or **Re-plan** resumes the checkpointed graph with `Command(resume=…)` from the interrupted node, even after days and a worker restart.

## Boundaries & Constraints

**Always:**
- **Statuses:** run gains `waiting_for_human`, and the run's task stays `queued` while it waits. A waiting run counts as active: a new start gets 409 `assessment_in_progress`, `enqueue_run` coalesces with it, it is never failed as stale, and retry gets 409. The Estimate tab's "run in progress" stays queued/running only.
- **Decision record:** new `workflows_decisions` (run, task, kind `plan_escalation`, status `open|resolved|cancelled`, choice `continue_without|replan`, payload with ids/codes only, resolved_by, resolved_at, `row_version`; unique (run_id, task_id, kind)). Recording it before `interrupt()` is idempotent (insert on conflict do nothing). When the graph returns with an open decision and no task running, the handler sets the run `waiting_for_human`, writes a progress row, and appends trace `workflows.run.waiting_for_human` (agent, decision id). The job ends without error.
- **Resolve:** `POST /opportunities/{id}/assessment-runs/{run_id}/decisions/{decision_id}/resolve` with body `{choice}` and `If-Match` (decision `row_version`). New action `workflows.decision.resolve`: owner and collaborators except sales representatives (relation grant, no Auth0 change). In one Unit of Work under the run lock it records the choice, sets the run `queued`, enqueues a `workflows.resume` job, and traces `workflows.decision.resolved`. Errors: 428 without If-Match; 412 with detail "Already resolved by {name}." when stale; 409 `decision_not_open` when the decision is not open or the run was cancelled.
- **Continue without:** the task becomes `skipped` / `agent_disabled` (shown as today's "Agent disabled — assess manually").
- **Re-plan:** allowed only once the Agent is active again (otherwise 409 `registry_agent_disabled`). It re-pins the task to the Agent's current config version and bumps the run's `plan_version`. The task then runs.
- **Resume:** the resume job resumes the run's thread with `Command(resume={interrupt_id: choice})`. Completed nodes are not re-run, and the node treats the decision row as truth.
- **Cancel:** also allowed while `waiting_for_human`. Open decisions become `cancelled`, and resolving afterwards gets 409.
- **Web:** while a run waits, the run panel's task card shows an amber **Waiting for you** pill with "{Agent} assessment not planned: {Agent} is disabled" and **Continue without** / **Re-plan** buttons. Re-plan is disabled with "Enable the agent first" while the Agent is inactive. A 412 shows "Already resolved by …" and reloads. The Overview shows a "Waiting for you" pill on the Agent run card and a Needs you row (amber, clock icon) whose **Resolve** link opens the Assessments tab. Cancel run is shown while waiting. The view is read-only for sales representatives. Trace labels are added.
- **Decided (automatic runs):** every run escalates, including the automatic run after a Gap detection. While an Agent is disabled, that run waits (its Estimate is not rebuilt) until someone resolves it.
- **Decided (plan versions, FR-15):** every plan version is stored in `workflows_plan_versions` (run_id, version, per task its agent and config version, created_by, created_at; unique (run_id, version)). v1 is written when the run is queued and v2+ on Re-plan. The run view returns `plan_versions`, and the run panel shows "Plan v{n}" with a disclosure listing each version's Agents, config versions, who and when.
- **Privacy:** ids and codes only in logs, payloads, progress and trace.

**Never:** No `task_failed` decisions or Retry/Skip-on-failure (Story 5.6), budgets, Inbox (9.2), filled Activity tab (5.7: decisions show in Recent activity via trace), idempotency-key table, or plan editing beyond Re-plan.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Escalate | Security disabled, run starts | Eng and PM run; Security task `queued`; one open decision; run `waiting_for_human`; trace + progress | N/A |
| Idempotent | Node re-runs before resolve | Still one decision row, one trace event | N/A |
| Continue without | Resolve `continue_without` | Security `skipped`/`agent_disabled`; run finishes `succeeded`; Estimate built; Eng/PM not re-run | N/A |
| Re-plan | Agent re-enabled, resolve `replan` | `plan_version` 2, Security re-pinned and runs; run finishes | Still disabled → 409 `registry_agent_disabled` |
| Restart | Interrupt, discard runner and pool, new runner, resolve | Resumes from checkpoint; no duplicate Assessments | N/A |
| Race | Two resolves, same If-Match | First applied; second 412 "Already resolved by {name}." | N/A |
| Cancel waiting | Cancel while waiting | Run `cancelled`, task `skipped`, decision `cancelled`; resolve 409 | N/A |
| Coalesce | Gap detection while waiting | No new run | Manual start 409 |
| Who | Sales rep resolves | 403; controls hidden | N/A |
| Plan history | After Re-plan | `plan_versions` lists v1 (Security at its old config) and v2 (re-pinned), each with who and when | N/A |

</frozen-after-approval>

## Code Map

- `app/modules/workflows/domain/runs.py` -- `AssessmentRunStatus` (+`WAITING_FOR_HUMAN`), `RUN_IN_PROGRESS` stays queued/running; add `RUN_ACTIVE`; `ProgressEvent` (+`workflows.run.waiting_for_human`); decision kinds/choices/status enums.
- `app/modules/workflows/adapters/models.py`, `repository.py` -- run status CHECK, progress CHECK, `WorkflowDecisionRow`, `WorkflowPlanVersionRow` (written by `queue_run` and Re-plan); `run_in_progress` (keep) vs new `run_active`; `stale_runs` must exclude waiting.
- `app/modules/workflows/application/runs.py` -- `queue_run` stops inserting `skipped` for inactive Agents; `_start`/`_skip_disabled` stop skipping (they escalate in the node instead); `_execute` after the graph: open decision and no running task → `mark_waiting` (not `RunIncompleteError`, not `finish_run`); new `RESUME` job type reusing `_execute`; `cancel` closes open decisions and accepts waiting runs; `_fail_open` leaves a waiting run alone.
- `app/modules/workflows/application/tasks.py` -- `escalation(uow, task_id)` (records decision idempotently, returns payload or the resolved choice), `skip_disabled_task` for continue_without.
- `app/modules/workflows/application/assessment_runs.py` -- `resolve_decision` (pattern: `retry_task`, plus `parse_if_match` as in `conflicts/application/decisions.py`); `cancel_run` accepts waiting; `run_view` adds `plan_version` and `decisions` (id, kind, agent, status, row_version, agent_active, resolved_by name).
- `app/modules/workflows/application/{models,public}.py`, `api/routes.py` -- view models, route, `_DESCRIBED` keys, `ETag`.
- `app/orchestration/graph.py` -- in `run_task`, before `begin_task`: inactive Agent → commit decision, then `interrupt(payload)` **outside** every `try/except Exception` (`GraphInterrupt` subclasses `Exception`). `runner.py` -- when the snapshot has pending interrupts and decisions resolved, invoke `Command(resume={interrupt.id: choice})`.
- `app/modules/identity/actions.py`, `domain/policy.py` -- `DECISION_RESOLVE` in owner/member grants, excluded for sales reps.
- `app/platform/errors.py` (`DecisionNotOpenError`), `platform/trace/catalogue.py` (two events).
- Migration `20261023_0038_workflows_decisions.py` revises `0037_intake_requirement_integration_types` (PR #77 also adds a 0037 and must be renumbered when it is rebased). Clean downgrade: waiting runs become `failed`.
- Web: `lib/assessments.ts` (status label, decision types), `app/opportunities/actions.ts` (`resolveRunDecision` with If-Match, like the Conflict resolve action), `components/opportunities/specialist-assessments.tsx` (`TaskCard`, `AgentRunPanel`, cancel visibility), `lib/overview.ts` + `overview-summary.tsx` (`AttentionKind` `waiting-run`), `lib/trace.ts` `EVENT_LABELS`, `lib/api/schema.d.ts` regenerated from a fresh backend.
- Tests to update without weakening: `tests/test_registry.py:661-725` (skips become escalations), `test_assessments_specialists*.py`, `test_orchestration.py`, `specialist-assessments.test.tsx`, overview tests.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261023_0038_workflows_decisions.py`, `workflows/adapters/*` -- decisions and plan-versions tables (backfill v1 for existing runs from their tasks), CHECKs, grants (psa_app: insert/select; update only on decision status columns)
- [x] `workflows/domain`, `application/{runs,tasks,assessment_runs,models,public}.py`, `api/routes.py`, identity, errors, trace -- escalation, waiting, resolve, resume job, cancel
- [x] `app/orchestration/{graph,runner}.py` -- interrupt and `Command(resume)`
- [x] `backend/tests/test_workflows_decisions.py` + updated tests -- every matrix row, the restart row with a fresh runner
- [x] Web files above + tests (axe on the waiting card)

**Acceptance Criteria:**
- Given the Security Agent disabled, when the presales engineer runs an assessment, then Eng and PM finish, the run waits with a Waiting for you pill on the Overview, and Continue without finishes it without re-running them.
- Given CI, when it runs, then ruff, format, mypy, lint-imports, `alembic check` up/down/up, pytest, and the web lint, typecheck, test and build all pass with no live model.

## Implementation Notes

- **Migration** is `0038_workflows_decisions` (revises `0037_requirement_tags`, the real revision id of `20261023_0037_intake_requirement_integration_types.py`). Besides the two tables it grants `psa_app` UPDATE on `workflows_tasks.config_version_id` and `workflows_runs.plan_version` (Re-plan needs both); the two tests that asserted those were denied now assert other columns are. Downgrade also fails the waiting runs' unfinished tasks (`model_timeout`), kills open `workflows.resume` jobs and deletes the waiting progress rows.
- **Run status after Continue without** stays the existing domain rule: a run with a skipped task ends `partially_failed` (epic: "a run with skipped tasks never shows plain success"); the job itself ends `succeeded`. The matrix's "run finishes succeeded" was read as the job.
- **Trace name** `workflows.run.waiting_for_human` is not a past-tense verb: `catalogue.is_valid_event_type` gained a one-entry allow-list of state events. Both new events take the run (`assessments.assessment_run`) as subject.
- **Node** (`orchestration/graph.py`): `workflows.escalation()` runs for queued tasks only, before `begin_task`; it records the decision with insert-on-conflict-do-nothing and commits before `interrupt()`, which is called outside every `try`. On resume the node re-reads the decision: Continue without → `skip_disabled_task` (traced `assessments.task.skipped` by the system), Re-plan → runs. The runner resumes with `Command(resume={interrupt.id: choice})` for interrupts whose decision (named in the payload) is resolved, else `None`.
- **Handler**: after the graph returns, `_wait` (under the run lock) marks the run `waiting_for_human` when a decision is open and no task is running, so a job that dies before that and runs again re-interrupts without a second decision or trace event. `finish_run` and the cancel close any decision still open. `workflows.resume` (`ResumeRun`) reuses the execute handler; the worker installs the graph runner when it claims either type.
- **Resolve order**: 428 → 409 when the decision or run is cancelled → 412 "Already resolved by {name}." on a stale `If-Match` → 409 when not open or the run isn't waiting → 409 `registry_agent_disabled` for Re-plan. `AssessmentsView` gained `can_resolve`. The eval harness counts a waiting run as a specialists failure.
- **Web**: `WaitingForYouPill` (amber, clock) on the run panel's task card and the Overview's Agent run card; `DecisionActions` (Continue without / Re-plan, Re-plan disabled with "Enable the agent first" via `aria-describedby`); "Plan v{n}" as a `<details>` disclosure in the run header; a `waiting-run` Needs you row (rank of escalated Conflicts) linking to the Assessments tab; `workflows.run.waiting_for_human` added to the stream's progress events.

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test> uv run pytest` -- expected: all pass (known local-only: `test_user_search.py::test_matches_email`)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
