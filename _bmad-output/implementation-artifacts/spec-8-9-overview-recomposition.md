---
title: 'Story 8.9: Overview recomposition'
type: 'feature'
created: '2026-10-26'
status: 'done'
baseline_commit: '92325ed2cd1c8169826b873b8b839ba71acf47f2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-6-submission-blockers.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Overview (redesigned earlier) has a 7-step pipeline that decides "Blocked" with its own browser rules. It uses "Not started" and "Unknown" states, its steps don't link anywhere, and it only re-renders on navigation. So it can disagree with the Submission blockers check (AD-27) and go stale.

**Approach:** Recompose the Overview to the new mockup (`new-mockups/…standalone.html`, Overview section). The pipeline gets 8 steps and the states Complete, In progress, Blocked and Pending. Every Blocked state comes from the API's blockers view, which is the same view the card, badge and header read. Each step links to its tab, and the Overview refreshes live over SSE. This is web-only: no backend, API or migration change.

## Boundaries & Constraints

**Always:**
- **Layout (already matches the mockup, keep it):** KPI row (4 tiles); Pipeline beside Needs you (`1.4fr/1fr`); Blockers beside Recent activity; Latest agent decision; Agent run.
- **Pipeline steps, in order (step → tab):**
  1. Sources added → sources
  2. Requirements extracted → requirements
  3. Requirements confirmed → requirements
  4. Gaps answered → gaps
  5. Assessments run → assessments
  6. Conflicts resolved → conflicts
  7. Estimate accepted → estimate
  8. Review and Baseline → estimate
- **States:** `complete | in-progress | blocked | pending`. Each shows its pill (icon plus text: Complete/check, In progress/loader, Blocked/circle-alert, Pending/clock) and its mockup node (green ✓, primary numbered, red numbered, neutral numbered). Colour is never the only signal.
- **One rule (decision):** a step is **Blocked only when the blockers view has items for it**, and never otherwise:
  - Gaps answered: `gap` items. Sub: "3 open, 2 High".
  - Assessments run: `finding` items. Sub: "N critical Findings".
  - Conflicts resolved: `conflict` items. Sub: "2 open".
  - Estimate accepted: `assumption` items, then `uncovered_requirement` items. Sub: "2 Assumptions not accepted" or "1 Requirement not covered".
  - Without blockers for a step, the reads set Complete, In progress or Pending. A failed parse, a failed extraction, a failed or waiting run, or a failed draft is **In progress** with the failure as its sub-line. The mockup does this too ("Run 2 stopped at token limit").
  - Requirements confirmed is never Blocked.
  - A failed read gives Pending with "… could not be loaded". This includes a failed blockers read for the steps that depend on it.
- **Review and Baseline (decision):**
  - No version, or a draft with to-submit blockers: Pending, "Starts when blockers clear".
  - A draft with none: Pending, "Starts after you submit".
  - Submitted with an empty `to_baseline`: Pending, "No Review Request sent yet".
  - `in_review` or a non-empty `to_baseline`: In progress, "N Review Requests pending".
  - Never Complete until Story 9.7 (Baseline).
- **Blockers source:** the pipeline reads `useSubmission()?.view` when a provider is above, falling back to `data.blockers`. It is therefore a client component, and it changes on the same frame as the card and badge.
- **Footer:** "2 of 8 steps complete" and "3 steps blocked" (mockup: two spans plus a segmented bar). Screen readers read them as "2 of 8 steps complete · 3 steps blocked".
- **Links:** each step's title is a link to its tab. The mockup has no chevron, so add none. Nothing is disabled or ordered by an earlier step: the pipeline is a status tracker.
- **Live:** `OverviewLiveRefresh` replaces `GapsLiveRefresh` on the Overview. It calls `router.refresh()`, debounced to about 300 ms and skipping each hook's first connect callback. It runs on progress events, `gaps.changed`, `conflicts.changed`, blocker frames, source events and review events.
- **Mockup touch-ups:**
  - The Conflicts KPI pill reads "Blocks submit" when there are `conflict` blocker items.
  - The Estimate KPI label is "Estimate · v3 draft" or "Estimate · v3 submitted".
  - Agent run tasks use a 3-column grid.

**Never:**
- No pipeline or KPI rule that decides blocked-ness outside the blockers view. Delete the old browser rules. No new blocker kinds.
- No backend change.
- No Baseline Complete state.
- No mockup features without data: Needs you "Resolved today", agent-decision "Proposed next steps" and Approve question, Cancel run, Retry or Skip on the Overview, the empty-Overview dropzone.
- No Prettier (hand-format at about 100 columns).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mockup | 6/6 parsed, 9/12 confirmed, 3 gap blockers, run cancelled, 2 conflict blockers, 2 assumption blockers, draft | Complete, Complete, In progress, Blocked, In progress, Blocked, Blocked, Pending "Starts when blockers clear"; footer "2 of 8 steps complete" / "3 steps blocked" | N/A |
| Gaps open but no blocker items | Gaps list shows open Gaps, blockers view has no `gap` items | Gaps answered not Blocked (follows the view) | N/A |
| Live clear | Last conflict resolved in another tab | Conflicts step turns Complete without a reload, same frame as the card | N/A |
| Ready | Draft, 0 blockers | Steps 4–7 Complete; Review "Starts after you submit" | N/A |
| In review | Version `in_review`, 2 review_request items | Review and Baseline In progress, "2 Review Requests pending" | N/A |
| Blockers read failed | `blockers` null, no provider | Steps 4–7 Pending, "The submission blockers could not be loaded…" | Card shows its own failure |

</frozen-after-approval>

## Code Map

- `web/src/lib/overview.ts:400-470` -- `PipelineState`, step builders and `pipelineSteps` / `pipelineProgress`: change to 8 steps with `tab`, the new states, and a `blockers: SubmissionBlockersView | null` input. Keep `requirementCounts`, `gapCounts` and `conflictCounts` for sub-lines only.
- `web/src/components/opportunities/overview-summary.tsx` -- `SubmissionPipeline` (`STEP_DISPLAY`, nodes, footer) moves into a new client `overview-pipeline.tsx`. Also: KPI touch-ups (`ConflictsKpi`, `EstimateKpi`), and the `AgentRun` grid (`lg:grid-cols-4` → 3).
- `web/src/components/opportunities/submission-context.tsx:31` -- `useSubmission()` (reuse, don't change). `web/src/lib/submission.ts` -- `Blocker` kinds and `NO_REVIEW_REQUESTS` copy.
- `web/src/lib/opportunity-events.ts:265-370` -- the `useOpportunityEvents`, `useGapsEvents`, `useConflictsEvents`, `useSourceEvents`, `useBlockersEvents` and `useReviewEvents` hooks for the new `overview-live-refresh.tsx`. Use `gaps-live-refresh.tsx` as the pattern.
- `web/src/app/opportunities/[id]/overview.tsx:83` -- swap in `OverviewLiveRefresh`.
- `web/src/lib/workspace.ts` -- `tabHref`. `web/src/lib/estimates.ts` -- `VersionStatus` (`draft | submitted | in_review | superseded`).
- Tests:
  - `web/src/lib/overview.test.ts:499-580` (pipelineSteps, with 7-step expectations to update).
  - `web/src/components/opportunities/submission.test.tsx` (`FakeSource`, `SubmissionProvider` and `axeViolations` patterns).
  - `web/src/test/axe.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/overview.ts` -- 8 steps, blocker-driven Blocked, Review and Baseline, pending states, `tab` per step, footer labels -- AD-27 single rule
- [x] `web/src/components/opportunities/overview-pipeline.tsx` (new, client) -- the mockup card reading `useSubmission()` with a fallback; step title links -- UX-DR29
- [x] `web/src/components/opportunities/overview-summary.tsx` -- use the new pipeline; KPI pill and label; Agent run 3 columns -- mockup
- [x] `web/src/components/opportunities/overview-live-refresh.tsx` (new) and `app/opportunities/[id]/overview.tsx` -- debounced live refresh -- AD-30
- [x] `web/src/lib/overview.test.ts` -- every matrix row, plus Review and Baseline states
- [x] `web/src/components/opportunities/overview-summary.test.tsx` (new) -- render `OverviewSummary` in a `SubmissionProvider`: axe passes; every step has a pill with an icon and text and a link to its tab; nothing is `aria-disabled`; a `FakeSource` blocker frame flips a step live; the live refresh debounces `router.refresh`

**Acceptance Criteria:**
- Given any Overview state, when it renders, then the pipeline's Blocked steps match exactly the kinds in the blockers view the card shows.
- Given CI, when the web checks run, then lint, typecheck, tests (axe included) and build pass.

## Implementation Notes

- **Steps without blockers:** with no items of its kind, a step is Complete once the read shows it ran, even if the read still counts open items (a stale read in the "Live clear" row, or open Gaps the view leaves out). The sub-line then reads "No Gaps block submission" / "No Conflicts block submission" instead of "No open …".
- **Blocked sub-lines:** Gaps uses the Gaps read's counts ("3 open, 2 High") when it loaded, else "N open" from the view. Conflicts reads "N open" from the view.
- **Failures** (In progress): "6 of 7 parsed, 1 failed", "Extraction failed", "Gap detection failed", the run's status label ("Cancelled — completed results kept", "Waiting for you", …), "Drafting failed".
- **Conflicts KPI:** "Blocks submit" (blocker tone) with `conflict` items, otherwise "Needs a decision" (gap tone). It's a small client component (`ConflictsKpiPill`) so it follows the same live view as the pipeline.
- **Estimate KPI label:** draft / submitted / in review / superseded.
- `GapsLiveRefresh` is kept (it has its own test) but no longer used on the Overview.
- `pages.test.tsx` Overview expectations were updated to the 8 steps and new states.

- **Merge with main (Stories 9.3/9.4):** `VersionStatus` gained `approved` and `rejected`. Review and Baseline shows In progress "Approved, Baseline not set yet" or "Rejected in review" for them (still never Complete before 9.7); the KPI label words them "approved" / "rejected".

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | blind+edge | `reviewStep` reads "0 Review Requests pending" when `in_review` or `to_baseline` has no `review_request` items | low | patch | The branch is entered on status or `to_baseline` length, but it counts only `review_request`. Now reads "In review". |
| 2 | blind+edge | A `superseded` version shows "No Review Request sent yet" | false | reject | The current version is the draft, else the latest submitted or in review. A superseded version is never the view's `version`. |
| 3 | blind+edge | "Starts when blockers clear" shows with no Estimate and no blockers | low | reject | This is the frozen decision ("No version … Pending, Starts when blockers clear"). Changing it means editing the spec. |
| 4 | blind | A failed blockers read makes steps 4–8 Pending, with the message repeated | low | reject | Required by the frozen spec and the matrix row "Blockers read failed". |
| 5 | blind+edge | `useOverviewBlockers` drops the server's blockers when the provider's view is null | medium | patch | `submission ? submission.view : fallback` returns null when the layout read failed and the page read succeeded. Now uses `submission?.view ?? fallback ?? null`. |
| 6 | blind | Failures look like progress (spinner) | low | reject | Frozen decision: failures are In progress with the failure as the sub-line, as in the mockup. |
| 7 | blind | Sub-lines can differ from the card: Gaps counts, Conflicts escalated count, Estimate shows only Assumptions when both kinds exist | low | reject | Each sub-line follows the frozen copy ("3 open, 2 High", "2 open", Assumptions then uncovered). The state comes from the view. |
| 8 | blind+edge | The trailing debounce has no max wait, so refreshes could be put off during a run | low | reject | Frames arrive seconds apart, not continuously under 300 ms. A max-wait adds a branch for a case not shown to happen. |
| 9 | blind | The same frame triggers a provider reload and a router refresh | low | reject | By design: the provider updates the pipeline at once, and the refresh updates the rest. One extra read per burst. |
| 10 | blind+verification | Live-refresh test doesn't pin each hook or the timer reset | medium | patch | Verification layer demonstrated it: with `useOpportunityEvents` / `useSourceEvents` removed, or a non-resetting timer, the test still passes. Added a per-frame table test and a timing test. |
| 11 | blind+edge | `GapsLiveRefresh` and its test are now dead code | low | patch | grep shows no other user. Deleted. |
| 12 | blind+edge | `useAfterFirst` / the timer are not reset when `opportunityId` changes without a remount | low | reject | The workspace remounts per Opportunity (dynamic `[id]` segment). Guarding it adds an effect for a case not shown. |
| 13 | blind | Agent run grid changed to 3 columns | false | reject | Required by the spec (mockup touch-up). |
| 14 | blind | `SubmissionPipeline` copies `SummaryCard` | low | reject | It is a client component and `SummaryCard` is private to a server module. Extracting it is a refactor with no defect. |
| 15 | blind | The Estimate KPI label can lag the live pipeline; dead `?? version.status` fallback | low | patch (fallback) / reject (lag) | The lag lasts until the debounced refresh (~300 ms). The fallback is unreachable under the `Record` type and was removed. |
| 16 | blind | `ConflictsKpiPill` shows "Needs a decision" when the blockers read failed | low | reject | The pipeline already says the read failed. A third pill state adds surface. |
| 17 | edge | A partial read without `to_baseline` / `version` crashes `reviewStep` | false | reject | `SubmissionBlockersView` is a typed response model that always has both arrays and a nullable `version` (8.6 triage #21). |
| 18 | edge | A `to_submit` kind no step maps leaves "0 steps blocked" while Submit is blocked | false | reject | Every `to_submit` kind maps to a step. `review_request` is only ever in `to_baseline` (`estimates/application/blockers.py:14`). |
| 19 | edge | Conflicts KPI shows 0 with no pill while the live pipeline shows Blocked (stale read) | low | reject | Transient until the debounced refresh. |
| 20 | edge | Baseline blockers on the card make no step Blocked | low | reject | Frozen decision: Review and Baseline is In progress for pending Review Requests. |
| 21 | verification | `estimateKpiLabel` `in_review` / `superseded` wording untested | low | patch | Cases added to the labels test. |
| 22 | verification | Mounting `OverviewLiveRefresh` on the Overview page is not checked | low | defer | `pages.test.tsx` has no `EventSource` stub. The old mount was equally unverified. |
| 23 | verification | "Needs a decision" tone moved from blocker to gap | false | reject | Intentional: blocker red is now only for "Blocks submit". |

## Verification

Work only in `D:/Projects/Office/pre-sales-agent-89` (branch `task/story-8-9-overview-recomposition`). Don't touch the main checkout. Don't commit.

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
