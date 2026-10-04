---
title: 'Story 6.5 (demo scope): Red Team Review flags risky Requirements and Estimate lines'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '91c1f12c02babe62607c4bd3172f53fe7636fc30'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-1-draft-estimate.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing in the platform pushes back on optimism. Estimates come in 20–50% low because hard integrations, incomplete Requirements and overstated capabilities go unchallenged until delivery (FR-28).

**Approach:**
- Add the `assessments` module and the `red_team_agent`.
- After each draft Estimate Version is accepted, an `assessments.red_team_review` job asks the agent to argue the Opportunity is harder than it looks.
- `assessments.accept_red_team_review` stores a Red Team Review with specific, severity-ranked Findings, each citing the Requirements and Estimate lines it challenges.
- The Findings show in a Red Team section of the Assessments tab, read-only.

## Boundaries & Constraints

**Always:**
- **Depends on:** Story 2.5 Part A (active Requirements), 4.3 (open Gaps), 8.1 (Estimate Versions and lines), 2.4 (gateway and contract), 2.2 Part A (jobs).
- **Trigger (decided: after the Estimate draft):**
  - `estimates.accept_draft` enqueues `assessments.red_team_review` for the Opportunity in its Unit of Work, through `assessments.application.public.enqueue_review`.
  - Every re-draft is reviewed again.
- **Placement (decided: the Assessments tab):**
  - Route the existing `assessments` tab to a page with one Red Team section.
  - No badges on Requirement rows.
- **Agent:**
  - `app/agents/red_team_agent/` is `AgentConfig("red_team_agent", "0.1.0", prompt v1, profile chat)`.
  - The inputs go in as delimited data blocks with a per-call fence token, as in `estimating_agent`: active Requirements `R1…Rn` (with classification) and open Gaps `G1…Gn` (category, impact).
  - The output goes in `extensions["red_team_agent"]`: `findings: [{category, severity, title, argument, requirements: ["R<n>"…], lines: ["L<n>"…]}]`. `lines` is optional.
  - `category` is one of `integration_harder | requirement_incomplete | capability_overstated | hidden_dependency`.
  - `severity` is one of `low | medium | high | critical`.
  - The prompt asks for 3–12 Findings, each specific ("ERP custom fields — no evidence the connector supports them", never "Potential issue detected"), and `critical` only when the deal is likely to overrun or fail without action.
- **Accept (one Unit of Work after the model call):**
  - **Finding rules:** a known category and severity; a title of 1–160 characters; an argument of 1–800 characters; at least one `R<n>` that resolves to a Requirement still active at the version read. `L<n>` labels that don't resolve to a line of the version reviewed are ignored.
  - Invalid Findings are dropped and counted.
  - If none is valid, the job retries once, then fails with `output_invalid`.
  - Each accepted review is a new Red Team Review (`version` = the previous one + 1). The previous one becomes `superseded` and is hidden.
- **Run states:** `queued | running | succeeded | failed`, with `error_code` (`model_unavailable | model_timeout | output_invalid`).
  - The job runs at `background` priority, with `timeout_s` 900 and `max_attempts` 2.
  - If a review is still unclaimed for that Opportunity, no second one is added.
  - A run stuck past its window reads as failed, like the 8.1 drafts.
- **Tables (grants as in 8.1, no DELETE):**
  - `assessments_red_team_runs`
  - `assessments_reviews` (`id`, `opportunity_id`, `kind` = `red_team`, `version`, `estimate_version_id`, `status` `current|superseded`, `dropped_count`, `created_at`)
  - `assessments_findings` (`id`, `review_id`, `position`, `category`, `severity`, `title`, `argument`)
  - `assessments_finding_requirements` (`finding_id`, `requirement_id`, `requirement_version`)
  - `assessments_finding_lines` (`finding_id`, `line_id`)
- **API:**
  - `GET /opportunities/{id}/red-team` (readers) returns `{review | null, run | null, can_start}`. The review's Findings are ordered critical → low, then by position, with their Requirement chips (label and excerpt), their Estimate line chips (title and effort), and counts per severity.
  - `POST /opportunities/{id}/red-team-reviews` (new action `assessments.red_team.start`, owner and collaborators except sales representatives) starts a review again. Returns 409 while one is running.
- **Trace:** `assessments.red_team_review.completed` with the version and counts only. Actor `red_team_agent@0.1.0`.
- **Web:**
  - Findings are dense 32px rows: a severity pill (icon plus label, with blocker red only for `critical` and gap amber for `high`), the category, the specific title, and Requirement and line count chips.
  - The selected row opens an inspector with the argument, Requirement chips with excerpts, and the challenged Estimate lines.
  - The header shows "Red Team v2", the severity counts, "Red Team reviewing" with a running dot while queued or running (polling every 2 s, paused while hidden, stopping after 15 min with "reload"), and "Red Team review failed: <reason>" with Retry.
  - Empty: "The Red Team reviews the Opportunity after the Estimate is drafted."
  - The keyboard model (`j`/`k`, arrows, Enter) and axe checks are as in the Gaps tab.
  - Read-only for everyone.
- **Privacy:** no Requirement, Gap or Finding text in logs or trace.

**Never:**
- No Critic, no Conflicts or `conflicts` module, no Unknowns (`gaps.register_unknown`), and no Knowledge Sources or `injection_suspected` flag.
- No resolving, overriding or Evidence-supplying of Findings, and no submission blocking (6.6). No eval harness (`make eval-red-team`).
- No Specialist Assessments (Epic 5). The Red Team reviews Requirements, Gaps and the Estimate directly.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Auto-queue | A draft Estimate is accepted | One review job queued in the same transaction | N/A |
| Happy | Fake agent returns 5 valid Findings, two citing lines | Review v1 with 5 Findings ordered critical→low, Requirement links at their versions and line links; one trace event | N/A |
| Bad line | A Finding citing `R2` and `L99` | Kept, with no line link | N/A |
| Bad label | A Finding citing only `R99` | Dropped; `dropped_count` 1 | N/A |
| Bad enum | Unknown category or severity | Dropped | N/A |
| All invalid | Every Finding invalid, twice | `failed`, `output_invalid`; no review written | Retry offered |
| Re-review | A re-draft is accepted | v2 `current`, v1 `superseded`; the UI shows v2 | N/A |
| Who | Sales rep POSTs a retry / reads | 403 / 200 | N/A |
| Privacy | Any run | No Requirement, Gap or Finding text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/` -- the pattern to mirror end to end:
  - `application/detection.py`: `enqueue_detection`, `fail_stale`, `accept_gap_detection`, `detect_gaps`, `_start`, `_detect`.
  - Also the `adapters/`, `domain/`, `api/routes.py` and `public.py` layers.
- `backend/app/agents/estimating_agent/agent.py` -- fenced `R<n>`/`G<n>` data blocks (`data_blocks`), `config`, `run`. Copy this for `red_team_agent`.
- `backend/app/modules/estimates/application/draft.py` -- the `accept_draft` hook site (next to `enqueue_proposals`, ~:275). Call `assessments.application.public.enqueue_review(uow, opportunity_id)` there. Use a function-level import if assessments importing the estimates public module would be circular (as `gaps/application/detection.py` ~:299 does).
- `backend/app/modules/intake/application/public.py` -- `active_requirement_snapshots`, `requirement_version_texts` (the chip excerpts).
- `backend/app/modules/gaps/application/public.py` -- `open_gap_summaries`.
- `backend/app/modules/estimates/application/public.py` -- add a public read of the current draft version's id and its lines (id, section, title, effort).
- Wiring:
  - the modules list in `backend/app/modules/__init__.py`;
  - `main_api.py` (router);
  - `main_worker._JOB_MODULES`;
  - `migrations/env.py`;
  - `identity/actions.py` + `domain/policy.py` (`RED_TEAM_START`, sales reps excluded like `ESTIMATE_DRAFT_START`);
  - `platform/errors.py` (`RedTeamReviewInProgressError`);
  - `platform/trace/catalogue.py`;
  - `backend/pyproject.toml` import-linter (a new `assessments` contract, and `assessments` added to the other modules' forbidden lists).
- Migration `0014_assessments_red_team`, revising `0013_estimates_assumptions`.
- Web:
  - `web/src/lib/workspace.ts` (the `assessments` tab already exists);
  - `web/src/app/opportunities/[id]/[tab]/page.tsx` (route it);
  - new `[id]/assessments.tsx`, `components/opportunities/red-team-list.tsx` + inspector, and `lib/red-team.ts`;
  - reuse the `gaps-list.tsx` polling, keyboard and inspector patterns and `status-pill.tsx`;
  - tokens `--color-blocker`/`--color-gap` in `globals.css`.

  Regenerate `schema.d.ts` from a local uvicorn, not the Docker `api`.
- `backend/app/agents/contract.py` -- `Finding`/`Risk` exist but don't fit the shape. Don't change them; use `extensions`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/assessments/**`, `app/agents/red_team_agent/**`, the trigger hook, identity, errors, catalogue, migration 0014, wiring, import-linter
- [x] `backend/tests/test_assessments_red_team*.py` -- every matrix row (fake gateway, Postgres), plus the grants (no DELETE, insert-only Findings and links)
- [x] Web: `schema.d.ts`, actions, the routing, the Red Team list, inspector and header, and tests with axe (including the 15-minute poll cutoff)

**Acceptance Criteria:**
- Given the demo Opportunity after its trigger (cloud profile, worker running), when the review finishes, then the UI shows specific, severity-ranked Red Team Findings, each citing the Requirements it challenges.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Import cycle (as in 8.1):** `assessments` reads Estimate lines through `estimates.application.public`, which imports `estimates.application.draft`, so `accept_draft` imports `assessments.application.public` inside the function, just before `enqueue_review(uow, opportunity_id)` (after `enqueue_proposals`). Only the success path that stores a version queues a review.
- **Estimate lines read:** new `estimates/application/line_refs.py` (`current_version_lines`, `version_lines`), exported from `estimates.application.public`. The agent sees the current draft version's lines as `L1…Ln` in grid order (template section order, then position), each with section and effort; line chips on read come from the reviewed version (`assessments_reviews.estimate_version_id`), whatever its status, in the same order.
- **No Estimate:** a POST retry before any draft still reviews the Requirements and Gaps; `estimate_version_id` is null (nullable column) and every `L<n>` is ignored. No active Requirements: no model call and no Review; the run `succeeded` and the section says "There were no active Requirements to review."
- **Enums in the schema:** `category` and `severity` are plain strings whose JSON schema carries `enum` (constrained decoding keeps to them), so a single bad value is dropped on acceptance (Bad enum row) instead of failing the whole reply.
- **Validation extras:** labels are trimmed; duplicate labels collapse; a `G<n>`/`L<n>` in `requirements` doesn't resolve. Requirement labels resolve only to Requirements still active at the version read (as in 8.1). An empty `findings` reply counts as "none valid" (retry, then `output_invalid`). Positions are the order of the valid Findings as proposed.
- **Read API:** `RedTeamReviewView` also carries `estimate_version` (the reviewed version's number) and `dropped_count`; Requirement chips use `R<n>` among the current active Requirements or `Superseded`, with a 140-character excerpt of the version read. The 409 code is `red_team_review_in_progress`. A run queued/running past both attempts' timeouts, backoff and five minutes reads as `failed` / `model_timeout` and is failed on the next enqueue or start.
- **Trace payload:** `assessments.red_team_review.completed` `{version, finding_count, critical_count, high_count, medium_count, low_count, dropped_count, requirement_count, gap_count, line_count, superseded_count}`, subject `assessments.review`.
- **Grants:** `assessments_red_team_runs` and `assessments_reviews` SELECT/INSERT/UPDATE; Findings and both link tables SELECT/INSERT only; no DELETE anywhere (tested).
- **Web:** the Assessments tab (5) routes to `[id]/assessments.tsx` with one "Red Team" section (`red-team-list.tsx`: list, header, section; `red-team-inspector.tsx`; `severity-pill.tsx`; `lib/red-team.ts`). Severity icons: Critical octagon-alert (blocker), High triangle-alert (gap), Medium circle-alert and Low info (muted). The polling includes the 8.1 fix: shown again after being hidden past 15 minutes it says "Still reviewing — reload to check." instead of pulsing.
- **Tests:** the intake fixture `_hidden_jobs` also hides and retires `assessments.red_team_review` jobs, since every accepted draft now queues one.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind | `accept_draft` rolls back if `enqueue_review` fails | false | reject | The frozen intent puts the enqueue in `accept_draft`'s Unit of Work; this is the decided design. |
| 2 | blind | estimates↔assessments function-level import cycle | false | reject | The Code Map sanctions it (as gaps does at detection.py ~:299); lint-imports keeps the AD-2 contracts; no harm named. |
| 3 | blind+edge | No server cap on the Finding count (prompt asks 3–12) | low | reject | Constrained decoding plus the prompt bound make a 40-Finding reply unlikely in everyday use; a cap adds a rule the intent does not state. |
| 4 | blind+edge | Staleness measured from `created_at`, not start; a live run queued >~39 min is failed and its result dropped | medium | defer | Real, but copies the 8.1 `drafts` pattern exactly (estimates repository :163), as the spec asks ("like the 8.1 drafts"); fix belongs across gaps/estimates/assessments together. |
| 5 | blind | GET staleness uses the app clock, `fail_stale_runs` the DB clock | low | defer | Same 8.1 pattern; merged into the deferred staleness entry. |
| 6 | blind | UI poll cutoff 15 min vs backend stale window ~39 min | medium | defer | The 15 min cutoff is frozen intent; the gap is the known 8.1 limitation, already noted by the implementer. |
| 7 | blind | All Requirements removed → run succeeds but the old Review stays current | low | reject | Requires every Requirement on the Opportunity to be retired after a draft; unlikely in use, and the fix adds a branch. |
| 8 | blind | Line links not re-checked when a newer draft lands mid-call | low | reject | The newer draft queues its own run, which supersedes this Review; `newer_succeeded` already drops out-of-date results. |
| 9 | blind | Retry only shown after failure | false | reject | The frozen intent specifies Retry on "Red Team review failed". |
| 10 | blind | Human start not traced | false | reject | The frozen intent names only `assessments.red_team_review.completed`. |
| 11 | blind | Empty excerpt chip when text is missing | low | reject | Every stored Requirement version has text; not reachable in practice. |
| 12 | blind | `section as SectionName` cast in the inspector | low | reject | Sections come only from the estimates template enum; developer-only, no reachable bad state. |
| 13 | blind | Run read model lacks id/timestamps | false | reject | The frozen API shape is `{review, run, can_start}` with status and error code. |
| 14 | blind | Findings not de-duplicated | low | reject | Not in the intent; near-duplicates are a prompt-quality matter for the live check. |
| 15 | edge | `created_at` = transaction start can misorder concurrent runs | low | defer | Same as 8.1 `drafts`; needs two runs inserted concurrently, which coalescing makes rare. Merged into the staleness entry. |
| 16 | verify | No test that a job whose run left queued/running is skipped without a model call | medium | patch | Pre-verified: no test exercises `_start`'s status guard. Fixed: test added; fails with the guard removed. |
| 17 | verify | Retry `not-found` message untested | low | patch | Pre-verified: the `it.each` covers only error/forbidden. Fixed: not-found row added. |
| 18 | verify | Downgrade retirement of Red Team jobs only runs on empty tables | low | defer | Same untested pattern as 0012/0013; belongs to a repo-wide migration-test pass. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
