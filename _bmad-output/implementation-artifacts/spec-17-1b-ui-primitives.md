---
title: 'Story 17.1b: Redesign UI primitives'
type: 'refactor'
created: '2026-10-22'
status: 'done'
baseline_commit: 'ec3e3feee26c9099b8b875804ca0e1c563d4a0eb'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/DESIGN.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 17.1a applied the redesign tokens, but the shared primitives still use the old look: `Button` is 32px with `rounded-lg`, `Input`, `Textarea` and `Dialog` use old fills and borders and animate, and Card, Select, Table, Skeleton, Avatar, Tooltip, Switch, a tint-filled pill and the chip do not exist. Later Epic 17 stories have nothing to build screens from.

**Approach:** Restyle the existing `web/src/components/ui` primitives to DESIGN.md Components and add the missing ones, each with its own test. Migrating existing consumers (pills, chips, raw buttons, inputs, selects, tables, the Settings switch, `title=` tooltips) is not part of this story.

## Boundaries & Constraints

**Always:**
- Use the 17.1a tokens only (`border-strong`, `surface`, `surface-alt`, `shadow-card`, `shadow-overlay`, `bg-scrim`, `text-control`, `text-body-strong`, `radius-md/xl`). Remove `dark:*` overrides, since tokens already switch.
- Import `cn` from the `"cn"` package, as the existing primitives do. Keep base-ui's `render={...}` pattern, no `asChild`.
- `Button`: primary about 38px (`px-4`, body-strong, radius 8); secondary 32px (`px-3`, control type, `bg-surface`, `border-strong`), reached through the existing `outline` variant; disabled is `opacity-40`, `cursor-not-allowed` and `aria-disabled`; hover `brightness-[.97]`. Keep the other variants working.
- `Input`, `Textarea`, `Select`: `bg-surface-alt`, `border-strong`, radius 8, 14px text.
- `Dialog`: `w-dialog-width`, `p-6`, 1px border, radius 12, `shadow-overlay`, `bg-scrim` overlay without blur, title 20/600, no `animate-*` or zoom classes, footer inset `-mx-6 -mb-6 p-6`. Keep Title and Description wiring and `showCloseButton={false}`.
- New: `Card` (surface, 1px border, radius 12, `shadow-card`, header `px-5 py-[18px]`), `Skeleton` (static neutral block), `Avatar` (human circle, agent 6px-radius square with initials, wraps base-ui Avatar), `Tooltip` (wraps base-ui Tooltip; its Provider mounts in `app/layout.tsx`), `Switch` (base-ui, 44x26, full radius, off track `border-strong`, on track `primary`, 20px white knob, visible On/Off text), `Select` (a styled native `<select>` wrapper), `Table` (sticky header, tabular figures, `h-row` body rows) and `Pill` and `Chip`.
- `Pill` is the status pill: full radius, label type, padding `2px 10px 2px 8px`, optional 12px icon, tones `neutral | resolved | agent | blocker | gap`, tint fill with the tone's text colour, no outline. `Chip` is the evidence chip: `text-primary-text bg-surface border-border-strong rounded-sm px-2 py-0.5`.
- Every primitive has a test in `web/src/components/ui/` (render, token classes, disabled or toggle behaviour where it applies, and an axe check with `src/test/axe.ts`).

**Never:**
- Do not migrate any existing consumer. The three `*-status-pill.tsx` files, other `*Pill` components, the chip class strings, raw `<button>`, `<input>`, `<select>`, `<table>`, `settings-form.tsx`'s switch and `title=` attributes stay as they are (Stories 17.1c, 17.2, 17.3).
- No base-ui Select (13 native selects and their `selectOptions` tests stay valid). No new dependency, no backend change.
- Do not name the new pill `StatusPill`: that name is taken by `opportunities/status-pill.tsx`.

**Decisions:**
- `Pill` and `Chip` live in `ui/pill.tsx` and `ui/chip.tsx`. The command palette keeps its current width with a className override on `CommandDialog`; the 520px default applies to other dialogs.
- Input height is 38px to match the primary button (DESIGN.md gives none).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Disabled button | `disabled` | Opacity .4, `aria-disabled`, not-allowed cursor, no click | N/A |
| Switch toggle | Click or Space | `aria-checked` flips, On/Off text follows | N/A |
| Dialog open | Trigger activated | 520px dialog with labelled title, focus trapped, Esc closes | N/A |
| Pill tone | `tone="gap"` | Gap tint fill and gap text, no border | N/A |

</frozen-after-approval>

## Code Map

- `web/src/components/ui/button.tsx` (57 lines, base-ui Button) -- default `h-8 rounded-lg disabled:opacity-50 hover:bg-primary/80`; variants outline, secondary, ghost, destructive, link.
- `web/src/components/ui/input.tsx` (19), `textarea.tsx` (17), `input-group.tsx` (158, used only by `command.tsx`) -- `bg-transparent border-input rounded-lg dark:bg-input/30`.
- `web/src/components/ui/dialog.tsx` (160, base-ui Dialog) -- `sm:max-w-sm p-4 ring-1 bg-popover`, `animate-in/zoom/fade` at about lines 33-36 and 55-57, overlay `bg-black/10 backdrop-blur-xs`, footer `-mx-4 -mb-4 bg-muted/50`, close at `top-2 right-2`.
- `web/src/components/ui/command.tsx` (197) -- `CommandDialog` inherits the Dialog width; `shell/command-palette.tsx` and `shell/cheat-sheet.tsx` use `ui/*`; `specialist-assessments.tsx:32,42,500-528` uses Button and Dialog (cancel-run confirm).
- `@base-ui/react` 1.8.0 exports Switch (Root, Thumb), Tooltip (Provider, Root, Trigger, Portal, Positioner, Popup), Avatar (Root, Image, Fallback).
- `web/src/app/layout.tsx` -- mount `Tooltip.Provider`. `web/src/test/axe.ts` and `src/test/setup.ts` (ResizeObserver and scrollIntoView shims) for tests.
- Existing tests to keep green: `app-shell.test.tsx`, `specialist-assessments.test.tsx`, palette and cheat-sheet tests. No tests exist under `ui/` yet.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/components/ui/button.tsx`, `input.tsx`, `textarea.tsx`, `dialog.tsx`, `command.tsx` -- restyle to DESIGN.md; keep the palette width -- UX-DR1, 8.
- [x] `web/src/components/ui/card.tsx`, `skeleton.tsx`, `avatar.tsx`, `tooltip.tsx`, `switch.tsx`, `select.tsx`, `table.tsx`, `pill.tsx`, `chip.tsx` -- add the primitives -- UX-DR1, 6, 8.
- [x] `web/src/app/layout.tsx` -- mount the Tooltip provider.
- [x] `web/src/components/ui/*.test.tsx` -- one test file per primitive covering the I/O matrix and axe.

**Acceptance Criteria:**
- Given the primitives, when rendered, then primary buttons are about 38px, secondary 32px with `border-strong`, pills are tint-filled without an outline, cards are 12px, and disabled controls use opacity .4.
- Given a dialog, when it opens, then it is 520px, has a labelled title and a scrim overlay, and has no animation classes.
- Given any existing consumer of `ui/*`, when its tests run, then they still pass.
- Given the primitive tests, when axe runs, then there are no violations.

## Implementation Notes

- **Type classes sit outside `cn()`.** The `cn` package (0.4.0) treats custom `text-*` sizes (`text-control`, `text-body`, `text-label`, `text-section`, `text-meta`) as colours, so `cn("text-foreground", "text-body")` drops one. Each primitive appends its type class after `cn()` (`${cn(...)} text-body`). A caller className that sets a font size will not replace the built-in one. Later stories (17.1c to 17.4) that pass classNames into these primitives must keep this in mind, or add a `cn` config that knows the custom sizes.
- `Select` is a styled native select; a `wrapperClassName` prop is the expected addition when Story 17.3 migrates the 13 native selects.
- `Switch` has no wrapper or label class props yet; Story 17.2 can add them when it consumes the Switch.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Edge | `Table` keeps `text-body` and `CardTitle` keeps `text-section` inside `cn()`, so a caller colour class drops the type class | medium | Verified: `cn("text-section","text-foreground")` returns `text-foreground` (cn 0.4.0 treats custom `text-*` sizes as colours). Every other primitive moved its type class outside `cn()`; these two did not (table.tsx:1175, card.tsx:524). | patch |
| 2 | Edge, Blind | Disabled ghost, destructive and link buttons still show hover background or underline (`pointer-events-none` was removed) | low | button.tsx variants keep `hover:bg-muted`, `hover:bg-destructive/20` and `hover:underline` with no disabled reset; the base only resets brightness. Real, direct class fix. | patch |
| 3 | Edge | Pill with `tone={null}` gets no tone classes while `data-tone` says neutral | low | `VariantProps` allows `null`; cva's default only covers `undefined`. One-line fix `tone ?? "neutral"`. | patch |
| 4 | Edge, Blind | Type class appended after `cn()` cannot be overridden by a caller (text-xs etc.) | low | Intentional and needed: cn drops one of two `text-*` classes (verified). No existing consumer passes a type class into these primitives (grep). Registering the sizes needs a `cn` config the spec does not include. Recorded in Implementation Notes for Stories 17.1c to 17.4. | rejected |
| 5 | Blind | Same pattern repeated (`buttonType` vs template suffix) | low | Cosmetic; a shared helper would be new surface. | rejected |
| 6 | Blind, Edge | Button `aria-disabled` can be overridden by a caller prop; `focusableWhenDisabled` bypassed | low | `disabled` is still passed to base-ui; a contradictory caller `aria-disabled` is not a state the app reaches (no consumer passes it). | rejected |
| 7 | Edge | Icon button sizes get no type class | false | Icon buttons hold an svg only; a labelled icon button inherits its parent's type. | rejected |
| 8 | Edge | `focus-visible:ring-offset-background` may have no token | false | `.focus-visible\:ring-offset-background:focus-visible` is in the built CSS. | rejected |
| 9 | Edge | Input and Textarea disabled lose `pointer-events-none` and the disabled fill | low | Spec: disabled is opacity .4 and cursor not-allowed. A not-allowed cursor needs pointer events. | rejected |
| 10 | Edge | `w-full` palette override conflicts with `w-dialog-width` | false | The palette's `sm:max-w-sm` clamps at 24rem from 640px up either way (width 520 or 100% both clamp to 384), and below 640px the base `max-w-[calc(100%-2rem)]` applies. Width equals the old palette width. | rejected |
| 11 | Edge | `w-dialog-width` may be undefined and collapse the dialog | false | `.w-dialog-width` is in the built CSS. | rejected |
| 12 | Blind, Edge | Switch: visible On/Off span not tied to the switch, hardcoded English, no wrapper class props | low | The switch gets an accessible name from the caller, the text is a redundant visible state (DESIGN.md), and the product is English-only. Wrapper props can be added by Story 17.2 when it consumes the Switch. | rejected |
| 13 | Edge | Switch shadow state can drift from the Root | false | `isOn = checked ?? inner`; a controlled value always wins and the inner state only tracks the uncontrolled case. | rejected |
| 14 | Blind, Edge | Select: `className` goes to the select, not the wrapper; multiple or size>1 and the chevron; no invalid state | low | No existing select uses `multiple` (grep). The wrapper-class split is a new prop; Story 17.3 adds it when the 13 selects migrate. | rejected |
| 15 | Blind, Edge | Avatar: kind conveyed by shape only; `kind` can be an unexpected runtime value | false | TypeScript restricts `kind`; initials and the agent's name sit beside the avatar; no consumer yet. | rejected |
| 16 | Edge | Tooltip on a disabled trigger never opens | low | Base-ui behaviour; nothing in the app uses the Tooltip yet. | rejected |
| 17 | Blind | Tooltip tests: hover only, closed-state axe, shadow choice | low | The Gap reviewer filed no gap; content and provider are covered, and shadow-card vs overlay is a design choice. | rejected |
| 18 | Blind, Edge | Dialog: animations and blur removed, footer margins tied to `p-6`, brittle trailing-space test assertion | false | Spec: no animation, `p-6` and footer `-mx-6 -mb-6`. The assertion passes reliably. | rejected |
| 19 | Blind | `h-[38px]`, `duration-[120ms]`, `py-[18px]` repeated; no tokens | low | DESIGN.md defines none of them. | rejected |
| 20 | Blind | Tests assert class strings; a token typo would pass | false | Every class asserted is present in the built CSS (checked `w-dialog-width`, `shadow-overlay`, `bg-scrim`, `bg-neutral-tint`, `h-row`, `border-border-strong`, `text-primary-text`, tints, `data-checked:*`, `h-[38px]`). | rejected |
| 21 | Blind | Pill and Chip axe in jsdom does not cover contrast | false | Pill and chip colour pairs are gated by `contrast.test.ts` (tint and primary-text pairs). | rejected |
| 22 | Blind | Pill test builds `bg-${tone}-tint` dynamically | false | The component writes the literal classes; only the test interpolates. | rejected |
| 23 | Blind | Missing variants: Table footer, scroll container, sticky header inside overflow, Card interactive, Avatar image test | low | Outside the spec's list. A sticky header in an `overflow-x-auto` wrapper sticks to that container, as designed for the consumer. | rejected |
| 24 | Blind | Existing-consumer regressions: sizes changed, button-group radius and `active:translate-y-px` removed, dark overrides removed | false | Only specialist-assessments, cheat-sheet and the palette use `ui/*`; the full suite passes (1,530 tests). `in-data-[slot=button-group]` has no consumer. Dark tokens switch under `.dark`. | rejected |
| 25 | Blind | Double TooltipProvider wrapping | false | The Gap reviewer found no other Tooltip or Provider usage. | rejected |
| 26 | Blind | Chip and Pill: no truncation or link variant; `text-text-secondary` mixes colour vocabularies | low | Evidence chips are plain references; `text-text-secondary` is the DESIGN.md token name. | rejected |
| 27 | Edge | InputGroup focus ring (ring-3 at 50%) differs from Input (ring-2 plus offset) | low | `command.tsx` overrides the palette's focus with `ring-2 ring-primary`; InputGroup has no other consumer. | rejected |
| 28 | Edge (claims) | Dialog title and description wiring, Button no-click claim | false | Verified by the dialog and button tests (labelled dialog, aria-describedby, disabled click). | rejected |
| 29 | Blind | The spec and deferred-work files are not in the diff | false | They are planning files, not code; the claims file is read by the Edge layer directly. | rejected |

## Verification

**Commands:**
- `npm run lint --prefix web` -- expected: no errors
- `npm run typecheck --prefix web` -- expected: no errors
- `npm test --prefix web` -- expected: all tests pass, including the new `ui/*.test.tsx`
- `npm run build --prefix web` -- expected: build succeeds
- `grep -rn "animate-in\|zoom-in\|dark:bg-input" web/src/components/ui` -- expected: no matches

**Manual checks (if no CLI):**
- Open the cancel-run confirm in Assessments and the command palette: dialog is flat, scrimmed and the palette width is unchanged.
