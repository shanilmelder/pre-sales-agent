---
title: 'Stories 5.8 + 5.9 (demo slice), with minimal 5.1–5.3: run the Engineering, PM and Security Agents in parallel'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '6b928a850bb866a1ead4f9b6221be02d6037b7b7'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-5-red-team-flags.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every judgement in the platform today comes from one model call. Stakeholders expect specialist agents — engineering, delivery and security — each assessing the Opportunity from its own angle, working at the same time, and stating a recommendation they can defend (FR-15, FR-16, FR-25).

**Approach:** A **Run assessment** button starts an assessment run with one task per specialist agent (Engineering, PM, Security). The tasks run in parallel; each agent reads the Opportunity's active Requirements and open Gaps and returns an Assessment — a recommendation, a confidence level with its basis, specific Findings citing Requirements, and effort per Requirement — which is validated and stored. The Assessments tab shows one section per agent above the Red Team.

## Boundaries & Constraints

**Always:**
- **Depends on:** 2.5 Part A (active Requirements), 4.3 (open Gaps), 6.5 (`assessments` module, Assessments tab, run-state patterns), 2.4 (gateway and contract), 2.2 Part A (jobs).
- **Parallel execution (decided: one run job, agents concurrent inside it):** starting a run enqueues one `assessments.run_assessment` job (background priority, `timeout_s` 900, `max_attempts` 2) that starts the three agent calls together (asyncio) and accepts each result in its own Unit of Work as it arrives; each task keeps its own status. A job attempt only re-runs tasks not yet `succeeded`. Retry of one failed task enqueues a one-task job. `PSA_MODEL_SLOTS` defaults to 3 for the demo (in `.env.example`, compose and the settings default); worker concurrency stays 1.
- **Run and tasks:** an assessment run has one task per agent (`engineering_agent`, `pm_agent`, `security_agent`). Run status `queued | running | succeeded | partially_failed | failed`; task status `queued | running | succeeded | failed` with `error_code` (`model_unavailable | model_timeout | output_invalid`). The run is `succeeded` when all tasks succeed, `partially_failed` when some do, `failed` when none do. While a run is queued or running, **Run assessment** returns 409 `assessment_in_progress`. A run stuck past its window reads as failed, as in 6.5.
- **Agents:** three new agents under `app/agents/` (`engineering_agent`, `pm_agent`, `security_agent`), each `AgentConfig(<id>, "0.1.0", prompt v1, profile chat)`, built like `red_team_agent`: active Requirements `R1…Rn` (with classification) and open Gaps `G1…Gn` (category, impact) in fenced data blocks with a per-call token.
  - Output in `extensions[<agent_id>]`: `recommendation` (`proceed | proceed_with_conditions | do_not_proceed`), `confidence` (`high | medium | low`), `confidence_basis` (1–500 chars), `findings: [{kind, severity, title, detail, requirements: ["R<n>"…]}]` (`kind` `risk | constraint | dependency | opportunity`; `severity` `low | medium | high | critical`; title 1–160, detail 1–800; at least one `R<n>` resolving to a Requirement still active at the version read), `effort: [{requirement: "R<n>", hours (0.5–2,000, 0.1 precision), basis (1–300)}]` (Engineering and PM required to cover every Requirement they consider in scope; Security may return none).
  - Prompts: Engineering — integrations, data, build complexity and build hours; PM — delivery phases, coordination, stakeholders, PM and testing hours; Security — authentication, data protection, compliance, hosting risks and security-work hours. Each asks for 3–10 specific Findings and `critical` only when the deal is likely to fail without action.
  - Invalid Findings or effort rows are dropped and counted; a missing or invalid recommendation/confidence makes the reply invalid. No valid Finding → the task retries once, then fails `output_invalid`.
- **Assessments:** each succeeded task stores a new Assessment for that agent (`version` = previous + 1 per agent; the previous becomes `superseded` and is hidden), with its Findings (+ Requirement links at their versions) and effort rows (+ Requirement link). A failed task leaves the agent's previous Assessment current.
- **Tables (grants as in 6.5: SELECT/INSERT, UPDATE only on status columns, no DELETE):** `assessments_runs`, `assessments_tasks`, `assessments_assessments` (`agent`, `version`, `run_id`, `status current|superseded`, `recommendation`, `confidence`, `confidence_basis`, `dropped_count`, `created_at`), `assessments_assessment_findings`, `assessments_assessment_finding_requirements`, `assessments_effort` (`assessment_id`, `requirement_id`, `requirement_version`, `hours numeric(10,1)`, `basis`).
- **API:** `GET /opportunities/{id}/assessments` (readers) returns `{run | null (latest, with its tasks), assessments: [per agent: current Assessment or null], can_start}`; Findings ordered critical → low then position, with Requirement chips (label and excerpt); effort rows in Requirement order with the per-agent total hours (server-calculated). `POST /opportunities/{id}/assessment-runs` (new action `assessments.assessment.start`, owner and collaborators except sales representatives) starts a run; 409 while one is running. `POST …/assessment-runs/{run_id}/tasks/{agent}/retry` re-runs one failed task of the latest run (same action), 409 unless that task is `failed`.
- **Trace:** `assessments.assessment_run.started` (actor the user, agent count), `assessments.assessment.completed` per task (actor `<agent_id>@0.1.0`; version, recommendation, confidence, counts), `assessments.assessment_run.completed` (status, counts). No Requirement, Gap or Finding text.
- **Web (Assessments tab):** a **Specialist Assessments** section above Red Team.
  - Header: **Run assessment** (hidden unless `can_start`), the latest run's status, and while queued or running a per-agent line ("Engineering Agent — Assessing…", "PM Agent — Done", "Security Agent — Failed: <reason>" with **Retry**), polling every 2 s, paused while hidden, stopping after 15 min with "reload".
  - One card per agent: name, "v{n}", recommendation pill (icon plus label), confidence with its basis, severity counts, Findings as 32px rows (severity pill, kind, title, Requirement count) and an effort table (Requirement label, hours, basis) with the total.
  - Selecting a Finding opens the shared inspector (detail and Requirement chips with excerpts); only one Finding across all sections (including Red Team) is selected at a time.
  - Empty: "No assessment yet. Run assessment to have the Engineering, PM and Security Agents review this Opportunity." Keyboard and axe as in the Red Team list. Read-only for sales representatives.
- **Privacy:** no Requirement, Gap or Finding text in logs or trace.

**Never:** No LangGraph or `app/orchestration` code, no Research Agent, no ToolGateway or web fetch, no Knowledge or Evidence chips, no pause/resume decisions, no budgets, no Cancel, no live run panel beyond the header lines (5B), no OpenTelemetry, no plan versions or input pins, no Red Team reading the Assessments, and no Estimate drafted from Assessments (8.3). These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | Owner presses Run assessment; fake agents return valid replies | Run `succeeded`; 3 Assessments v1 with Findings, effort and totals; trace events | N/A |
| Parallel | Fake gateway that records call windows | The three agent calls overlap in time | N/A |
| Partial | Security agent's gateway fails on both attempts | Run `partially_failed`; Security task `failed` `model_unavailable`; the other two stored | Retry offered for Security |
| Retry | Retry the failed Security task | Only Security runs; on success the run becomes `succeeded` | N/A |
| Bad rows | A Finding citing only `R99`; an effort row of 0 h | Dropped and counted; the rest stored | N/A |
| Invalid reply | No valid Finding twice | Task `failed` `output_invalid`; previous Assessment stays current | N/A |
| Re-run | Run again after a success | v2 per agent current, v1 superseded and hidden | N/A |
| Busy | POST while a run is queued or running | 409 `assessment_in_progress` | N/A |
| Who | Sales rep starts / reads | 403 / 200 | N/A |
| Privacy | Any run | No Requirement, Gap or Finding text in logs or trace | N/A |

</frozen-after-approval>

## Covers Stories

Called "slice 5A" while planning; "5B" in the Never list is now Stories 5.7 and 5.5 (demo slices).

| Story | What this slice builds | Left `[post-demo]` |
|-------|------------------------|--------------------|
| 5.1 Start a Workflow Run | A run with one task per agent, started from the Assessments tab; 409 while one is running | `workflows` module, `start_run` with idempotency keys, versioned plans, input pins |
| 5.2 Durable execution | One background job; the agents run concurrently (asyncio); per-task status; a job attempt re-runs only unfinished tasks | LangGraph, Postgres checkpointer, resume after restart without re-execution |
| 5.3 Assessment contract | Versioned Assessments per agent with recommendation, confidence, Findings citing Requirements, effort per Requirement; invalid rows dropped and counted | Evidence references, Unknowns via `gaps.register_unknown`, low/likely/high effort, catalogue lines |
| 5.8 Engineering and PM Agents | Both agents with v1 prompts, Findings and effort per Requirement | Effort per Integration Type and Work Package, timeline, role mix |
| 5.9 Security and Research Agents | Security Agent | Research Agent, research snapshots, full run with the ToolGateway (5.4) |

Not touched: 5.4 (ToolGateway), 5.6 (budgets), 5.10 (load test).

## Code Map

- `backend/app/modules/assessments/` (6.5) -- reuse and generalise:
  - `domain/reviews.py`: `RunStatus` :21, `IN_PROGRESS` :28, `RunErrorCode` :31, `validate_findings`/`FindingValidation[R, L]` :85-111 (generic; new categories and severities via a new domain module `domain/assessments.py`).
  - `application/review.py`: `queue_review` :100, `enqueue_review` :108 (lock, `fail_stale`, coalescing), `stale_after` :123, `accept_red_team_review` :207 (pattern for `accept_assessment`), error mapping :323, handler :346 with shielded final fail, `_start` input loading :407-466, `RED_TEAM_REVIEW_JOB` :510 (background, `timeout_s` 900, `max_attempts` 2).
  - `application/reviews.py` (`get_red_team` :169, `start_review` :179), `api/routes.py:38,47`, `application/public.py`, `adapters/models.py` (6.5 tables :25-126). Leave the Red Team tables and behaviour unchanged; add new tables.
- Agents: copy `backend/app/agents/red_team_agent/` (`AGENT_ID`/`SEMVER`/`PROMPT_VERSION` :30-32, `config` :41, fenced blocks :95-130, one `complete_structured` call :154-174, `schema.py` with enum-in-JSON-schema strings). `agents/contract.py` (`AgentResult` :72, `AgentConfig` :107, `actor_id` :127). No agent registry exists; trace names derive from the id (`opportunities/application/trace.py:33`).
- Jobs and gateway: `platform/jobs/registry.py:83-131` (`register`, `JobType`, priorities `interactive|background` :42); `platform/config.py:70` (`PSA_WORKER_CONCURRENCY`, capped at 1), `:111` (`PSA_MODEL_SLOTS`); `model_gateway/gateway.py:107` + `semaphore.py`; `main_worker.py`; `compose.yaml:81` (worker service). Raise the `PSA_MODEL_SLOTS` default to 3 (decided).
- Inputs: `intake.active_requirement_snapshots` (`intake/application/requirement_refs.py:17`), `gaps.open_gap_summaries` (`gaps/application/gap_refs.py:16`).
- Identity: `identity/actions.py:31` (`RED_TEAM_START` pattern), `domain/policy.py:98,112,131,145`; update `tests/test_authorize.py`.
- Trace: `platform/trace/catalogue.py:359-377` pattern; add labels to `web/src/lib/trace.ts` `EVENT_LABELS` and the agent subject to `SUBJECTS`.
- Migration `0017_assessments_specialists`, revising `0016_gaps_question_approval`. Register the job module in `main_worker._JOB_MODULES`; import-linter contract at `backend/pyproject.toml:165-186` unchanged (same module).
- Web: `app/opportunities/[id]/assessments.tsx` (server component; add the section above `RedTeamSection`), `app/opportunities/data.ts:169` (`getRedTeam` pattern), `actions.ts:644` (`startRedTeamReview` pattern); `components/opportunities/red-team-list.tsx` (`RedTeamHeader` :177, `RedTeamSection` :264, polling :333-370), `red-team-inspector.tsx`, `severity-pill.tsx`, `lib/red-team.ts:106,109`. `RightPaneContent` (`components/shell/shell-context.tsx:183`) is one shared slot: lift Finding selection so only one section owns it. Regenerate `schema.d.ts` from a local uvicorn.
- Leave `app/orchestration/` empty (reserved for LangGraph).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/agents/{engineering,pm,security}_agent/**` -- agents, schemas, v1 prompts
- [x] `backend/app/modules/assessments/**`, identity, catalogue, migration 0017, worker wiring, `PSA_MODEL_SLOTS` 3 -- run, tasks, accept, read model, routes
- [x] `backend/tests/test_assessments_specialists*.py` -- every matrix row (fake gateway, Postgres), grants
- [x] Web: `schema.d.ts`, actions, Specialist Assessments section, cards, inspector sharing, trace labels, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity (cloud profile, worker running), when the presales engineer presses Run assessment, then the three agents work at the same time and the Assessments tab shows each agent's recommendation, confidence with basis, specific Findings citing Requirements, and effort per Requirement.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | VG: no test that a Requirement edited mid-run stops resolving | medium | Pre-verified gap; Red Team has the sibling test | patch: `test_a_requirement_changed_after_the_read_does_not_resolve` |
| 2 | VG: "Superseded" chip label untested | medium | Pre-verified gap | patch: `test_a_superseded_requirement_reads_as_superseded` (both sized Requirements go inactive on re-extraction) |
| 3 | VG: retry of a lost run untested | medium | Pre-verified gap; `retry_task` relies on `fail_stale` before the 409 check | patch: `test_retry_fails_a_lost_run_first` |
| 4 | VG: late acceptance after the task stopped running untested | medium | Pre-verified gap; the guard protects the newer current Assessment | patch: `test_an_older_run_accepted_after_a_newer_one_writes_nothing` |
| 5 | VG/edge: a raising failure-mark in `_task` escapes `gather` and abandons siblings mid-call | low | `_task`'s final-attempt UoW is unguarded; needs a DB failure, fix is one argument | patch: `gather(..., return_exceptions=True)` |
| 6 | blind: Security prompt list is broken ("and - hosting … - and the hours") | low | `security_agent/prompts/v1.md` list items | patch: list fixed |
| 7 | blind/edge: 900 s timeout too short if calls serialise (slots < 3, or `OLLAMA_NUM_PARALLEL` < 3) | low | Worst case only (3 × 3 × 120 s); `.env` doesn't set `PSA_MODEL_SLOTS`, so 3 applies | reject (README documents the default) |
| 8 | blind: a retried task re-reads Requirements, so one run can mix inputs | low | True, but input pins are excluded by the intent's Never list | reject (out of scope: no input pins) |
| 9 | blind: a run with no active Requirements succeeds and leaves old Assessments current | low | Rare (no Requirements); fix adds behaviour | reject |
| 10 | blind: cards don't show which run an Assessment came from | low | Spec asks only for "v{n}"; display-only addition | reject |
| 11 | blind: no "edited since assessed" marker on chips | low | Not asked for; new UI | reject |
| 12 | blind: `total_hours` includes rows whose Requirement is now inactive | low | True after re-extraction; rows stay visible as "Superseded" | reject |
| 13 | blind: UI polling stops at 15 min, stale window is ~39 min | low | Same pattern as 6.5; the read model reports the lost run as failed | reject |
| 14 | blind: retry trace event lacks the agent | low | Spec defines the payload as agent count | reject |
| 15 | blind: `dropped_count` merges Findings and effort | false | Spec defines one `dropped_count` column | reject |
| 16 | blind: PM prompt lacks "leave out Requirements with no work" | false | PM sizes PM and testing work, which applies to every Requirement in scope | reject |
| 17 | blind: `_responses` variant-key encoding is obscure | low | Works; refactor only | reject |
| 18 | blind: `insert_assessment` would fail on Findings with no links | false | `validate_assessment_finding` guarantees at least one Requirement | reject |
| 19 | blind: `retryAssessmentTask` callable with an undefined run id | false | Retry renders only when a run exists | reject |
| 20 | blind: spec file left unfinished | false | Sections fill during review; status is now `in-review` | reject |
| 21 | edge: app clock vs database clock in the lost-run check | low | Same pattern as 6.5; local Docker on one machine | reject |
| 22 | edge: 409 on start/retry gives no visible feedback | low | The handler re-reads and shows the stored run, as in Red Team | reject |
| 23 | edge: database errors in acceptance read as `model_unavailable` | low | Same mapping as 6.5; rare | reject |
| 24 | edge: non-numeric `hours` fails the whole reply | low | Constrained decoding enforces a number; gateway retries | reject |
| 25 | edge: hours are rounded before the bounds check (0.45 → 0.5) | false | Deliberate and tested (`test_hours_are_rounded_to_a_tenth_and_bounded`); consistent with 0.1 precision | reject |
| 26 | edge: empty effort from Engineering/PM is accepted | false | The spec says "every Requirement they consider in scope", which is the agent's judgement and can't be enforced | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped (known local-only failure: `test_user_search.py::test_matches_email`, deferred)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
