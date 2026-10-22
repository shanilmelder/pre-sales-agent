---
title: 'Story 17.3b: Conflicts, Estimate and Trace refit onto the empty-tab card and InlineAlert'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: '563da77f6e327aac6748d556950e69dd7aadfbdc'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3a-sources-requirements-gaps-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Conflicts, Estimate and Trace tabs show a plain sentence when empty, hand-roll `rounded-md border` boxes, and show their 412 messages as a plain paragraph with a Reload button (Story 17.3, UX-DR6, UX-DR8, UX-DR20, UX-DR26, UX-DR29).

**Approach:** Reuse the `EmptyTabCard` and `InlineAlert` from Story 17.3a. Refit the three tabs and the assumptions register onto them and onto `ui/card`. Behaviour does not change. Assessments is 17.3c.

## Boundaries & Constraints

**Always:** Empty-tab card copy, verbatim from EXPERIENCE State Patterns: Conflicts "No Conflicts detected" / "Conflicts appear when Assessments or Sources disagree." / **Open Assessments**; Estimate "No Estimate yet" / "Run Assessments to produce Estimate v1 from the confirmed Requirements." / **Run assessment**; Trace "No trace events" / "Decisions and Evidence are recorded here as work happens." / **Open Overview**. All three buttons are links built with `tabHref`; **Run assessment** opens the Assessments tab and does not start a run. Stale (412) notices on Conflicts, Estimate lines and the assumptions register become `InlineAlert` with **Reload** only, keeping each existing message as the lead and the existing reload behaviour. The estimate grid wrapper, assumptions groups and "Unconverted Gaps" note become `Card`. Pad the estimate editor cells and `effort-comparison` cells (`py-1.5`/`py-1` to padded). Type classes outside `cn()`; reuse `ui/card`, `ui/button`. Existing tests pass with updated selectors only.

**Never:** Touch Sources, Requirements, Gaps, Assessments, Overview (`NO_ESTIMATE_YET`, Overview's `NO_EVENTS` use), the shell, tokens or `ui/*`; change any state machine, API call, polling or 412 logic; build a diff for Conflicts, Estimate or Assumptions; show an empty card while building, loading or failed, or in a filtered-empty Trace; add an empty card to the assumptions register; add toasts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No Conflicts | `conflicts.length === 0` | Empty card with **Open Assessments** link | N/A |
| No Estimate | No version, not building | Empty card with **Run assessment** link to Assessments | N/A |
| Estimate building | `building` | No card; existing building text | N/A |
| Run finished, nothing to estimate | Existing `NOTHING_TO_ESTIMATE` state | Keeps its sentence, not the card | N/A |
| No trace events | `page.total === 0`, no filters | Empty card with **Open Overview** link | N/A |
| Trace filtered to zero | Filters set, no matches | Keeps "No events match these filters." and Clear filters | N/A |
| Stale save | 412 on a Conflict, Estimate line or Assumption | `role="alert"` `InlineAlert` with Reload, no View diff | Reload refetches as today |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/conflicts-list.tsx:168` -- empty branch to `EmptyTabCard`; `lib/conflicts.ts:20` copy. Rows already `min-h-row`.
- `components/opportunities/conflict-inspector.tsx:147,257-267` -- position box to `Card`; stale `notice` plus Reload to `InlineAlert` (keep `router.refresh()`, `RELOAD`, GONE text).
- `components/opportunities/estimate-grid.tsx:431,384-420,434,956` -- grid wrapper to `Card`; per-line stale row to `InlineAlert` (`reloadEstimate`); pad `py-1.5` cells; empty branch to card (keep the `!building` guard; `NO_ESTIMATE` is also an announce string at ~830, so add new constants and keep that one). `lib/estimates.ts:100`.
- `components/opportunities/effort-comparison.tsx:26,110-152` -- pad `py-1` cells.
- `components/opportunities/assumptions-register.tsx:345-358,363,386` -- stale notice to `InlineAlert`; groups wrapper and Unconverted Gaps note to `Card`. Leave the inline "No Assumptions for this version." text.
- `components/opportunities/trace-list.tsx:474-493` -- `total === 0` unfiltered branch to card; list in `Card`. `lib/trace.ts:12` `NO_EVENTS` is also used by `overview-summary.tsx:432`: add new title constants, do not change it.
- Reuse `ui/empty-tab-card.tsx`, `ui/inline-alert.tsx`, `lib/workspace.ts:30` `tabHref` (slugs `assessments`, `overview`).
- Tests to update: `conflicts-list.test.tsx:170`, `conflict-inspector.test.tsx:266-282`, `estimate-grid.test.tsx:454-475,884-930`, `assumptions-register.test.tsx:322-336`, `trace-list.test.tsx:364`, `app/opportunities/pages.test.tsx:1225,1717,1757`. Keep `pages.test.tsx:699,701,923` (Overview) passing unchanged.

## Tasks & Acceptance

**Execution:**
- [x] `conflicts-list.tsx`, `conflict-inspector.tsx`, `lib/conflicts.ts` + tests -- empty card, `Card`, `InlineAlert`
- [x] `estimate-grid.tsx`, `effort-comparison.tsx`, `lib/estimates.ts` + tests -- empty card, `Card` wrapper, padded cells, `InlineAlert`
- [x] `assumptions-register.tsx` + tests -- `InlineAlert`, `Card` groups
- [x] `trace-list.tsx`, `lib/trace.ts` + tests -- empty card for the unfiltered zero state, `Card`
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given an Opportunity with no Conflicts, no Estimate or no trace events, when each tab renders, then it shows the empty-tab card with the copy and link above.
- Given a 412 on Conflicts, an Estimate line or an Assumption, when the message shows, then it is an inline alert with Reload.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

(Implementation note: the matrix row "Run finished, nothing to estimate" has no code path; `NOTHING_TO_ESTIMATE` in `lib/estimates.ts` is unused. Nothing to test or change.)

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `NO_CONFLICTS` left unused | low | patch | No importer; constant deleted. |
| Trace row focus ring clipped by the Card's `overflow-hidden` | low | patch | Row button ring is outside its box; now `ring-inset`. |
| Trace page beyond the last page renders nothing | medium | defer | Pre-existing branch, not changed here; recorded in deferred-work. |
| Estimate empty card shows after a failed run | low | rejected | Same condition showed the plain sentence before; an existing test expects the empty state. |
| Reload clickable while a reload runs (Estimate, Assumptions, Conflicts) | low | rejected | Same as before the refit. |
| Stale Estimate alert falls back to a paragraph without `onReload` | low | rejected | Pre-existing fallback; the grid always passes `onReload`. |
| "Run assessment" only links; no permission check; "Estimate v1" hardcoded | low | rejected | Copy and link target are the spec's. |
| `cardClass` overrides Card styling in the inspector | low | rejected | Visual only; fix is a new Card variant. |
| `effort-comparison` padding repeated and unrelated | low | rejected | The spec asks for it; no drift shown. |
| Tests lock in no View diff | low | rejected | Spec decision; matches 17.3a. |
| Missing axe checks on Estimate and Trace empty cards | low | rejected | Card is covered by its own axe test; Conflicts and Estimate empty tests already run axe. |
| Narrow alert in Estimate editor row | low | rejected | Cosmetic. |
