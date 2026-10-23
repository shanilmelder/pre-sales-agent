---
title: 'Story 17.3a: Empty-tab card, InlineAlert and Sources, Requirements, Gaps refit'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: '36b763937a293914a52cf5daa96cf68f0c001ead'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-1c-migrate-pills-and-chips.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Sources, Requirements and Gaps tabs show a plain sentence when empty, hand-roll `rounded-md border` boxes instead of cards, and have no shared inline alert. Sources rows use dense `py-1.5` cells (Story 17.3, UX-DR6, UX-DR8, UX-DR20, UX-DR26, UX-DR29).

**Approach:** Add two shared primitives, an empty-tab card and an inline alert, then refit the three tabs onto them and onto `ui/card`. Behaviour does not change. Conflicts, Estimate, Trace (17.3b) and Assessments (17.3c) are deferred.

## Boundaries & Constraints

**Always:** Empty-tab card = centred `Card`, title, one sentence, one primary button that jumps to the fixing tab (or opens the file chooser for Sources). Copy, verbatim from EXPERIENCE State Patterns: Sources "No Sources yet" / "Add an email, transcript or document. Requirements and Gaps are extracted from Sources." / **Choose files**; Requirements "No Requirements yet" / "Requirements appear after the first Source is parsed." / **Add a Source**; Gaps "No Gaps" / "Gaps appear after Requirements are checked against Checklists." / **Open Requirements**. Inline alert = `role="alert"`, red-tint, lead line, detail, actions **Reload** and optional **View diff** (shown only on Requirements, where `requirement-diff.tsx` exists); focus still moves to Reload as today. Rows use `min-h-row` (padded). Pills already use `Pill`; keep. Type classes outside `cn()`; reuse `ui/card`, `ui/button`. Existing tests pass with updated selectors only.

**Never:** Touch Conflicts, Estimate, Trace, Assessments, the shell, tokens or `ui/*` primitives other than adding the two new files; change any state machine, API call, polling or 412 logic; build a diff for Gaps; show an empty card while loading, detecting or failed (the existing branches stay); add toasts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No Sources | `sources.length === 0` | Empty card with **Choose files** | N/A |
| No Requirements | Pre-extraction empty (`NO_REQUIREMENTS`) | Empty card with **Add a Source** to Sources tab | N/A |
| Extraction found none | Finished, 0 found | Keeps "No Requirements were found in N Sources." (not the card) | N/A |
| No Gaps, detection succeeded | `succeeded`, 0 items | Keeps "No Gaps were found in the Requirements." | N/A |
| No Gaps, not run | Not detecting, not failed | Empty card with **Open Requirements** | N/A |
| Stale save | 412 on Requirements | Inline alert with Reload and View diff | Reload refetches |
| Stale save | 412 on Gaps | Inline alert with Reload only | Reload refetches |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/ui/` -- add `empty-tab-card.tsx` (title, body, action label, `href` or `onClick`) and `inline-alert.tsx` (`tone`, lead, children, `onReload`, optional `onViewDiff`), each with a test. Model on `ui/card.tsx`.
- `components/opportunities/sources-list.tsx` (~118, table at ~120) -- `NO_SOURCES` branch to the card; `py-1.5` cells to padded `min-h-row`; wrap the table in `Card`. `lib/sources.ts:32` copy.
- `components/opportunities/requirements-list.tsx` (~1461 `NO_REQUIREMENTS`; stale notice ~1332; pending-change boxes) -- card for the pre-extraction empty state; swap the stale notice to `InlineAlert` with `requirement-diff`; boxes to `Card`. `lib/requirements.ts:175`.
- `components/opportunities/gaps-list.tsx` (~1340 `NO_GAPS`; stale notice ~1307) -- card for the not-run empty state; stale notice to `InlineAlert` (Reload only). `lib/gaps.ts:242`.
- `lib/workspace.ts:30` `tabHref(id, slug)` -- jump targets.
- Tests to update: `sources-list`, `requirements-list*`, `gaps-list*`, `app/opportunities/pages.test.tsx:1036`, `source-upload.test.tsx:85,102`.

## Tasks & Acceptance

**Execution:**
- [x] `ui/empty-tab-card.tsx`, `ui/inline-alert.tsx` + tests -- the two primitives, axe clean
- [x] `sources-list.tsx`, `lib/sources.ts` + tests -- card, padded rows, empty card
- [x] `requirements-list.tsx`, `lib/requirements.ts` + tests -- card surfaces, empty card, `InlineAlert` with View diff
- [x] `gaps-list.tsx`, `lib/gaps.ts` + tests -- empty card, `InlineAlert`
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given an Opportunity with no Sources, Requirements or Gaps, when each tab renders, then it shows the empty-tab card with the copy and button above.
- Given a 412 on Requirements or Gaps, when the message shows, then it is an inline alert with Reload, plus View diff on Requirements.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Empty card button never verified through SourcesSection to the file input | medium | patch | Wiring only tested with a mock; added a SourcesSection test (click reaches input, no button when `canAdd` is false). |
| `reloadRef` forwarding untested on `InlineAlert` | low | patch | Added a ref test; covers Requirements and Gaps. |
| `tone` prop declared, never read | low | patch | Removed the dead prop. |
| `NO_*` constants still documented as "the empty-state sentence" | low | patch | Comments updated to say title, with `_BODY` named. |
| Double announcement from `role="alert"` plus shell live region | low | rejected | Spec requires `role="alert"`; fix would edit the spec's intent. |
| `aria-disabled` Reload still fires `onReload` | low | rejected | Same behaviour as before the refit; not caused by this change. |
| Two "Choose files" buttons on empty Sources | low | rejected | Card button is spec-mandated and opens the same chooser; tests now scope the query. |
| Requirements and Gaps card buttons not permission-gated | low | rejected | Spec says the button jumps to the fixing tab; the target tab is viewable. |
| `min-h-row` on `<tr>` has no effect | low | rejected | Spec mandates `min-h-row` with padding; `py-3` sets row height. |
| Card wrapper not re-indented | low | rejected | Cosmetic; lint passes. |
| `EmptyTabCard` allows `href` and `onClick` together | low | rejected | Fix adds type complexity for no demonstrated caller. |
| Stale alert styled red | false | rejected | Spec says red-tint. |
| Focus lost when empty card unmounts after upload | low | rejected | Fix adds focus-management logic; no demonstrated user harm. |
