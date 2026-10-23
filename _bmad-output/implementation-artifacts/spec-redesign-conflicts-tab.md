---
title: 'Redesign the Conflicts tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '8d1443233b2290e575b4eb285a1fec12021caa46'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-3-resolve-conflicts.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-overview-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Conflicts tab (Stories 6.1–6.3, refit in 17.3b) does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Conflicts). It is two plain lists of dense 32px rows ("Open", "Resolved") with type, severity and status pills, and the decision lives in the right-pane inspector as small cards.

**Approach:** Rebuild the tab body to the mockup: a "Conflicts" heading with "{n} open · {n} resolved", a card of open Conflict rows, a decision card for the selected Conflict (two big position cards, a required reason, Resolve and Escalate), and a "Resolved {n}" card. Only data the API returns today; the resolve and escalate commands, permissions, errors, live refresh and keyboard model keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Header:** `h2` "Conflicts" (16px semibold, visible) with "{open} open · {resolved} resolved" in muted 13px beside it.
- **Open card** (`ui/card` styling, rows separated by top borders, 3px red inset bar on the left): each row has the red alert icon, the Conflict `summary` as title (medium), a 12px muted sub-line "{type} · {Requirement label}" (type only when no Requirement, plus "· Detected from text" for 6.2 Conflicts), and on the right "Open" in red, or "Escalated to {name}" in amber with the up-arrow icon. The selected row gets the primary tint. Keep the roving tabindex, j/k and arrows, Enter/Space, `aria-selected`. With no open Conflicts, the card shows "No open Conflicts."
- **Decision card** (`ui/card`, 24px padding, 16px gaps): the selected Conflict's `summary` as a 16px semibold title; a note below (the type and severity in words, plus "Resolved earlier…" and the escalation line and reason when present). Then a 2-column grid (1 column below `md`; auto-fit when there are 3+ positions) of position cards: a primary-tint agent pill with the sparkle icon ("Engineering Agent", or "Estimate v3" for the Estimate), the version ("Assessment v2") in muted text, the value at 20px semibold tabular, the cited Finding's title as the basis line when there is one, and the Requirement chip as the evidence chip. When the viewer can resolve, each card is a radio (2px border; primary border and tint when chosen), plus "A different position" with its field as today. Then "Reason (required)" textarea with the count, then **Resolve** (primary) and **Escalate** (outline) on one row with a muted hint ("Choose a position, then give a reason."). Resolve keeps today's inline validation and the agents'-total note for effort Conflicts.
- **Escalate:** shown only when `can_escalate` and reviewers exist. Pressing it reveals a reviewer select beside the buttons and uses the same reason field; a second press with a reviewer sends `escalateConflict`. Validation messages as today.
- **Read-only:** when the viewer cannot resolve, or the Conflict is resolved, the cards are static (the chosen one marked "Chosen") with the decision line, reason and Estimate effect above them; no form.
- **Selection:** the first open Conflict is selected on load (else none); clicking a row (open or resolved) selects it and moves focus to the decision card's title when done by keyboard. After a decision, `router.refresh()` and the selection falls to the first open Conflict.
- **Resolved card:** header "Resolved {n}"; each row a green check icon, the summary, a muted line (the decision label, else the system reason) and a neutral tag: "Resolved by {name}" or "No longer present". Rows are selectable and show the read-only decision card.
- **Empty:** no Conflicts at all keeps the `EmptyTabCard`.
- **Placement (decided 2026-10-23: inline, as the mockup):** the decision card sits in the main pane under the open card; the right pane is not used by this tab.
- Use existing tokens and `ui/*` primitives; light and dark both work; every colour cue has an icon or text too.

**Never:** Show data the API lacks: per-position basis text other than the Finding title, Source evidence links, "Superseded by Assessment v2" tags, resolved dates beyond what the decision label holds. Change any API call, action, SSE refresh or backend. Touch other tabs, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mockup data | 2 open (effort R1, security R4), 5 resolved | Header "2 open · 5 resolved"; first row selected; decision card shows 2 position cards; Resolved 5 | N/A |
| Resolve | Pick a card, reason, Resolve | `resolveConflict` sent; refresh; row moves to Resolved | Inline 422/403/409, 412 + Reload as today |
| No choice / no reason | Resolve pressed blank | Inline errors, nothing sent | Blocked inline |
| Escalate | Escalate, pick reviewer, reason, Escalate | `escalateConflict` sent; row shows "Escalated to Sam" | As today |
| Viewer | `can_resolve` false | Static cards, no form, no buttons | N/A |
| All resolved | 0 open, 3 resolved | "No open Conflicts."; no card selected until a resolved row is picked | N/A |
| None | No Conflicts | `EmptyTabCard` | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `app/opportunities/[id]/conflicts.tsx` -- drop the `sr-only` heading (the header comes from the section); otherwise unchanged.
- `components/opportunities/conflicts-list.tsx` -- `ConflictsList` (rows, roving tabindex at :41-121) restyled to the mockup row; `ConflictsSection` (:126-232) composes header, open card, decision card and resolved card; remove `RightPaneContent`/`useShell` pane logic, keep `singleKeyShortcuts`.
- `components/opportunities/conflict-inspector.tsx` -- becomes the decision card: `PositionBody`/`cardClass`/`gridClass` (:95-148) → big position cards; `ResolveForm` (:277-440) and `EscalateForm` (:444-532) merge into one form with a shared reason (keep `useDecision`, `failure`, validation constants, `ReasonField`); `ConflictInspector` keeps its props and `focusRequest`.
- `components/opportunities/conflict-status-pill.tsx` -- keep; the pills are no longer on rows (decision card note uses words).
- `lib/conflicts.ts` -- add `headerCounts`, `rowSubline`, `resolvedTag`, `agentPillLabel` (full "Engineering Agent" via `agentLabel`); reuse `sections`, `decisionLabel`, `estimateEffect`, `escalatedLabel`, `previousDecisionLabel`, `positionRole`, `positionSource`.
- Reuse `ui/card`, `ui/button`, `ui/chip`, `ui/textarea`, `ui/select`, `EmptyTabCard`, lucide `SparklesIcon`, `CircleAlertIcon`, `CircleCheckIcon`, `ArrowUpIcon`.
- Tests: `conflicts-list.test.tsx`, `conflict-inspector.test.tsx`, `lib/conflicts.test.ts`; `app/opportunities/pages.test.tsx` only if it asserts the tab body.

## Tasks & Acceptance

**Execution:**
- [x] `lib/conflicts.ts` + `lib/conflicts.test.ts` -- new label helpers
- [x] `components/opportunities/conflict-inspector.tsx` -- decision card with merged Resolve/Escalate form
- [x] `components/opportunities/conflicts-list.tsx` -- header, open card, resolved card, inline selection
- [x] `app/opportunities/[id]/conflicts.tsx` -- heading cleanup
- [x] `conflicts-list.test.tsx`, `conflict-inspector.test.tsx` -- update to the new structure; a test per matrix row; axe

**Acceptance Criteria:**
- Given the mockup data, when the tab renders at 1440px in light and dark, then it matches the mockup's order and styling.
- Given a keyboard user, when they move with j/k or arrows and press Enter, then the decision card shows that Conflict and its title takes focus.
- Given lint, typecheck, tests and build, when run in `web/`, then all pass.

## Implementation Notes

- New `lib/conflicts.ts` helpers beyond the Code Map: `conflictNote` ("Effort Conflict · High severity", plus "Detected from text"), `resolvedLine` (decision label, else the system reason) and `positionVersion` ("Assessment v2"; null for the Estimate, whose pill already names the version). `positionsSummary` and `OPEN_SECTION` were removed as unused.
- The form is now one `<form aria-label="Decide the Conflict">` (was "Resolve the Conflict" + "Escalate the Conflict"); the reason label is "Reason (required)" for both actions, and the reviewer select's label is visually hidden. Escalate's first press reveals and focuses the select; escalating does not require a position.
- The selection is pinned (first open Conflict on load); `open[0]` is only the fallback when the pinned Conflict is gone, so a live refresh never switches the card. `ConflictInspector` gains an optional `onDecided(kind)`: after a resolve the selection moves to the next open Conflict (not the decided one) and its title takes focus; after an escalation it stays.
- Escalate's reveal press clears earlier Resolve errors and the hint reads "Choose a reviewer, then give a reason." while the select is shown.
- The "Detected from text" chip on rows and in the header became words in the row sub-line and the decision-card note. The basis line is "{Finding kind} · {Finding title}". The Conflict's Requirement chip and excerpt sit under the note; each card also carries its Requirement chip.
- A resolved row's muted line drops "Resolved by {name}: " (the tag names them). `ConflictStatusPill`, `DetectedFromTextTag` (and `conflict-status-pill.tsx`) and `positionSource` were deleted as unused.
- `ConflictsSection` renders the visible `h2` (also above the empty card). The page keeps a visible `h2` in the failed-read branch so the tab always has its heading.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Card shows the just-resolved first Conflict again (old data, old `row_version`) until the refresh lands (blind, edge) | medium | patch | `decided()` sets `selectedId` null; `open[0]` is computed from the old `initial`. |
| Implicit selection follows `open[0]`, so a live refresh switches the card mid-typing (edge) | medium | patch | `selected` falls back to `open[0]` whenever `selectedId` is null; SSE refresh reorders it. |
| After escalating, the card jumps to another Conflict (edge) | low | patch | `onDecided` runs for escalations too and resets the selection. |
| Focus drops to body after a decision (blind, edge) | low | patch | The submit button unmounts; `decided()` sets `focusRequest` 0. |
| Stale "Choose a position" error and Resolve hint while escalating (blind, edge) | low | patch | Reveal press leaves `errors`; `DECISION_HINT` is static. |
| Requirement excerpt no longer shown (blind, edge) | medium | patch | `RequirementChip` lost its excerpt and the Conflict-level chip was removed. |
| Finding kind dropped from text-detected positions (blind, edge) | low | patch | `kindLabel` line removed; direct re-add. |
| Resolved row repeats "Resolved by {name}" in line and tag (blind) | low | patch | `resolvedLine` uses `decisionLabel`, which starts with the same words as `resolvedTag`. |
| `ConflictStatusPill`, `DetectedFromTextTag`, `positionSource` left without production callers (blind, edge) | low | patch | grep: only tests import them. |
| Dangling doc comment in `conflicts.tsx`; failed-read heading untested (blind, verification) | low | patch | Pre-verified by the verification layer; comment line ends mid-sentence. |
| Enter in the entered-position field resolves while the reviewer select is open (blind, edge) | low | rejected | Enter submits the form's primary action by design; routing it adds branches for a rare path. |
| Reviewer select label is `sr-only` (blind) | low | rejected | The select shows the chosen name or "Choose a reviewer"; the label exists for assistive tech. |
| Requirement chip repeated on each card (blind) | false | rejected | The frozen block asks for the Requirement chip as each card's evidence chip. |
| Severity pills removed from rows; red bar on escalated rows; decision card placed above Resolved (blind) | false | rejected | All required by the frozen block. |
| "No longer present" tag for other system reasons (edge) | low | rejected | Carried-forward Conflicts are not listed; the line shows the real reason; the frozen block fixes the tag text. |
| Hard-coded sizes bypass tokens (blind) | low | rejected | They are the mockup's sizes, used the same way in the Overview redesign. |
| `lib/conflicts.ts` imports `severityInfo` from `lib/red-team` (blind) | false | rejected | `severity-pill.tsx` already imports it from there; it is the shared severity helper. |
| Untested 3+ positions grid, `escalated_to` null, "Agent" fallback (blind) | low | rejected | Rare shapes; no wrong output shown. |
| 0 or 1 position renders half width (edge) | low | rejected | A Conflict always has two or more positions by construction. |
| Stale `focusRequest` when the selected Conflict leaves the list (edge) | low | rejected | Superseded by pinning the selection; no fallback mount on refresh after the patch. |
| Hidden `resolution_reason` on a decidable Conflict (edge) | false | rejected | Only resolved Conflicts carry a resolution reason. |
| Escalate now takes two presses and shares the reason (edge) | false | rejected | The frozen block specifies exactly this flow. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare with the mockup.
