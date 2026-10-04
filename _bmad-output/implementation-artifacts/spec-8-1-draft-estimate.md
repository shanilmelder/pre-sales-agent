---
title: 'Story 8.1 + 8.2 + 8.3 (demo scope): Draft Estimate with deterministic totals'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '189c999a6c88c3de986c863ccf9eae56525acdb7'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-3-detect-gaps.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After Requirements and Gaps, the presales engineer still builds the estimate by hand in a spreadsheet, and its numbers aren't linked to what the customer asked for (FR-33).

**Approach:**
- Add the `estimates` module and the `estimating_agent`.
- After every successful Gap detection, an `estimates.draft_estimate` job asks the agent to group the active Requirements into work items, with effort and a role mix.
- `estimates.accept_draft` stores a `draft` Estimate Version.
- Every total is calculated by pure domain functions, never by the model.
- The Estimate tab shows the grid.

## Boundaries & Constraints

**Always:**
- **Depends on:** Story 4.3 (open Gaps and `gaps.accept_gap_detection`), Story 2.5 Part A (active Requirements), Story 2.4 (gateway and contract) and Story 2.2 Part A (jobs).
- **Trigger (decided: automatic):**
  - `gaps.accept_gap_detection` enqueues `estimates.draft_estimate` for the Opportunity in its Unit of Work, through `estimates.application.public`.
  - If a draft job is still unclaimed for that Opportunity, no second one is added.
  - The job runs at `background` priority with `timeout_s` 900 and `max_attempts` 2.
- **Template (demo):** template version `demo-1`, held in `estimates/domain`.
  - **Sections:** the six Requirement classifications, in the Requirements tab order.
  - **Roles:** `engineer`, `project_manager`, `qa`.
  - **Columns:** Line, Covers, Role mix (%), Effort (h), Contingency (h), Total (h).
- **Agent:**
  - `app/agents/estimating_agent/` is `AgentConfig("estimating_agent", "0.1.0", prompt v1, profile chat)`.
  - Active Requirements enter the prompt as delimited data labelled `R1…Rn`, with their classification. Open Gaps enter as `G1…Gn`, with category, why it matters and impact, as context for risk only.
  - The output goes in `extensions["estimating_agent"]`: `lines: [{section, title, covers: ["R<n>"…], effort_hours, role_mix: {engineer, project_manager, qa}, basis}]`.
  - The prompt asks for 5–20 work items, each covering related Requirements, with a short basis for its effort.
- **Accept (`estimates.accept_draft`, one Unit of Work after the model call):**
  - **Line rules:** a known section; a title of 1–160 characters; at least one `covers` label that resolves to an active Requirement; `effort_hours` from 0.5 to 2,000, rounded to 0.1; a role mix of integers from 0 to 100 summing to exactly 100; a basis of 1–500 characters.
  - **Coverage:** invalid lines are dropped and counted. Active Requirements that no valid line covers are counted as `uncovered`.
  - If no line is valid, the job retries once, then fails with `output_invalid`.
  - **Versions:** each accepted draft creates a new Estimate Version (`version` = the previous one + 1, `status` `draft`, `template_version` `demo-1`). The previous `draft` becomes `superseded`. A superseded version is read-only and hidden from the default view.
- **Tables:**
  - `estimates_estimate_versions`: `id`, `opportunity_id`, `version`, `status` (`draft | superseded`), `template_version`, `uncovered_count`, `dropped_count`, `row_version`, `created_at`.
  - `estimates_estimate_lines`: `id`, `version_id`, `position`, `section`, `title`, `effort_hours numeric(10,1)`, `role_mix jsonb`, `basis`.
  - `estimates_line_requirements`: `line_id`, `requirement_id`, `requirement_version`.
  - `estimates_drafts`: `id`, `opportunity_id`, `status` (`queued|running|succeeded|failed`), `error_code`, `created_at`, `finished_at`.
- **Arithmetic (pure domain functions, AD-10):**
  - **Per-role hours:** effort × mix, rounded to 0.1 h by the largest-remainder method, so the role hours sum exactly to the line effort.
  - **Contingency:** a line's Contingency is the sum of its linked Contingency amounts (0 until Story 8.4 links any). A line's total is effort plus Contingency.
  - **Subtotals and totals:** section subtotals, per-role totals, and overall effort, Contingency and total.
  - Property-based tests (`hypothesis`) prove totals equal the sum of their parts for any valid input.
- **API:**
  - `GET /opportunities/{id}/estimate` (readers) returns `{version | null, draft: {status, error_code} | null}`. The version includes its sections with lines and their server-calculated per-role hours and totals, the covered Requirement excerpts, the section subtotals, the role totals and the overall totals.
  - No endpoint accepts a total.
  - `POST /opportunities/{id}/estimate-drafts` (new action `estimates.draft.start`, owner and collaborators except sales representatives) retries a failed draft. Returns 409 while one is running.
- **Trace:** `estimates.estimate_version.created` with the version, line count and counts only. Actor `estimating_agent@0.1.0`.
- **Web: Estimate tab (minimal 8.2):**
  - A dense grid grouped by section, with a sticky header and a sticky totals row.
  - Columns: Line, Covers (Requirement count chip), Role mix (`E 60 · PM 20 · QA 20`), Effort (h), Contingency (h), Total (h). The Contingency column has a left rule. Numbers use tabular figures and are right-aligned.
  - Section subtotal rows, plus a per-role totals row under the totals.
  - The header shows the version pill (`Draft v2`), "Drafting Estimate" with a running dot while a draft is queued or running (polling every 2 s, paused while hidden), and "Estimate draft failed: <reason>" with Retry.
  - Selecting a line opens the inspector: its basis, the role-mix breakdown in hours, and the covered Requirements as chips with excerpts.
  - Empty: "The Estimate is drafted after Gaps are detected."
  - Read-only for everyone in this story. Inline editing is `[post-demo]`.
  - The `j`/`k`/arrows and Enter keyboard model, as in the Requirements list.

**Never:**
- No catalogue tags or `catalogue_required`.
- No inline edit, add or delete of lines. No submit (8.6). No versions comparison (8.7). No money. No durations.
- No Assessments or Specialist Agents (Epic 5).
- No export (8.8).
- No Assumptions here: that's Story 8.4.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Auto-queue | Gap detection accepted | One draft job queued in the same transaction | N/A |
| Happy | Fake agent returns 6 valid lines over R1–R10 | Draft v1, 6 lines, links to Requirements at their versions, server totals; one trace event | N/A |
| Role rounding | Effort 10.0 h, mix 33/33/34 | Role hours 3.3 / 3.3 / 3.4, summing to 10.0 | N/A |
| Bad mix | Mix sums to 90 | Line dropped; `dropped_count` 1 | N/A |
| Bad label | Covers `R99` only | Line dropped | N/A |
| Uncovered | R7 not covered by any valid line | `uncovered_count` 1, shown in the header as "1 Requirement not covered" | N/A |
| All invalid | Every line invalid, twice | `failed`, `output_invalid`; no version written | Retry offered |
| Re-draft | A second draft | v2 `draft`, v1 `superseded`; the tab shows v2 | N/A |
| Totals property | Random valid lines and contingencies | Section, role and overall totals equal the sum of their parts | N/A |
| Who | Sales rep POSTs a retry / reads | 403 / 200 | N/A |
| Privacy | Any run | No Requirement or line text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/` (new, mirroring `gaps`) -- `domain/` (template `demo-1`, line rules, the arithmetic module with largest-remainder rounding), `application/` (draft job, `accept_draft`, read query, retry command, `public.py` with `enqueue_draft(uow, opportunity_id)`), `adapters/` (tables, repository), `api/`. Wire it like `gaps`: modules list, router, `main_worker._JOB_MODULES`, `migrations/env.py`, and import-linter contracts (estimates uses intake and gaps only through their `public.py`).
- `backend/app/modules/gaps/application/` (Story 4.3) -- the hook in `accept_gap_detection`, and a public query for open Gaps (id, title, category, why it matters, impact).
- `backend/app/modules/intake/application/public.py` -- the active Requirements query from Story 4.3.
- `backend/app/agents/estimating_agent/` -- following `clarification_agent`.
- `backend/pyproject.toml` -- add `hypothesis` (dev group, pinned).
- migrations -- the next revision: the four `estimates_*` tables with grants.
- `web/src/app/opportunities/[id]/[tab]/page.tsx` -- route `estimate` to `[id]/estimate.tsx`. Build an `estimate-grid.tsx` and a line inspector, reusing the list keyboard pattern and tokens.
- Tests -- domain arithmetic (unit plus `hypothesis`), job and accept with a fake gateway against Postgres, API, web grid and inspector with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**`, `app/agents/estimating_agent/**`, the gaps hook, identity, catalogue, migration, wiring
- [x] `backend/tests/test_estimates_*.py` -- every matrix row, including the property tests
- [x] Web: `schema.d.ts` (from local uvicorn), actions, `[id]/estimate.tsx`, grid, inspector and tests

**Acceptance Criteria:**
- Given the demo Opportunity after Gap detection (cloud profile, worker running), when the draft finishes, then the Estimate tab shows sectioned work items that cover the Requirements, with role mixes and server-calculated totals that add up exactly.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Import cycle (decided in code, as in 4.3):** `estimates` reads Gaps through `gaps.application.public`, which imports `gaps.application.detection`, so `accept_gap_detection` imports `estimates.application.public` inside the function, just before `estimates.enqueue_draft(uow, opportunity_id)`. The draft is queued only on the success path that stores Gaps (including a valid empty result), not for an outdated or `output_invalid` detection. The gaps import-linter contract now also forbids `estimates.domain/adapters/api`.
- **Open Gaps query:** `gaps.open_gap_summaries` (new `gaps/application/gap_refs.py`) returns `{id, category, impact, title, why_it_matters}` ranked as the Gaps tab lists them; the agent sees them as `G1…Gn`.
- **No active Requirements:** no model call and no version; the draft is `succeeded` and the tab says "There were no active Requirements to estimate." An empty `lines` reply from the model when Requirements exist counts as "no line is valid" (retry, then `output_invalid`).
- **Validation extras:** unknown `covers` labels are ignored when another resolves (as in 4.3); labels resolve only to Requirements still active at the version read. Effort is rounded half-up to 0.1 before the 0.5–2,000 check (so 0.45 is accepted as 0.5). The role mix must name exactly the three roles. `uncovered_count` counts the Opportunity's active Requirements (current versions) that no valid line covers.
- **Versions:** numbered `max(version) + 1` under the Opportunity's draft lock; a partial unique index (`status = 'draft'`) keeps at most one `draft` per Opportunity. Lines and their links are insert-only for `psa_app` (no editing in this story). No totals are stored; `GET …/estimate` recalculates them on every read.
- **Arithmetic:** `domain/arithmetic.py` works in whole tenths of an hour (exact sums); largest-remainder ties go to the earlier role (engineer, project manager, QA). Role totals split effort only; Contingency is not split by role. API hours are JSON numbers with one decimal place.
- **Read API extras:** `EstimateView.can_start_draft` (like `can_start_detection`) drives Retry. Only sections with lines are returned, in template order. The 409 code is `estimate_draft_in_progress`. A draft `queued`/`running` past both attempts' timeouts plus a minute reads as `failed` / `model_timeout`, as for detections.
- **Trace payload:** `estimates.estimate_version.created` `{version, template_version, line_count, dropped_count, uncovered_count, requirement_count, superseded_count}`.
- **Schema name:** the domain role enum is `EstimateRole` (not `Role`) so its OpenAPI schema doesn't collide with identity's `Role`.
- **Tests:** the intake fixture `_hidden_jobs` also hides and retires `estimates.draft_estimate` jobs, since every accepted Gap detection queues one. `hypothesis==6.168.3` added to the dev group; `.hypothesis/` is git-ignored.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | edge | Huge effort (1e30) makes `quantize` raise `InvalidOperation`, failing the whole draft | medium | patch | Reproduced: `Decimal('1e30').quantize(Decimal('0.1'))` raises; nothing catches it in `validate_lines`. |
| 2 | blind+edge | `stale_after` ignores backoff and queue wait, so attempt 2 of a live draft can be failed as lost | medium | patch | 900 + up to 120 backoff + 900 > 1860 s window; the later accept returns None. |
| 3 | blind+edge | Outdated draft's output is validated before the `newer_succeeded` check, causing a needless retry or failure | low | patch | `accept_draft` calls `proposal()`/`validate_lines` first; a reorder fixes it. |
| 4 | edge | Tab hidden past the 15-minute poll limit then shown: `stalled` never set, dot pulses forever | low | patch | estimate-grid.tsx:431 returns before `setStalled`. The same bug exists in gaps-list.tsx:269 (deferred). |
| 5 | verification | No test of `EstimateSection`'s 15-minute polling cutoff | low | patch | Only `EstimateHeader` gets `stalled` passed by hand. |
| 6 | verification | No test that migration 0012 makes lines and links insert-only for psa_app | low | patch | No `estimates_*` privilege test; the repo has the pattern in test_intake_requirement_edits.py:159. |
| 7 | blind+edge | Estimate goes stale after Requirement edits: no indicator, no Re-draft once succeeded, chips show current `R<n>` with the old version's excerpt | medium | defer | Real, but re-draft triggers and stale flags are not in the demo intent (Retry only after failure). |
| 8 | blind | UI stops polling at 15 min but the backend treats a draft as lost only after ~31 min, so Retry gets 409 in between | low | reject | Same pattern as the Gaps tab; only after a lost job; fix needs a shared deadline. |
| 9 | blind | No server cap on line count | low | reject | Prompt asks for 5–20; a runaway reply is unlikely and a cap is new behaviour. |
| 10 | blind | DB check constraints weaker than domain rules | low | reject | `accept_draft` is the only writer and validates every value. |
| 11 | blind | Version lacks agent/prompt provenance | false | reject | The spec fixes the trace to counts with actor `estimating_agent@0.1.0`. |
| 12 | blind | No trace for draft start or failure | false | reject | The spec defines one trace event only. |
| 13 | blind | gaps↔estimates coupling; enqueue errors roll back Gap detection | false | reject | The spec requires the enqueue in the same Unit of Work. |
| 14 | blind | `aria-selected` on a plain `<tr>` | low | reject | Same pattern as the Requirements and Gaps lists; axe passes. |
| 15 | blind | Silent 409 on Retry; blank excerpt when text is missing | low | reject | Rare paths; the view reloads into the correct state. |
| 16 | blind | Missing tests: fence token, draft queued while one runs, second-cancel branch | low | reject | Low-risk paths mirroring tested siblings. |
| 17 | blind | `test_no_endpoint_accepts_a_total` is weak | low | reject | No estimate endpoint takes a body or parameters today. |
| 18 | blind | `commercial` section overlaps the PM role share | maybe-false | reject | Prompt-quality question for the live check; at most low. |
| 19 | edge | Every Requirement deactivated after a version: the old Estimate stays current | low | reject | Unlikely; Requirements can't be deleted in the demo. |
| 20 | edge | An outdated successful Gap detection queues no draft | false | reject | The newer detection already queued one. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
