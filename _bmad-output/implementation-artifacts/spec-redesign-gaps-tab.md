---
title: 'Redesign the Gaps tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'f3405b6dcd9179693bc762fc7ade3b7d606d5f7f'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-sources-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Gaps tab does not match the new mockup (`_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Gaps, `isGaps` and `paneGap`). Today it is a dense 32px list with tiny outline buttons, a neutral impact bar and a plain inspector stack.

**Approach:** Rebuild the main column as the mockup's header row plus one table card, and restyle the right-pane inspector into the mockup's sections. Use only data the API returns today. Detection status and polling, SSE, multi-select, approve, mark sent, export, record answer, impact change, dismiss, reopen, stale/412 handling, keyboard and focus keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Header row** (wraps): `h2` "Gaps" (section type) and a muted "{N} total · {M} open · ranked by impact", then a spacer, then the existing actions restyled with `ui/button` (outline, small): **Approve N selected** / **Approve all (N)**, **Mark N selected sent** / **Mark all sent (N)**, and the Export menu, whose trigger reads **Export questions**. Same visibility rules as today. `DetectionStatus`, the mark-sent form and the stale/notice alert sit under the header, unchanged in behaviour.
- **Filters** (decision: client-side; "Saved views" omitted). Three buttons, **Impact**, **Area** and **Question status**, sit between the spacer and the actions. Each is dashed-border, muted, with a chevron, and opens a `ui/popover` with radio options:
  - **Impact:** Any, High, Medium, Low.
  - **Area:** Any plus the categories present in the list.
  - **Question status:** Any plus Draft, Approved, Sent, No answer, Answered.
  - An active filter's trigger reads "Impact: High" with a solid border. Filters combine with AND, are not persisted, and do not reorder rows.
  - While any filter is active, the summary appends " · showing K", and a ghost **Clear filters** button appears.
  - Changing a filter drops checked rows that are no longer shown. Approve all, Mark all sent and Export still cover every Gap, as today.
  - If no rows match, the card shows "No Gaps match these filters." with **Clear filters**.
  - The opened Gap stays in the inspector even when it is filtered out.
- **Table card** (`Card`, `overflow-hidden`): a header row on `bg-surface-alt` with meta labels: (blank), "Impact", "Gap · affected area · trigger", "Question". Grid `28px 112px minmax(0,1fr) 120px`, gap 12, padding 8×16. Below `md` the header hides and rows stack. The card keeps `role="grid"` and the current roving tabindex, j/k/arrows, x, e, Esc.
- **Row** (same grid, `items-start`, padding 12×16, top border):
  - **Col 1:** the checkbox (only with select rights), 18px, rounded, primary when checked. Same label and `x` behaviour.
  - **Col 2:** `ImpactBar` coloured by impact: High `blocker`, Medium `gap`, Low `neutral`; unlit bars `border-strong`; label medium weight.
  - **Col 3:** the open button with the title (medium weight, wraps) and a meta line "{category} · " followed by a primary-tint pill with a sparkle icon reading "Clarification Agent". The answered / possible-answer meta stays after it.
  - **Col 4:** `QuestionPill` with mockup colours (Draft neutral, Approved resolved, Sent primary, No answer gap, Answered resolved); converted and dismissed rows keep their neutral pills.
  - **State:** selected → `bg-primary-tint`; else an open High-impact Gap gets `bg-blocker-tint` and a 3px inset left bar in `blocker`. Converted and dismissed rows stay greyed. The whole row is clickable through the open button's stretched hit area (one Tab stop per row).
- **Key hints** under the card as one meta line: "j / k move · x select · Enter open · e edit question · ] inspector", leaving out terms the viewer lacks rights for.
- **Inspector sections**, each padded 16 with a bottom border; headings are uppercase meta labels.
  - **Header:** "{Impact} impact" in the impact colour, then "· {category}" muted, the `GapStatusPill` on the right, and the title in section type.
  - **Why it matters:** the text, then the trigger pill.
  - **Related Requirements:** an id chip and the excerpt.
  - **Clarification Question:** the pill beside the heading. The existing click-to-edit topic and text sit in a bordered box on the page background. The caption is `statusSince` plus "Press e to edit." when editable.
  - **Actions:** the status's primary action as a primary `ui/button`, with a muted flow line under it:
    - Draft → **Approve question** / "Draft, then Approved, Sent and Answered."
    - Approved → **Mark as sent** (opens the existing date form) / "Approved. Export it, send it to the customer, then mark it sent."
    - Sent or No answer → **Record answer** (opens the existing form), plus outline **No answer** for Sent / "Sent. Record the customer answer to close this Gap."
    - Answered → "Answered. Related Requirements have proposed updates."
    - Dismissed → "Dismissed with a reason."
    - Reopen keeps its required-reason form, styled as an outline button.
  - **Suggested answers** and the answer section: restyled only.
  - **Change impact:** restyled.
  - **Dismiss** box: bordered, rounded. It keeps the reason kind and note, and its button uses blocker text.
  - **History:** restyled.
- The empty and "none found" states keep `EmptyTabCard` and their copy. Existing tokens and `ui/*` primitives only. Light and dark both work.

**Never:**
- Data the API lacks: confidence, "Blocks submit", checklist ids in the trigger, the Requirement source chip, "Saved views", server-side filtering.
- The "Convert to Assumption" box: conversion stays on the Estimate (Epic 8), and there is no Gaps-tab API.
- An always-open question textarea.
- Changes to API calls, SSE, polling, permissions logic, other tabs, the shell, tokens or `ui/*`.
- Changing `ImpactBar`'s neutral default, which the Assumptions register uses.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mixed list | 5 Gaps, 3 open, one open High | Header "5 total · 3 open · ranked by impact"; the High row has the red tint and left bar | N/A |
| Selected High row | Open High Gap opened | Primary tint wins over red tint | N/A |
| Sales rep | `can_edit_questions` false, `can_send_questions` true | No Approve; Mark sent and Export shown; hints omit `e` | N/A |
| Viewer | No rights | No checkbox column (grid drops col 1), no actions, hints "j / k move · Enter open · ] inspector" | N/A |
| Draft question | Editable | Inspector primary "Approve question" | Failure → existing notice |
| Dismissed Gap | `can_edit_gaps` | Greyed row, "Dismissed · …" pill; inspector flow line and Reopen form | N/A |
| Impact filter | Impact: High, 1 of 5 matches | One row; summary "5 total · 3 open · ranked by impact · showing 1"; trigger "Impact: High" | N/A |
| Filter hides checked row | g2 checked, filter excludes g2 | g2 unchecked; "Approve N selected" recounts | N/A |
| No match | Filters exclude all | "No Gaps match these filters." + Clear filters restores all rows | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/gaps-list.tsx`
  - `GapsList` (~149-345): the table card, header row and grid rows. Keep `rowItem`, `onKeyDown` and the `data-gap-row`/`data-gap-id` attributes.
  - `GapsKeyHints` (~349): becomes the single meta line.
  - `GapsSection` (~1236-1393): the header row layout, plus filter state. It passes `filterGaps(list.items, filters)` to `GapsList`, and on a filter change it prunes `checked` to the visible ids. All other state and handlers stay as they are.
- `components/opportunities/gaps-filters.tsx` (new): the filter triggers on `components/ui/popover.tsx`, with radio options.
  - Swap `actionClass` buttons for `ui/button`.
- `components/opportunities/gap-inspector.tsx`
  - `GapInspector` (~102-360): sections and the Actions block.
  - `QuestionPill` (~55): tones per status.
  - Restyle the forms (`MarkSentForm`, `RecordAnswerForm`, `ImpactForm`, `DismissForm`, `ReopenForm`) without changing their behaviour.
- `components/opportunities/impact-bar.tsx`: add an optional `coloured` prop (bars and label in the impact tone). The default stays neutral for `assumptions-register.tsx`.
- `components/opportunities/questions-export.tsx`: the trigger label becomes "Export questions", as an outline `ui/button`. The menu stays unchanged.
- `lib/gaps.ts`:
  - `gapsSummary` → "{N} total · {M} open · ranked by impact".
  - `QUESTION_STATUSES` tones per the mockup.
  - Add `impactTone(impact)` and `questionFlow(status)` for the flow lines.
  - Check `pillToneFor` in `lib/pill-tone.ts` maps `text-primary`.
- Tokens: `blocker`/`blocker-tint`, `gap`, `neutral`, `resolved`, `primary-tint`/`primary-text`, `surface-alt`, `border-strong`.
- Reuse the Sources card header pattern from `sources-list.tsx:163-170`.
- Tests: `gaps-list.test.tsx`, `lib/gaps.test.ts`, `app/opportunities/pages.test.tsx`, and the `impact-bar` / assumptions tests if they assert classes. Update selectors that relied on the old header labels or button text ("Export", "Approve", "Mark sent").

## Tasks & Acceptance

**Execution:**
- [x] `lib/gaps.ts` + test -- summary copy, tones, `impactTone`, `questionFlow`, and a pure `filterGaps(items, filters)` with its option lists
- [x] `components/opportunities/gaps-filters.tsx` (new) + test -- the three popover filters and Clear filters
- [x] `impact-bar.tsx` -- `coloured` prop
- [x] `gaps-list.tsx` + tests -- header row, table card, rows, hints
- [x] `questions-export.tsx` -- trigger restyle and label
- [x] `gap-inspector.tsx` + tests -- sections, Actions block, form restyle
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given an Opportunity with Gaps, when the tab renders at 1440px, then it matches the mockup's order and styling in light and dark.
- Given a row, when it is clicked anywhere or activated with Enter, then the inspector opens as today, and focus returns to the row when the pane closes after a keyboard open.
- Given lint, typecheck, tests and build, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Checked rows hidden by a later list change (approve, SSE, impact edit) stay checked; bulk "selected" actions hit invisible rows (blind, edge) | medium | patch | `checkedIds` is built from `list.items`; `changeFilters` prunes only on a filter change. |
| Row lost its status icon and sr-only status label (blind, edge) | low | patch | Open vs answered is no longer in the row's accessible name; a one-line sr-only span restores it. |
| Checked-but-not-opened rows lost their row tint (blind, edge) | low | patch | The `state` ternary has no `checked` branch; the old `bg-muted/40` was dropped. |
| Focus is lost when the pane closes and the opened Gap is filtered out (edge) | low | patch | `querySelector([data-gap-id])` finds nothing; the AC promises a return to the row. |
| Filter trigger hard-codes `text-[13px] leading-[1.4]` instead of `text-control` (blind) | low | patch | The token exists with the same values. |
| No test of the level-2 "Gaps" heading on the empty and failed-read paths (verification) | low | patch | Pre-verified: `pages.test.tsx` empty and failed tests assert only the text. |
| Approve all, Mark all sent and Export act on hidden Gaps (blind, verification) | false | rejected | Frozen decision: "Approve all, Mark all sent and Export still cover every Gap, as today." |
| Esc hint dropped; hints show single-key shortcuts even when they are off (blind, edge) | false | rejected | Hint copy is frozen; the old hints also showed j/k regardless of the setting. |
| "Press e to edit." works only on a focused row (blind, verification) | low | rejected | Copy is frozen; the fix edits the spec. |
| Answered flow line claims updates even with no requirement changes; the No answer line reads "Sent" (blind, verification) | low | rejected | Copy is verbatim from the frozen spec. |
| Actions heading and Approved flow line shown to read-only viewers (blind, edge) | low | rejected | The spec's Actions section always carries the flow line; cosmetic. |
| Primary tone hand-rolled instead of a Pill `primary` variant (blind) | low | rejected | The spec forbids changes to `ui/*`. |
| Urgent rows have no hover state (blind) | low | rejected | Cosmetic; the tint already marks them. |
| Tests replaced `user.tab()` with direct focus; Tab order changed (blind, edge) | false | rejected | The frozen spec puts the filters and actions before the grid; the grid stays one roving Tab stop. |
| `min-h-row` assertion removed; no `coloured` low ImpactBar test; no axe contrast (blind) | low | rejected | Row height changed by design; the other two carry no demonstrated harm. |
| Roving tab stop when the focused row is filtered out (blind) | false | rejected | `tabStopId` falls back to the first shown row. |
| Area trigger shows the raw key when its category leaves the list (edge) | low | rejected | Categories leave only on re-detection; a fix adds plumbing. |
| Selection shrink not announced (edge) | low | rejected | Rare; adds a branch. |
| `EXPORT_QUESTIONS` lives outside `lib/gaps`; no Gap-status filter; dismissal details under Actions (blind) | low | rejected | No named harm; the status filter is outside the decided filters. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab and the inspector in light and dark at 1440px, and compare them with the mockup.
