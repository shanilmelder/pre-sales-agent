---
title: 'Story 8.6: Submission blockers gate and Estimate submission'
type: 'feature'
created: '2026-10-24'
status: 'done'
baseline_commit: 'a3e9347ead4d6a7879aa958c3200a862b003350d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-4-gaps-to-assumptions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing stops an Estimate Version with open Gaps, unaccepted Assumptions, open Conflicts or critical Findings from going out, and there is no Submit at all. The Overview's blockers card is assembled in the browser from other tabs' reads, so it is not the single rule AD-27 requires.

**Approach:** `estimates.get_submission_blockers(version)` becomes the only check, and `estimates.submit_version` re-runs it under the lock and moves the version `draft` → `submitted`. Every surface reads the same check, follows the new mockup and updates over SSE: the Overview card, the header Submit and Resolve buttons, the Estimate tab badge, Submit on the Estimate tab, and the list blocker count.

## Boundaries & Constraints

**Always:**
- **Query:** `get_submission_blockers(uow, version_id) -> SubmissionBlockers {to_submit: [Blocker], to_baseline: []}`. `Blocker {kind, subject_id, title, detail, href}` has kind `gap | assumption | conflict | finding | uncovered_requirement | review_request`. Each kind is read through its owner's `public.py`:
  - `gap`: `gaps.open_gap_summaries`. Open Unknowns are open Gaps.
  - `assumption`: unaccepted Assumptions of the version.
  - `conflict`: `conflicts.list_open`, which uses the conflicts module's own `BLOCKING` set.
  - `finding`: `assessments.get_blocking_findings` (Story 6.6, merged): open critical Findings of the current Critic and Red Team Reviews.
  - `uncovered_requirement` (**decision 2026-10-24:** the user chose to make it a blocker, which changes FR-14/AD-27): active Requirements (`intake.active_requirement_snapshots`) that no line of the version covers (`estimates_line_requirements`). It is computed live, not read from the stored `uncovered_count`.
  - `review_request`: always `[]`.
- **Batched count:** `submission_blocker_counts(uow, opportunity_ids) -> dict[UUID, int]` goes in `estimates/application/public.py` and feeds `OpportunitySummary.blocker_count`. It runs per-module batched counts with no per-row query loop, and it must equal `len(to_submit)`.
- **Read API:**
  - `EstimateView` gains `blockers` and `can_submit` (true when the caller may submit and the current version is a draft).
  - `GET /opportunities/{id}/submission-blockers` returns the blockers for the Overview and the header.
  - The current version is the draft if one exists, otherwise the latest `submitted`.
- **Submit:** `POST /opportunities/{id}/estimate/versions/{vid}/submit` with `If-Match`.
  - Uses a new action `estimates.estimate_version.submit`: owner and collaborators get it, sales representatives get 403.
  - Takes `lock_opportunity` then `lock_assumptions`, the same order Accept uses, then re-runs the query in that Unit of Work.
  - Blocked: 409 `estimate_version_blocked`, with the blockers in a `blockers` extension member of the problem body, and the version stays `draft`.
  - Otherwise the status becomes `submitted`. Earlier `submitted` versions become `superseded`, each with an `estimates.estimate_version.superseded` event. Then `estimates.estimate_version.submitted` is appended with ids and counts only.
  - Lines and Assumptions of a non-draft version stay immutable through the existing not-draft errors.
- **Migration 00NN:** the version status check gains `submitted`.
- **Live updates:** trace events already reach SSE. The web refreshes blockers on `gaps.changed`, `conflicts.changed` and the `estimates.*` and `assessments.*` trace frames (one shared hook, `useBlockersEvents`). The announcement uses `useAnnounce()`: "3 blockers before you can submit" or "0 blockers — ready to submit".
- **Web, matching the new mockup:**
  - *Overview card:* replace the browser-built `blockers()`. The header pill reads "N to submit · M to Baseline" in `blocker` tone, or "0 blockers" in `resolved` tone.
  - *Card groups:* the "Blockers to submit · N" group uses blocker-tint rows. **Decision:** one mockup row per kind ("3 open Gaps" with an alert icon, a bold title, a meta line and a tab action such as Open Gaps, Resolve, Open Estimate or Open Requirements), with each subject listed underneath as a direct link to it. The "Blockers to Baseline · 0" group reads "No Review Requests yet". When ready, the card shows a centred check, "0 blockers — ready to submit" and "Both gates are clear. Submit is now the primary action."
  - *Header actions*, in both header variants:
    - Blocked: an `outline` Submit with `aria-disabled` and "Resolve N blockers to submit" next to it, plus a primary **Resolve N blockers** that links to the Overview card.
    - Ready: Submit is primary and Resolve is hidden.
  - *Estimate tab:* Submit (same rules), and the banner "Submitted v3, 14 Oct" on a submitted version. The tab badge shows `to_submit` count, blocker-toned while above 0.
  - *Confirm dialog:* "Submit Estimate v3?" / "Submitted versions can't be edited." / Cancel and Submit. A 409 shows an inline alert listing the blockers and refreshes them.
  - *Opportunity list:* the Open items cell adds "N to submit" in `text-blocker`.
- **Accessibility:** axe passes on the card, header, dialog and tab. Every state has an icon plus text, never colour alone.

**Never:**
- No other code decides submittability. Delete the web-side derivation; do not mirror it.
- No New version button, version diff, Baseline, Review Requests or in_review transitions: those are 8.7, 9.x. No Overview KPI or pipeline recomposition: that is 8.9.
- No Add line action for uncovered Requirements. Lines still come only from drafting.
- No change to Story 8.5 Risk or Assumption-edit behaviour (PR #82).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mixed | 2 open Gaps, 1 unaccepted Assumption, 1 escalated Conflict, 1 open critical Red Team Finding, 1 uncovered Requirement | `to_submit` has 6 typed items with hrefs; count is 6; list shows "6 to submit" | N/A |
| Overridden | That Finding is overridden (6.6) | It leaves `to_submit`; the SSE refresh drops its row | N/A |
| Ready | Nothing open | `to_submit` is `[]`; `can_submit` is true | N/A |
| Submit OK | Ready draft v2, correct If-Match | v2 is `submitted`; the earlier submitted v1 is `superseded`; both events written | N/A |
| Submit blocked | A Gap reopened after the page loaded | 409 `estimate_version_blocked` with `blockers`; v2 stays `draft` | Inline alert, card refresh |
| Race | Accept and submit run concurrently, submit last | The lock serialises them; the outcome matches the blockers at commit time | N/A |
| Stale | Old If-Match | 412 | Reload |
| Not draft | Submit a submitted version | 409 `estimate_version_not_draft` | N/A |
| Who | Sales rep submits or reads | 403 / 200 (no Submit shown) | N/A |
| Edit after | PATCH a line of a submitted version | 409 not-draft; nothing changes | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/domain/estimates.py:83` `VersionStatus` -- add `submitted`; `adapters/models.py:65-71` -- status check (the one-draft partial index stays).
- `estimates/adapters/repository.py` -- `lock_opportunity` (:89), `lock_assumptions` (:537), `assumptions_of(..., unaccepted_only=True)` (:689), `supersede_drafts` (:239) as the pattern for superseding submitted versions, `current_version(s)` (:326-356) to return the draft, else the latest submitted.
- `estimates/application/` -- new `blockers.py` (query + batched counts) and `submit.py`; `models.py:233` `EstimateView`; `estimates.py:448` `get_estimate`; `public.py` exports the counts. `api/routes.py:53` -- add the submit and blockers routes.
- `gaps/application/gap_refs.py:65,80` `open_gap_summaries`, `open_gap_counts`; `conflicts/application/conflicts.py:333,340` `open_conflict_counts`, `list_open`; `assessments/application/findings.py:168` `get_blocking_findings` (add a batched `blocking_finding_counts(uow, ids)` to assessments `public.py`); `intake.active_requirement_snapshots`, `estimates/domain/estimates.py:251` `uncovered` and the `estimates_line_requirements` table (`adapters/models.py:158`) for the uncovered kind.
- `backend/app/platform/errors.py:40-48` -- allow optional extension members on the problem body; add `EstimateVersionBlockedError` next to `EstimateVersionNotDraftError` (:210).
- `platform/trace/catalogue.py:564-662` -- the `submitted` and `superseded` payloads; `web/src/lib/trace.ts:65` labels.
- `identity/actions.py`, `identity/domain/policy.py:72,91,114` -- the submit action and grants (Auth0 is mapped by hand; add the permission to the README Auth0 list).
- `opportunities/application/opportunities.py:190-235` `_page`, `models.py:104` `OpportunitySummary.blocker_count`.
- Migration `0044` after `20261024_0043_estimates_risks.py` (Story 8.5 took 0043; renumbered at the merge).
- Web:
  - `components/opportunities/overview-summary.tsx:533-597` (card) and `lib/overview.ts:485-549` (`blockers()`, to delete; its uncovered row moves to the API kind), `:50` copy.
  - `workspace-header.tsx:40`, `inline-field.tsx:267/413` and `header-parts.tsx` (actions slot).
  - `workspace-tabs.tsx:21,59-92,168` (Estimate badge) and `app/opportunities/[id]/layout.tsx:35`.
  - `estimate-grid.tsx:413,570`, `app/opportunities/actions.ts`, `data.ts:224`.
  - `lib/opportunity-events.ts:282-294` (new hook), `shell/live-region.tsx:76`, `ui/dialog.tsx` (pattern `specialist-assessments.tsx:940`), `ui/button.tsx`, `ui/pill.tsx`.
  - `opportunities-table.tsx:85`.
- Tests:
  - Fixtures come from `tests/test_intake_extraction.py` (`FakeGateway`, `client`, `drain`) and `test_estimates_assumptions.py:126,144`.
  - The lock-race pattern is `test_intake_sources.py:549-606`.
  - Web tests sit next to their files, with `test/axe.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/*_submitted_status.py`, `estimates/domain|adapters` -- the `submitted` status, current-version rule and supersede-submitted -- the base for submit
- [x] `estimates/application/blockers.py`, `public.py`, plus the read helpers in gaps, conflicts and assessments `public.py` -- the single query and its batched counts -- AD-27
- [x] `estimates/application/submit.py`, `api/routes.py`, `platform/errors.py`, trace catalogue, identity -- submit under the lock, 409 with blockers -- FR-14/FR-34
- [x] `opportunities/application/*` -- `blocker_count` in the list
- [x] `backend/tests/test_estimates_submit.py` -- every matrix row, the race test, and a count-equals-query test
- [x] `npm run gen:api` against a fresh local uvicorn (not the Docker api)
- [x] Web: the card, header actions, Estimate Submit, banner and badge, dialog, list cell, the `useBlockersEvents` refresh plus announcement, and tests with axe

**Acceptance Criteria:**
- Given a draft with blockers, when the presales engineer resolves the last one on another tab, then the Overview card switches to "0 blockers — ready to submit" without a reload, the announcement fires, and Submit becomes primary in the header and on the Estimate tab.
- Given a submitted version, when the Estimate tab renders, then the submitted banner shows and no edit or Accept control is offered.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **`submitted_at` (added):** migration 0044 also adds `estimates_estimate_versions.submitted_at` (set by submit, kept once superseded; a check makes a `submitted` version always have it) so the Estimate tab banner can read "Submitted v3, 14 Oct". `EstimateVersion` and `SubmissionVersion` expose it.
- **Current version:** `repo.current_version(s)` returns the draft, else the latest `submitted`. `repo.draft_version` (draft only) is used by the Conflict decision's line edit (6.3), so a submitted version is never changed. Accept and Accept all on a submitted current version are 409 `estimate_version_not_draft` ("This Estimate Version was submitted and can't be edited."); a re-draft after a submission carries the submitted version's accepted Assumptions and edits. The export header says "Submitted" for a submitted version.
- **Read API shape:** `GET …/submission-blockers` returns `SubmissionBlockersView` = `SubmissionBlockers` plus `version` (id, number, status, `row_version` for `If-Match`, `created_at`, `submitted_at`) and `can_submit`. Submit returns `SubmittedVersion` with an `ETag`. Hrefs are `/opportunities/{id}/{tab}#{gap|assumption|conflict|finding|requirement}-{id}`; the rows of those tabs carry the matching DOM ids.
- **Before the first version** the blockers list only the Opportunity's own kinds (Gaps, Conflicts, Findings); `can_submit` is false.
- **Problem extensions:** `ProblemError.extensions` adds members to the body (never replacing standard ones); `EstimateVersionBlockedError` sets `blockers`. The submit 409 is documented with an inline `SubmissionBlockedProblem` schema.
- **Batched count:** `submission_blocker_counts` uses `gaps.open_gap_counts`, `conflicts.open_conflict_counts`, the new `assessments.blocking_finding_counts`, the new `intake.active_requirement_ids`, and two estimates queries (unaccepted counts, covered Requirements), whatever the page size.
- **Web:** one `SubmissionProvider` (`submission-context.tsx`) in the workspace layout holds the blockers for the header actions, the Estimate tab badge, the Overview card and the Estimate tab's Submit; it re-reads them on `useBlockersEvents` frames (with Requirement trace frames too, for uncovered Requirements) and announces count changes. Auth0: the submit action is relation-granted only, so the README notes it needs no Auth0 permission.
- **Submitted has no blockers (verification fix):** a version that is no longer a draft has passed the gate. `blockers_for` and `submission_blocker_counts` return none or 0 for it, so the Overview card, the badge and the list don't show "N to submit" when a Requirement or Gap is added after submission. The list's Estimate cell reads "Submitted v3" or "Draft v3" (`EstimateSummary.status`).

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | blind | Generated API types missing from the diff | false | reject | `schema.d.ts` was excluded from the review diff on purpose; it was regenerated and `npm run typecheck` passes. |
| 2 | blind+edge | Submit's lock doesn't serialise Gap, Conflict, Finding or Requirement writers in other modules, so a blocker committed between the re-check and the commit can slip through | medium | defer | Confirmed: every module has its own lock key (`gaps.detection:`, `conflicts.detect:`, `assessments.*`) and there is no shared AD-26 per-Opportunity lock. The fix touches four modules' writers; the spec fixes submit's locks to `lock_opportunity` + `lock_assumptions`. |
| 3 | blind | If-Match on the version's row_version misses line edits and accepts made after the page loaded | medium | defer | Line edits and accepts bump their own row_version, not the version's. The blocker re-check still guards safety, so this is about stale totals only. Bumping the version on each child write is a design change. |
| 4 | blind | Estimate tab shows two Submit buttons (header and toolbar) | medium | patch | The header renders `SubmissionHeaderActions` on every tab and `EstimateSection` adds `SubmitEstimate`. Removing the toolbar copy keeps "Submit primary on the Estimate tab" through the header. |
| 5 | blind+edge | `BLOCKER_TRACE_EVENTS` misses `intake.requirement_change.accepted` / `intake.requirement.edited` | low | patch | Both exist in the catalogue (:220, :323) and change active or covered Requirements. |
| 6 | blind | The Overview card has no submitted state | medium | patch | `BlockersBody` falls through to an empty "Blockers to submit · 0" group when the status is submitted. |
| 7 | blind | A re-draft hides the submitted version | false | reject | By design: the current version is the draft, else the latest submitted (spec Always). |
| 8 | blind | The list page runs the batch queries twice | low | reject | One extra batched round per page, no N+1; reusing them means adding parameters. |
| 9 | blind | Other `current_version` callers (Red Team and run inputs) now read a submitted version | false | reject | Reviewing or assessing the current submitted Estimate is the intended reading; no write path uses it (`apply_decision` moved to `draft_version`). |
| 10 | blind | `EstimateSummary.status` typed `str` | low | patch | Direct correction to a Literal. |
| 11 | blind | Accept of an already-accepted Assumption on a submitted version is 409, not 200 | low | reject | A submitted version is immutable; the test pins it. |
| 12 | blind | Blocker anchors exist only in some render paths | low | reject | The link still opens the right tab; giving every filtered or paged branch an anchor adds complexity for a rare case. |
| 13 | blind | Duplicated `MAX_ROW_VERSION` / stale copy; a double blank line; an overview.tsx line over 100 columns | low | patch | Formatting fixes only; the duplication stays (existing pattern per module). |
| 14 | verification | No test of a submitted version's export header | low | patch | No test exports a submitted version. |
| 15 | verification | No test of a Conflict decision after submission | medium | patch | Reverting `draft_version` to `current_version` would pass every test. |
| 16 | verification | No list test with submitted v1 + draft v2 | medium | patch | The batched-count test has at most one version per Opportunity. |
| 17 | verification | `submitEstimateVersion` status mapping untested | medium | patch | Component tests mock the action. |
| 18 | verification | Blocker href anchors vs row ids not pinned | low | patch | The backend test checks only the tab and `subject_id in href`. |
| 19 | verification | Migration 0044 (was 0043) downgrade untested | low | defer | Rollbacks are on the excluded prod-hardening track; 0042 has a migration test to copy. |
| 20 | edge | A decision on a submitted version reports `no_line` | low | reject | The message is imprecise but nothing changes; a new enum value adds surface. |
| 21 | edge | Partial blockers body without `to_submit`/`to_baseline` crashes the provider | false | reject | The API always returns both arrays (typed response model); the layout guard already covers a failed read. |
| 22 | edge | An in-flight `load()` can overwrite a newer server `initial` | low | patch | Confirmed in `submission-context.tsx`; a one-line bump of `reads.current`. |
| 23 | edge | The 409 schema claims `blockers` on every 409 | low | patch | `estimate_version_not_draft` has none; make it optional. |
| 24 | edge | 428/422 shows "platform is not reachable" | low | reject | The client always sends If-Match from the read; unreachable in normal use. |

## Verification

- Work only inside the worktree `D:/Projects/Office/pre-sales-agent-86` (branch `task/story-8-6-submission-blockers`); never touch the main checkout or the dev `psa` DB. Test DB `psa_test86` exists. Build both URLs from `.env` (grep those two vars only, never `source .env`), swapping the host and DB for `127.0.0.1:5432/psa_test86`. The full suite takes about 16 minutes, so run the targeted tests first. Hand-format web code at about 100 columns; don't use Prettier. Don't commit.

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1:5432/psa_test86> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1:5432/psa_test86> uv run pytest` -- expected: all pass
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
