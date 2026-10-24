---
title: 'Story 6.4: Critic Review'
type: 'feature'
created: '2026-10-23'
status: 'done'
route: 'dispatch'
baseline_commit: '6a38bd5e8360caffdf029249f1bc521a0197b6d4'
baseline_tree: '2e8dc8d6b0f9c112eff3602894180024cbf4ca40' # working-tree snapshot incl. uncommitted 5.4/5.5 work; diff against this
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-5-red-team-flags.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing checks the combined specialist Assessments of a run. Requirements no agent sized or discussed, claims with no basis, timelines that don't add up and missing dependencies all reach the Estimate unnoticed (FR-27).

**Approach:**
- Add `critic_agent`, which every assessment run plans as a `critic_review` task.
- The task runs after all specialist tasks have ended.
- Code computes the uncovered Requirements first. The agent then reviews the run's Assessments.
- `assessments.accept_critic_review` stores a versioned Critic Review whose Findings cite specialist Findings at their Assessment version, or Requirements.
- Contradictions between Assessments become Conflicts (`detected_by = critic`), not Findings.

## Boundaries & Constraints

**Always:**
- **Plan:** `workflows.queue_run` adds one `critic_agent` task, pinned to its current config version, with a new `after` list holding the specialist task ids.
  - A task is ready when everything in `requires` succeeded **and** everything in `after` has ended, whatever the outcome.
  - Cancel, pause and escalation (5.5) apply to the Critic task like any other.
  - `finish_run` still runs once every task has ended.
- **Inputs (prepare):**
  - The Assessments accepted in this run, with Findings labelled `F1…Fn` (agent role, Assessment version, kind, severity, title, detail, cited `R<n>`) and effort rows.
  - The active Requirements `R1…Rn`.
  - `uncovered`: the active Requirements that no Finding and no effort row of those Assessments cites.
  - All of this goes in fenced data blocks (`platform/prompt_data.py`).
  - If no specialist Assessment was accepted in this run, there is no model call and no Review, and the task succeeds.
- **Output:** `extensions["critic_agent"]`
  - `findings: [{category, severity, title, argument, findings: ["F<n>"], requirements: ["R<n>"]}]`
  - `category` is one of `coverage | unsupported_claim | timeline | dependency | risk_coverage`.
  - `severity` is one of `low | medium | high | critical`.
  - `contradictions: [{type, severity, summary, positions: [{finding: "F<n>", stance}]}]`
  - The prompt asks for one `coverage` Finding per uncovered Requirement, and for specific copy that names agents by role.
- **Accept (one Unit of Work):**
  - **Finding rules:** a known category and severity, a title of 1–160 characters, an argument of 1–800 characters, and at least one resolving `F<n>` or `R<n>`. A `coverage` Finding must cite an uncovered `R<n>`. Invalid Findings are dropped and counted.
  - **Coverage backstop:** each uncovered Requirement that no valid coverage Finding cites gets a code-written `coverage` Finding: `medium`, "No specialist Assessment covers R<n>".
  - **Contradictions:** validated with the 6.2 semantic rules (at least two Findings, mandatory claims discarded, duplicate fingerprints dropped), then raised through `conflicts.raise_conflict` with `detected_by = critic` and actor `critic_agent@0.1.0`. They are never stored as Findings.
  - **Versioning:** each accepted review is a new Critic Review (`kind = critic`, `version` = the previous one + 1, `run_id`). The previous Critic Review becomes `superseded`.
  - **Failure:** an unparseable reply fails the task through the executor's retry, like the specialists.
- **Registry and tools:**
  - Seed `critic_agent` with prompt v1, an extension schema and a read-only config granting a new catalogue tool, `assessments.run.read`.
  - That tool returns the run's accepted Assessments and Findings with their versions.
- **API:** `GET /opportunities/{id}/critic` (readers) returns `{review | null}`, in the same view shape as the Red Team: Findings ordered critical → low, with counts per severity, Requirement chips and cited-Finding chips (agent role, Assessment version, title).
- **Trace:** `assessments.critic_review.completed`, carrying the version and counts only (Findings by severity, dropped, backstopped, conflicts raised).
- **Privacy:** no Requirement, Finding or argument text in logs or trace.
- **Web (decided: fold in like the Red Team):**
  - The Critic gets a fifth result card on the Assessments tab ("Critic v2", severity counts, "Critic reviewing" while its task runs).
  - Its Findings join the one Findings table with Raised by "Critic".
  - Critical Findings use the blocker colour and icon (UX-DR5).
  - The row inspector shows the argument, the cited specialist Findings (role, Assessment version, title) and the Requirement chips.
  - Read-only.
- **Eval (decided: include now):**
  - At least 3 fixtures in `evals/critic/*.yaml`, each seeding an uncovered Requirement, an unsupported claim and an inconsistent timeline.
  - `make eval-critic` scores the agent's reply before the backstop, records the share of seeded defects found, and exits non-zero unless the uncovered Requirement is reported in every fixture.
  - The harness report's "Critic: not available" placeholder becomes the real stage.
  - Tests use a fake gateway; the live baseline is a manual run.

**Never:**
- Moving the Red Team into the plan or changing its trigger.
- Resolve, override or Evidence actions on Findings, or submission blocking (6.6).
- Wiring the ToolGateway into agent calls (5.4 follow-up). The executor reads through the public query, like the specialists do.
- Adding the Critic to `assessments.AGENTS`, or to effort comparison or the Estimate build.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plan | A run is queued | 4 tasks; Critic `after` = the 3 specialist ids | N/A |
| Specialist failed | Security fails, the others succeed | Critic runs on 2 Assessments; run `partially_failed` | N/A |
| None accepted | All specialists fail or are skipped | Critic task succeeds, no model call, no Review | N/A |
| Happy | Fake agent returns 4 valid Findings, one citing `F2`, plus 1 contradiction | Review v1 with 4 Findings and target links at their versions; 1 Conflict `detected_by=critic`; one trace event | N/A |
| Uncovered missed | R5 uncovered, and the agent does not report it | Backstop coverage Finding for R5 | N/A |
| Bad refs | Cites only `F99`/`R99`, or coverage on a covered R | Dropped; `dropped_count` counts it | N/A |
| Re-run | A second run accepts | Critic v2 `current`, v1 `superseded` | N/A |
| Who | Sales rep GETs | 200 | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/` -- mirror the Red Team:
  - `domain/reviews.py`: `ReviewKind` :12 (add `CRITIC`), `FindingCandidate` :87, `validate_findings` :165, `severity_rank`.
  - `application/review.py`: `accept_red_team_review` :208, `candidates` :194.
  - `application/reviews.py`: `review_view` :114, `get_red_team` :175.
  - `adapters/repository.py`: `insert_review` :247, `supersede_reviews` :230, `current_review(kind)` :302, `findings_of` :319.
  - `adapters/models.py`: the `kind` CHECK :71, the Findings `category` CHECK :93, `assessments_assessment_findings` :207, `assessments_effort` :261.
- `backend/app/modules/assessments/application/assessment.py` -- `current_finding_snapshots` :301 and `current_assessment_snapshots` :271. Add run-scoped variants (filter on `assessments_assessments.run_id`) and export them from `public.py`. These back both the inputs and the `assessments.run.read` tool.
- `backend/app/agents/red_team_agent/` and `agents/specialist/agent.py` -- copy for `agents/critic_agent/` (`agent.py`, `schema.py`, `prompts/v1.md`). Update `agents/manifest.json`.
- `backend/app/orchestration/executors.py` -- `SpecialistExecutor` :56 is the prepare/run/accept pattern. Add `CriticExecutor` and register it in the executor map :121.
- `backend/app/modules/workflows/` -- `application/runs.py:176 queue_run` (add the Critic task), `domain/runs.py:87 readiness` (add `after`), `adapters/models.py:116` (`requires`; add the `after` column), the plan version payload, and the graph edges in `orchestration/graph.py:184 build_graph`.
- `backend/app/modules/conflicts/application/semantic.py` and `domain/semantic.py` -- `validate_semantic`/`ValidSemantic` and the candidate→`raise_conflict` path in `accept_semantic_conflicts` :210. Expose a public `raise_critic_conflicts(uow, *, opportunity_id, run_id, candidates, actor)` that reuses them. `raise_conflict` is at `conflicts.py:120`.
- `backend/app/platform/tool_gateway/` -- catalogue :13 (add `assessments.run.read`, READ). Registry validation is at `registry/domain/registry.py:136`.
- Migration `0039_critic_review`, revising `0038_tool_gateway`:
  - Widen `kind` to `('red_team','critic')`; add nullable `assessments_reviews.run_id`; widen the `category` CHECK.
  - New `assessments_finding_targets` (`finding_id`, `assessment_finding_id`, `assessment_id`, `assessment_version`), SELECT/INSERT only.
  - `workflows_tasks.after uuid[] default '{}'`.
  - Seed the `critic_agent` registry rows the way `20261020_0033_conflict_agent.py` does.
- Wiring: `platform/trace/catalogue.py` (near :670), `main_api.py`/routes, and the import-linter in `backend/pyproject.toml`.
- Web: `web/src/app/opportunities/[id]/assessments.tsx:25`, `components/opportunities/specialist-assessments.tsx` (`RedTeamResultCard` :465, `FindingsTable` :198), `red-team-inspector.tsx`, `lib/red-team.ts`. Add `lib/critic.ts`. Regenerate `schema.d.ts` from a local uvicorn.
- Evals: `backend/app/evals/report.py:17,62`, `harness.py:13`, `scoring.py:28`, `Makefile` (`eval-conflicts` is the pattern), `backend/tests/test_evals_conflicts.py`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261023_0039_critic_review.py` + models -- schema, grants, registry seed
- [x] `backend/app/agents/critic_agent/**` -- agent, schema, prompt v1, manifest
- [x] `backend/app/modules/assessments/**` -- run-scoped snapshots, coverage computation, `accept_critic_review`, the read view, `GET /critic`, trace, tool registration
- [x] `backend/app/modules/conflicts/**` -- `raise_critic_conflicts`
- [x] `backend/app/modules/workflows/**`, `orchestration/**` -- the `after` readiness, the Critic task in the plan, `CriticExecutor`
- [x] `backend/tests/test_assessments_critic*.py`, `test_workflows*` -- every matrix row (fake gateway, Postgres), `after` readiness unit tests, grants
- [x] Web -- `schema.d.ts`, `lib/critic.ts`, the Critic result card, table rows and inspector, tests with axe
- [x] `evals/critic/*.yaml`, `backend/app/evals/**`, `Makefile`, `backend/tests/test_evals_critic.py` -- fixtures, scoring, the report stage, the `eval-critic` target

**Acceptance Criteria:**
- Given a demo Opportunity with Requirements, when an assessment run finishes with the worker running, then the Assessments tab shows a Critic Review version with severity-ranked Findings citing specialist Findings or Requirements, and critical ones in the blocker colour and icon.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Plan and readiness:** `workflows_tasks.after` (uuid[]); `readiness(requires, statuses, after)` is `waiting` while any `after` task is queued or running. `plan_of` hands the graph `requires + after` as one dependency list (a waiting edge), so the node tells them apart through `node_task`. Plan version payloads carry `after`. A new `TaskAgent` enum (`engineering_agent | pm_agent | security_agent | critic_agent`) types run tasks, plan tasks, decisions and the retry route (the Critic's failed task can be retried); `assessments.AGENTS` is unchanged.
- **Run status:** still derived from every task, except that a run where only the Critic succeeded is `failed` (no Assessment came out of it). The Estimate build after `finish_run`/`cancel` counts specialist successes only.
- **Inputs:** `assessments.critic_inputs` (pure) over `intake.active_requirement_snapshots` and `run_assessment_reads` (the newest Assessment per agent with `run_id` = the run); uncovered = active Requirements whose id no Finding or effort row of those Assessments cites. Effort rows go in one `EFFORT` block per Assessment, the uncovered labels in one `UNCOVERED` block.
- **Accept:** Findings with no resolving label, a coverage Finding without an uncovered `R<n>`, or a bad enum/length are dropped and counted (`dropped_count`); an all-dropped or empty reply still stores a Review (only an unparseable reply raises `ModelOutputInvalidError`). Backstop Findings come after the agent's, in Requirement order. Requirement labels resolve only to Requirements still active at the version read.
- **Contradictions:** `conflicts.raise_critic_conflicts` validates with `validate_semantic` (current-Assessment check on, no rule-key dedupe) and raises with fingerprint `critic:<type>:<ids>` in a detection pass one past the run's latest, not recorded in `conflicts_detections` (so the semantic job's staleness is unchanged); they are never auto-resolved by the rules or the Conflict Agent.
- **Trace:** `assessments.critic_review.completed` `{version, finding_count, critical/high/medium/low_count, dropped_count, backstopped_count, conflict_count, superseded_count}`, subject `assessments.review` at the version, `workflow_run_id` = the run.
- **Tool:** `assessments.run.read` returns `RunAssessment`s for `ctx.run_id`; denied `out_of_scope` without a run or for another `run_id` argument. The executor reads through `load_critic_inputs`, not the gateway.
- **Web:** the Critic task card (ScanSearch icon), a fifth result card ("Critic" + "v2" + severity counts, "Critic reviewing" while its task is `running`), Critic rows in the one Findings table (Raised by "Critic", a cited-Findings count chip) and `CriticInspector`. The Critic Review is re-read (`loadCritic`) with every Assessments re-read.
- **Eval:** `app/evals/critic.py`, three fixtures in `evals/critic/`, `make eval-critic` (exit 1 unless every fixture's uncovered Requirement is reported; scored before the backstop). The harness report's Critic placeholder is now a stage (`critic` in `stages.run`, a per-Opportunity and summed Critic summary, no bar); a failed Critic task is its own stage failure and zeroes no metric.

- **Migration renumbered on merging main (2026-10-24):** Story 5.4 merged as `0039_tool_gateway` (after 4.2's `0038_mandatory_gaps`), so this branch's chain is now `0039_tool_gateway` → `0040_workflows_decisions` (5.5, `20261024_0040_workflows_decisions.py`) → `0041_critic_review` (`20261024_0041_critic_review.py`); the branch's own `0038_tool_gateway` was dropped (identical upgrade to main's).

- **Rebuilt on the finished Story 5.5 (2026-10-24):** the branch first carried an earlier, unfinished 5.5 attempt. After 5.5 merged (PR #81), the 6.4 delta was re-applied onto main and ported to 5.5's final API: `after` on `PlanTask` and its plan-version JSON, `TaskAgent` for decisions and `openDecision`, the Critic-only-finish rule next to 5.5's chosen-skip run status. A 5.5 test now counts the Critic's task (4 tasks, 3 succeeded). The chain stays `0039_tool_gateway` → `0040_workflows_decisions` → `0041_critic_review`.

## Spec Change Log

- **Loop 1 (review triage #1–#3):** review found that retries and re-runs were unspecified: a specialist retry left the Critic Review stale, a Critic-only retry rebuilt the Estimate and re-queued the Red Team, and Critic Conflicts were never retired. Amended: added "Re-run rules" to Design Notes. Known-bad state avoided: stale coverage backstops after a retry, needless Estimate versions, permanently open Critic Conflicts. User chose to patch in place instead of revert/re-derive (a concurrent Story 5.4 session shares files in the tree). KEEP: everything else in the implementation — the plan `after` readiness, `TaskAgent`, accept/backstop rules, the Conflicts path via `validate_semantic`, migration 0039, the web card/table/inspector, and the eval.

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge+verify | Retrying a failed specialist leaves the Critic Review stale (Critic task not re-run) | medium | bad_spec | `retry_task` (assessment_runs.py ~:302) re-queues only the specialist; `test_a_failing_agent_leaves_the_run_partially_failed…` asserts the Critic is not re-run; a backstop "No specialist covers R<n>" survives a retry that covers it. Spec silent on retries. |
| 2 | verify | Retrying only the Critic rebuilds the Estimate (new draft version, Red Team re-queued, rules re-run) | medium | bad_spec | `finish_run` (runs.py :412) builds whenever `_specialists_succeeded`; `build_from_assessments` always stores a version when lines exist (from_assessments.py :68). Spec silent on what a Critic-only finish does. |
| 3 | edge | Critic Conflicts are never auto-resolved; with Finding-id fingerprints they can never be re-raised, so they stay open forever | medium | bad_spec | `raise_critic_conflicts` (conflicts/application/critic.py) only raises; nothing resolves stale `detected_by=critic` Conflicts (semantic does for its own). Epic: "a re-run auto-resolves Conflicts that no longer hold"; spec didn't carry it over. |
| 4 | blind+edge | Run `partially_failed` when only the Critic fails | low | reject | A failed Critic task is a failed part of the run with its own Retry; status is truthful. |
| 5 | blind+edge | Disabled Critic escalates every run | false | reject | Frozen intent: "Cancel, pause and escalation (5.5) apply to the Critic task like any other." |
| 6 | blind+edge | Older run's Critic Review shown when the latest Critic failed/made no call | low | reject | The failed Critic task card with Retry shows beside it; flagging staleness adds a branch for a rare state. |
| 7 | edge | Contradictions dropped when an Assessment is superseded mid-run | low | reject | Needs a newer run to accept between this Critic's prepare and accept; counted in the log. |
| 8 | edge | Duplicate coverage Findings for one Requirement | low | reject | Prompt-quality matter; dedupe adds a rule the intent does not state. |
| 9 | edge | Harness: failed run with no task rows records no specialists failure | low | reject | A run is always planned with tasks; unreachable in practice. |
| 10 | edge | Harness: Critic failure hides an unrelated dead specialists job | low | reject | Needs two independent failures in one eval run; fix adds a branch. |
| 11 | blind+edge | Eval `_effort` accepts negative/NaN hours | low | reject | Fixtures are committed by developers and parse-tested; guard is extra branches. |
| 12 | blind+edge | Downgrade leaves Critic entries in plan-version JSON and critic Conflicts | low | reject | Downgrades are a dev-only rarity; fix is a data rewrite. |
| 13 | edge | Trace tab has no label for `assessments.critic_review.completed` | low | patch | `web/src/lib/trace.ts` :70 has the Red Team label only. |
| 14 | blind+edge | "Critic Review could not be loaded" stays after a later successful re-read | low | patch | `specialist-assessments.tsx` :1620 renders from `criticInitial` only. |
| 15 | blind+edge | `CRITIC_REVIEWING` comment says queued or running; code shows running only | low | patch | `lib/critic.ts` comment vs :1321 `status === "running"`; spec says "while its task runs" — fix the comment. |
| 16 | blind | `CriticOutput.findings` required; a contradictions-only reply fails the task | low | patch | schema.py :82 has no default, unlike `contradictions` :83; one-line direct fix. |
| 17 | blind | Stale docstrings: `critic.evaluate` eval note; `loadRedTeam` JSDoc orphaned above `loadCritic` | low | patch | Direct comment corrections. |
| 18 | blind | Agent task grids are 3 columns; the 4th (Critic) card wraps alone | low | patch | `specialist-assessments.tsx` :852 `md:grid-cols-3`, `overview-summary.tsx` :764 `lg:grid-cols-3`. |
| 19 | blind | Overview "Needs you" ignores critical Critic Findings | low | reject | Blocking/attention for Findings is 6.6; adds a branch. |
| 20 | blind | `loadCritic` re-read on every poll tick | low | reject | One small GET per 2 s poll while assessing; fix adds status tracking. |
| 21 | blind | `Case.seeded` hard-codes one claim and one timeline defect per case | low | reject | Every fixture seeds exactly one of each, as the AC describes. |
| 22 | blind | "Critic" (web) vs "Critic Agent" (registry/decisions) naming | low | reject | Mirrors Red Team ("Red Team" in UI, registry name elsewhere). |
| 23 | blind | `assessments.run.read` registered but unused | false | reject | Frozen intent: wiring the gateway is out of scope; the tool and grant are required by the AC. |
| 24 | blind | Diff contains 5.4/5.5 work | false | reject | Concurrent 5.4 session in the same checkout and pre-existing uncommitted 5.5 work (user chose to branch off it); handled at commit time. |
| 25 | verify | Harness `_failures` Critic-task handling untested | medium | patch | Pre-verified gap: no test drives `_failures` with a failed `critic_agent` task. |
| 26 | verify | Accept-time "Requirement no longer active" filter untested end to end | low | patch | Pre-verified gap: only the pure domain test covers it. |
| 27 | verify | No backend test retries the Critic's own task via the route | medium | patch | Pre-verified gap: route now takes `TaskAgent`; nothing posts `critic_agent/retry`. |

## Design Notes

**Re-run rules (added after review, loop 1):**
- **Specialist retry re-runs the Critic:** a successful requeue of a failed specialist task also re-queues every ended task whose `after` contains it (the Critic), so the Critic reviews the run again once the retried task ends and writes a new Critic Review version.
- **A Critic-only finish doesn't rebuild:** when a run finishes again and only the Critic's task ran since the previous finish (no specialist task changed), `finish_run` does not build an Estimate Version or re-run Conflict detection; it only settles the run status.
- **Stale Critic Conflicts resolve as gone:** each Critic acceptance resolves, as gone with a specific reason, every unresolved `detected_by = critic` Conflict of the Opportunity that this pass did not raise, the way semantic detection retires its own.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
