---
title: 'Story 8.4 + 8.5 (demo scope): Gaps become Assumptions in the Register'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '4a21c6f98fe96b257c3cb51af0b929f3c55b1b3c'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-1-draft-estimate.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Open Gaps are exactly what gets "silently assumed away" today, and that's how estimates come in 20–50% low. The draft Estimate must state, for every open Gap, whether the customer must meet a **Condition** or we add a priced **Contingency**, and who accepted it (FR-14, FR-34).

**Approach:**
- After each draft Estimate Version is created, an `estimates.propose_assumptions` job asks the agent for one proposal per open Gap.
- `estimates.accept_assumption_proposals` stores the proposals as **unaccepted** Assumptions.
- The presales engineer accepts them one by one or all at once. Accepting records who accepted it and marks the Gap `converted` in the same transaction.
- Contingencies flow into the grid's Contingency column, calculated in code.

## Boundaries & Constraints

**Always:**
- **Depends on:** Story 8.1 (Estimate Versions, lines, arithmetic, Estimate tab), Story 4.3 (open Gaps and the `gaps` module) and Story 2.4 (gateway and contract).
- **Trigger:** `estimates.accept_draft` enqueues `estimates.propose_assumptions(version_id)` in its Unit of Work, at `background` priority with `timeout_s` 900 and `max_attempts` 2. A version that already has proposals is skipped.
- **Agent:** `estimating_agent` is reused with prompt `v1-assumptions`, a second prompt file.
  - Open Gaps go in as `G1…Gn` (title, category, why it matters, impact, question). The version's lines go in as `L1…Ln` (section, title, effort).
  - The output goes in `extensions["estimating_agent"]`: `assumptions: [{gap: "G<n>", kind: condition|contingency, wording, hours?, line: "L<n>"?}]`.
  - The prompt says: a **Condition** for things the customer must provide or decide, written as proposal-ready wording ("The estimate assumes …"). A **Contingency** for uncertainty we absorb, with hours sized to the Gap's impact and linked to the line it affects.
- **Validation:**
  - The `gap` label must resolve to an open Gap.
  - `wording` is 1–500 characters.
  - A Contingency needs `hours` from 0.5 to 1,000, rounded to 0.1. A Condition must not carry hours.
  - `line` is optional and must resolve to a line of this version.
  - One proposal per Gap: duplicates are dropped and counted.
  - If any open Gap has no valid proposal, the job retries once. After that it accepts what is valid, and the rest show as **Unconverted Gaps**.
- **Table:** `estimates_assumptions` columns: `id`, `version_id`, `kind`, `wording`, `amount_hours numeric(10,1)` (null for a Condition), `line_id` (nullable), `origin_ref jsonb` (`{kind: "gap", id, row_version}`), `accepted_by` and `accepted_at` (null until accepted), `row_version`, `created_at`.
- **Arithmetic (extends Story 8.1's domain functions):**
  - A line's Contingency is the sum of all its linked Contingency amounts, **accepted or not**: the grid shows what the Estimate would be.
  - Contingencies with no line add up in a version-level "Unallocated contingency" row, which counts in the totals.
  - Property tests are extended to cover this.
- **Accept:**
  - `POST /opportunities/{id}/assumptions/{aid}/accept` with `If-Match`.
  - `POST /opportunities/{id}/assumptions/accept-all` accepts every unaccepted Assumption of the current draft.
  - New action `estimates.assumption.accept`, for owner and collaborators except sales representatives.
  - Accepting takes `pg_advisory_xact_lock(opportunity_id)`. It sets `accepted_by` to the caller and `accepted_at` to now, and calls `gaps.mark_converted(gap_id)` in the **same Unit of Work**. If either fails, nothing commits.
  - Accepting an already-accepted Assumption returns 200 with no change.
  - The Gap must still be `open`. Otherwise the call returns 409 `gap_not_open` and nothing changes.
- **Gaps side:** the `gaps` lifecycle gains `converted`. The public `mark_converted` only allows `open` → `converted`. Converted Gaps leave the open-Gaps list, so a later re-detection doesn't supersede them. The Gaps tab shows them greyed out at the bottom, labelled "Converted to Condition" or "Converted to Contingency".
- **Trace:**
  - `estimates.assumption.proposed` (count, with the agent as actor).
  - `estimates.assumption.accepted` per Assumption, with the actor and the accepting person.
  - `gaps.gap.converted`.
  - All carry ids, kinds and hours only.
- **Read API:** the `GET /opportunities/{id}/estimate` version gains:
  - `assumptions`, grouped as `conditions` and `contingencies`, each item with its origin Gap (id, title, impact) and its linked line title;
  - `counts {total, accepted, not_accepted}`;
  - `unconverted_gaps`;
  - `unallocated_contingency_hours`.
- **Web: Assumptions Register (minimal 8.5), below the grid:**
  - Two groups: Conditions (clipboard-check icon) and Contingencies (shield-plus icon, with the group total in hours).
  - Each row shows the wording, the hours for a Contingency, a "Gap" origin chip (opening the Gap in the inspector), the linked line, and "Accepted by {name}, {date}".
  - An unaccepted row is a **blocker row**: blocker tint, a 2px blocker bar and a "Not accepted" label, never colour alone. It has an **Accept** button.
  - Header: "7 · 6 accepted · 1 not accepted" and **Accept all (N)**, hidden when N is 0.
  - An "Unconverted Gaps" note lists any Gap that has no proposal.
  - The grid's Contingency column and totals refresh from the server after each accept.
  - Sales representatives see everything read-only.
  - **On 412:** "Changed by {name} since you opened it." with Reload.

**Never:** No manual Convert form, no editing of Assumption wording, hours or kind, no Risks, no Unknowns or Findings, no accepting on behalf of another member, no submission gate (8.6), and no carrying Assumptions to a new version. These are `[post-demo]`. A re-draft (new version) gets fresh proposals for the Gaps that are still open.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Proposals | 4 open Gaps; fake agent returns 2 Conditions and 2 Contingencies (8 h on L2, 12 h with no line) | 4 unaccepted Assumptions; L2 Contingency 8.0; Unallocated 12.0; totals include both | N/A |
| Missing Gap | Agent skips G3, twice | 3 Assumptions; G3 listed under Unconverted Gaps | N/A |
| Invalid | A Condition with hours, or a Contingency without hours | That proposal dropped | N/A |
| Accept | Owner accepts A1 with the current `If-Match` | `accepted_by` and `accepted_at` set; Gap `converted`; both events; totals unchanged | N/A |
| Atomic | `mark_converted` fails (Gap already converted) | 409 `gap_not_open`; Assumption still unaccepted | Nothing committed |
| Accept all | 3 unaccepted, 1 accepted | 200, 3 accepted; 3 Gaps converted | N/A |
| Stale | Old `If-Match` | 412 | N/A |
| Who | Sales rep accepts / reads | 403 / 200 | N/A |
| Re-detect | Gap detection runs after conversions | Converted Gaps are untouched; only open detected Gaps are superseded | N/A |
| Totals property | Random lines and linked or unlinked contingencies | Line, section, unallocated and overall totals equal the sum of their parts | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/` (Story 8.1) -- add the assumptions table, the proposal job and `accept_assumption_proposals`, accept and accept-all commands, the read-model fields, and extend the domain arithmetic for linked and unallocated Contingency.
- `backend/app/modules/gaps/` (Story 4.3) -- add the `converted` status, the public `mark_converted(uow, gap_id, *, actor, assumption_kind)`, and a query for open Gaps including the question. Change the re-detection supersede to touch only `open` Gaps (already the rule), with a test.
- `backend/app/agents/estimating_agent/prompts/v1-assumptions.md` and its schema.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- `ASSUMPTION_ACCEPT`, excluding sales representatives like Story 2.6.
- `backend/app/platform/trace/catalogue.py` -- the three events.
- migrations -- the next revision: `estimates_assumptions` and the gaps status check constraint updated to allow `converted`.
- `web/src` Estimate tab (Story 8.1) -- an `assumptions-register.tsx` under the grid; blocker-row tokens from DESIGN.md (reuse them if present); Accept and Accept all actions; Gap origin chip into the inspector. Gaps tab: converted rows greyed out at the bottom.
- Tests -- domain property tests, job and accept and atomicity tests against Postgres with a fake gateway, API, web Register with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**`, `gaps/**` (converted), the agent prompt, identity, catalogue, migration
- [x] `backend/tests/test_estimates_assumptions.py` and extended property tests -- every matrix row
- [x] Web: `schema.d.ts`, actions, `assumptions-register.tsx`, the grid refresh, Gaps-tab converted rows, and tests

**Acceptance Criteria:**
- Given the demo Opportunity with a draft Estimate, when proposals finish and the presales engineer presses **Accept all**, then every open Gap appears in the Register as an accepted Condition or a priced Contingency, the Gaps tab shows them as converted, and the Estimate totals include the Contingency hours.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Proposal state (added):** `estimates_estimate_versions.proposal_status` (`queued|running|succeeded|failed`, null for pre-8.4 versions) drives "Proposing Assumptions" polling, the failed note, and when `unconverted_gaps` is computed (only once proposals finished; empty before). `accept_draft` inserts the version `queued` and enqueues the job; a gateway error on the final attempt marks it `failed` (no retry button: a re-draft gets fresh proposals).
- **Extra columns:** `estimates_assumptions.position` keeps proposal order (UUIDv7 isn't monotonic within a millisecond). `gaps_gaps.converted_to` (`condition|contingency`, set exactly when `converted`) lets the Gaps tab label converted rows without gaps importing estimates.
- **Validation extras:** a Condition's `line` label is ignored (not dropped); duplicates are counted separately (`duplicate_count`) from invalid ones (`dropped_count`) in `estimates.assumption.proposed`, which also carries `condition_count`, `contingency_count`, `unconverted_count`. Labels resolve only to Gaps still open at acceptance; `origin_ref.row_version` is the Gap's row version then.
- **Accept:** the lock is `pg_advisory_xact_lock(hashtextextended('estimates.opportunity:<id>'))`. Only Assumptions of the Opportunity's current draft are found (404 otherwise, e.g. a superseded version's). 404 is checked before If-Match (428/412), as in Story 2.6. Accept-all is all or nothing: one Gap no longer open fails the whole call with 409 `gap_not_open`. Single accept returns the Assumption with its ETag; accept-all returns `{count}`; the web reads the Estimate again after either.
- **Read API:** each Assumption has `origin_kind: "gap"` and `origin` (id, title, category, impact, why it matters, status), `line` (id, title), `accepted_by` (UserRef), `accepted_at`, `row_version`; `assumptions.contingency_hours` is the group total (server-calculated). `EstimateView.can_accept_assumptions` hides Accept for sales reps. `gaps.list_gaps` returns converted Gaps after the open ones (`Gap.converted_to`).
- **Web:** Unallocated contingency is a grid row before the sticky totals (shown when > 0). The Gap chip opens a compact Gap inspector (title, category, why it matters, impact, status). On 412 the changer's name is read again from the Estimate.
- **Tests:** the `_hidden_jobs` fixture also hides and retires `estimates.propose_assumptions` jobs.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | blind+edge | Failed (or pre-8.4 null) proposals are a dead end: no Retry or Re-draft in the UI; failure note blames the model's answer even when the gateway was down | medium | patch | Retry only shows when the draft failed; `POST /estimate-drafts` exists but has no button after success. Fixed by reusing that action, with no new endpoint. |
| 2 | edge | Accept and accept-all take `lock_assumptions`, `accept_draft` takes `lock_opportunity`, so an accept can convert a Gap on a version being superseded | low | patch | Confirmed in repository.py:79 and :383: two different advisory-lock keys. |
| 3 | verification | No test polls while proposals are queued after a succeeded draft | low | patch | Every fixture uses `proposal_status: "succeeded"`. |
| 4 | verification | No test of the `CancelledError` branch of `propose_assumptions` | low | patch | Only the `except Exception` branch is tested. |
| 5 | verification | No test of a Gap closing during the model call (`still_open`) | low | patch | No test changes Gaps between `_start` and acceptance. |
| 6 | verification | Gaps-tab announcement filter has no test with a converted Gap | low | patch | gaps-list.test.tsx:427 loads only open Gaps. |
| 7 | blind+edge | After a re-detection, a superseded Gap makes all-or-nothing Accept all return 409 until the new draft lands; Accept stays visible on those rows | medium | defer | Transient: re-detection queues a new draft with fresh proposals; lasts only until that draft lands. Skipping instead of failing is a behaviour choice the spec doesn't make. |
| 8 | blind+edge+verification | Nothing recovers `proposal_status` stuck `queued`/`running` when the worker dies on the final attempt | medium | defer | Unverified whether the job runner re-invokes the handler after lease expiry; drafts have `fail_stale`, proposals don't. |
| 9 | verification | No round-trip test of migration 0013's data-changing downgrade | low | defer | Filed as defer by the reviewer; downgrades aren't on the demo path. |
| 10 | blind+edge | Re-draft drops accepted Assumptions; a converted Gap then shows no Assumption in the new version | false | reject | Intent: "no carrying Assumptions to a new version [post-demo]. A re-draft gets fresh proposals for the Gaps that are still open." |
| 11 | blind | 412 "Changed by" is effectively unreachable; a second accepter gets 200 | low | reject | The spec requires the idempotent 200; the 412 test still covers a stale `If-Match`. |
| 12 | edge | Already-accepted with no `If-Match` returns 428, not 200 | low | reject | A missing precondition is refused before the idempotency check, as in Story 2.6. |
| 13 | blind | `origin_ref.row_version` stored but not checked | low | reject | The spec asks only to record it. |
| 14 | blind | `gaps.gap.converted` lacks `assumption_id` | low | reject | The spec fixes the payloads to ids, kinds and hours; the link isn't needed for the demo. |
| 15 | blind | DB check on hours looser than the domain; line FK cascades | low | reject | Validation is the only writer; lines are insert-only, never deleted. |
| 16 | blind | Accept all while proposing returns count 0; no accepted-only totals | low | reject | Accept all is hidden at 0; the spec says to total all Contingency. |
| 17 | blind | 422 vs 412 for a huge `If-Match`; `assert` in production; `_origin` placeholder | low | reject | Existing patterns or unreachable paths. |
| 18 | blind | Prettier rewrapping noise in web/src/lib/estimates*.ts | low | reject | 7 lines; cosmetic. |
| 19 | blind | Gaps tab with only converted Gaps hides the empty state | false | reject | Showing the converted rows is the intended display. |
| 20 | edge | Pre-8.4 drafts have null `proposal_status` and never get proposals | low | patch | Folded into row 1: Retry is also offered for a null status. |
| 21 | edge | Claim: Accept all leaves Gaps with no proposal open | false | reject | Unconverted Gaps are defined by the spec. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
