---
title: 'Redesign the Requirements tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'c4cd95f8c65501fae00258a982ab48108f0b0193'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3a-sources-requirements-gaps-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Requirements tab does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Requirements). Today it is a flat list of thin bordered rows under plain group headings, with small outline buttons, a per-row "Pending change" marker and no summary or filters.

**Approach:** Restyle the tab to the mockup: a pending-changes banner, a "Requirements" heading with counts and filter chips, and per-classification cards of padded rows with an `R<n>` tag, a status pill, Evidence chips and an origin line. The selected row expands with its actions. Use only data the API returns today. Saves, 412 handling, polling, keyboard model and announcements keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Pending-changes banner** (when any Requirement has a `pending_change`): an agent-tint `Card` with a sparkle icon tile, "{n} pending change(s) from incremental intake", then one diff block per change: a red `−` line with `R<n>` and the current text, and a green `+` line with the proposed text. Each row and the inspector keep Accept / Reject as today.
- **Heading row:** "Requirements" (`text-section`), then "{total} total · {confirmed} confirmed · {toReview} to review" in muted meta, where toReview = unconfirmed. On the right, dashed filter chips **Category** (classifications present) and **State** (Confirmed, Unconfirmed, Pending change), built on `ui/select`. Below: **Add requirement** and **Confirm all (n)** as `ui/button` outline. Filters are client-side and narrow the visible groups; j/k skip hidden rows. A filter that leaves nothing shows "No Requirements match these filters." with a **Clear filters** button.
- **Groups:** a heading "{Label}" with "{n} · {c} confirmed" in muted meta, then one `Card` with divided rows (`py-3`, `min-h-row`).
- **Row:** a muted `R<n>` tag box on the left; the text (button, inline edit as today); on the right a `Pill`: Confirmed (resolved, check), Unconfirmed (neutral, clock) or Pending change (gap, triangle). A pending-change row also gets an amber left border. Under the text: Evidence chips, then muted "· Extracted" or "· Edited by {last_changed_by.name}" or "· Added by a person" (no Evidence). Unconfirmed rows show a small primary **Confirm** under the pill.
- **Decision 1 — banner is read-only:** no bulk Accept/Reject. Each change in the banner has a **Review** link that selects that Requirement and opens its inspector, where Accept / Reject already live.
- **Selected row:** agent-tint background and a row of small outline buttons **Edit** (inline edit), **Split** (opens the inspector's split form) and **Merge**.
- **Decision 2 — no checkbox column:** the selected row's **Merge** toggles that row into the merge selection (same as `x`, label "Merge" / "Selected for merge" with `aria-pressed`). Checked rows show a subtle check marker. The existing "n selected / Merge n / Clear selection" toolbar appears at 2+.
- **Decision 3 — inspector restyled:** a meta line "{Category} · R<n> · {origin}", the text in bold title size (click-to-edit as today), the status pill, an uppercase muted "EVIDENCE" label over the chips and the passage in a muted rounded box, then an uppercase "ACTIONS" block: full-width primary **Confirm requirement** (only when unconfirmed and editable) over a 3-column row **Edit** / **Split** / **Merge**; classification select, pending change view and **Delete** (a quiet destructive text button) stay, with forms behaving as today.
- Existing tokens and `ui/*` primitives only; light and dark both work; reduced motion respected.

**Never:** Show data the API lacks: confidence (pill, filter or inspector), agent names ("Extracted by Clarification Agent"), the source filename in the banner. Change any API call, request order, 412 or polling logic. Touch other tabs, the shell, the right-pane tabs, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mixed list | 3 confirmed, 1 unconfirmed, 1 pending | "5 total · 3 confirmed · 2 to review"; 3 green, 1 grey, 1 amber pill; banner with 1 change | N/A |
| No pending changes | none pending | No banner | N/A |
| Viewer | `can_edit_requirements` false | No Add, Confirm, Confirm all, Edit, Split, Merge | N/A |
| Filter: State = Confirmed | as above | Only confirmed rows; empty groups hidden | N/A |
| Filter leaves none | Category = Commercial, none present in state | Empty-filter sentence + Clear filters | N/A |
| Human-added | `origin` human, no Evidence | "· Added by a person", no chips | N/A |
| Stale save | 412 | InlineAlert with Reload / View diff as today | Reload refetches |
| Empty / extracting / failed | as today | Existing branches unchanged | as today |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/requirements-list.tsx` -- `RequirementsList` (153-366) rows and groups: restyle; add filter props (`visibleIds` or filtered `items`) while keeping the roving tab stop valid; selected-row actions. `RequirementsSection` render (1299-1491): heading row, filters state, banner, buttons to `ui/button`. Keep `ExtractionStatus`, `RequirementDraftForm`, all handlers (`save`, `confirm`, `confirmAll`, `decide`, `split`, `merge`, `create`).
- `components/opportunities/requirement-inspector.tsx` -- `EvidenceChip` (42) reused in rows; `PendingChangeMarker` (101) replaced by the row pill; `RequirementDiff` lines reused for the banner if it fits; `RequirementInspector` (463-696) restyle per Decision 3 (its Merge toggles the row's selection); its `SplitForm` must be openable from the row's Split (add an `initialMode`/focus request).
- `components/opportunities/requirement-diff.tsx` -- reuse the `−`/`+` tints for banner lines.
- `lib/requirements.ts` -- add `requirementState(item)` ("confirmed" | "unconfirmed" | "pending"), `requirementCounts(items)`, `groupSummary`, `originLine(item)`, filter helpers; reuse `groupRequirements`, `classificationLabel`, `requirementLabel`.
- `components/ui/` -- `button`, `card`, `pill`, `chip`, `select` (dashed chip trigger via `className`), `empty-tab-card`, `inline-alert`. Do not modify them.
- Tests: `requirements-list.test.tsx`, `requirement-edits.test.tsx`, `requirement-lifecycle.test.tsx`, `requirement-pending-change.test.tsx`, `requirement-inspector.test.tsx`, `lib/requirements.test.ts`, `app/opportunities/pages.test.tsx` (update selectors only where markup changed).

## Tasks & Acceptance

**Execution:**
- [x] `lib/requirements.ts` + tests -- state, counts, origin line, filtering
- [x] `requirements-list.tsx` + tests -- heading, filters, banner, group cards, rows, selected-row actions
- [x] `requirement-inspector.tsx` + tests -- row-pill replaces the marker; Split openable from the row; Decision 3
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given an Opportunity with grouped Requirements and a pending change, when the tab renders at 1440px, then it shows the banner, heading with counts and filters, and grouped cards in the mockup's order and styling, in light and dark.
- Given keyboard only, when j/k, Enter, e, x, c and Esc are used, then they behave as today, including with a filter applied.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Hidden rows stay in the merge selection; Merge (N) merges rows the filter hides (blind, edge, verification) | medium | patch | `items={shown}` narrows only the list; `checked` is built from `list.items`. |
| Counts treat a confirmed Requirement with a pending change as confirmed while its pill and the State filter say Pending change (blind x2, edge x2, verification) | low | patch | `requirementCounts` uses `confirmed_at`; `requirementState` ranks pending first. |
| Selected-row Edit / Split / Merge are Tab stops inside the one-Tab-stop grid (blind, edge) | low | patch | Default `tabIndex`; the row Confirm and chips use `-1`; spec keeps the keyboard model. |
| Banner Review opens a Requirement the filters hide, so no row is selected (blind, edge) | low | patch | `onReview` calls `open` without checking `shown`. |
| "Selected for merge" is announced twice on a selected, checked row (blind) | low | patch | sr-only text in the check plus the button with the same name. |
| `hasFilters` exported and tested but unused (blind) | low | patch | No caller outside the test. |
| Import order out of alphabetical order (blind) | low | patch | `MERGE`, `originLine` in the inspector import; new names in `requirements.test.ts`. |
| Category option kept after its last Requirement goes is untested (verification) | low | patch | Pre-verified: no test covers the push-back block. |
| Split request cleared on open and on pane close is untested (verification) | low | patch | Pre-verified: no test re-opens a row after a row Split. |
| Banner classification-change line is never asserted (verification) | low | patch | Pre-verified. |
| "Edited by" names whoever changed it last, which may be the confirmer (edge) | low | rejected | The frozen intent specifies `last_changed_by.name`; the API has no separate editor field. Raised with the user. |
| Focus drops to body when a confirmed row leaves a State = Unconfirmed filter (blind, edge) | low | rejected | The row Confirm is pointer-only (`tabIndex=-1`); focus management adds branches for a rare keyboard path. |
| Merge toggle not disabled while locked (blind, edge) | low | rejected | Toggling only changes the client selection; the Merge (N) action itself is disabled while locked, as with the old checkbox and `x`. |
| Confirm all also confirms rows the filters hide (blind) | low | rejected | The button states its count of the whole list, as today. |
| "Added by a person" can be wrong for a human Requirement with no Evidence (blind) | low | rejected | Same heuristic as the old "Manual"; the API defines human + no Evidence as created by a person. |
| Tests assert on class strings (blind) | low | rejected | No demonstrated harm. |
| Banner unbounded, "from incremental intake" wording, title is a `<p>` (blind) | low | rejected | Pending changes only come from incremental intake (Story 2.7); the region is labelled. |
| Checkbox column removed (edge) | false | rejected | Decision 2 in the frozen intent. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare with the mockup.
