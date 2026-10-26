---
title: 'Restyle the Effort comparison grid like the other grids'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On the redesigned Assessments tab, the Effort comparison is still a bare, borderless `<table>` under a small `text-body-strong` heading. It does not match the Findings table above it or the Estimate grid, which both sit in a `Card` with a tinted label header and ruled rows.

**Approach:** Restyle `EffortComparisonSection` only, using the same visual language: a `text-section` heading with the notes below it, a `Card` (no padding, clipped) holding the table, a `bg-surface-alt` header row in `text-label` muted type, `h-row` rows with bottom rules and a soft hover, the Requirement label as a `Chip` beside its excerpt, tabular right-aligned hours, a left rule setting the Estimate columns apart, and a top-ruled bold totals footer. Data, wording, calculations, empty and error states, and the scrollable `region` keep their behaviour.

</frozen-after-approval>

## Implementation Notes

- Only `web/src/components/opportunities/effort-comparison.tsx` changes (and its test if a selector needs it). `lib/effort-comparison.ts`, the page composition, tokens and `ui/*` are untouched.
- `ui/table.tsx` is not used by any grid in the app; the Findings table and Estimate grid hand-roll their markup, so this one does too, copying their classes.
- The header row copies the Findings table (`bg-surface-alt`, `text-label`). The totals row repeats that tint with a `border-border-strong` top rule; neither reference grid has a tinted footer, so this is new, chosen so the totals read as a band. The first column uses `pl-5` to line up with the Findings card above.
- Rows have no hover: they are read-only, and a hover would suggest an action.
- Difference stays uncoloured: a positive or negative gap is not good or bad in itself, so colour would imply a judgement the data does not make.

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `line-clamp-2` hides excerpt text with no way to read it | medium | patch | The old table showed the full (server-cut, 140 char) excerpt; clamp removed. |
| Row hover filter barely visible on a background-less `tr` | low | patch | Hover deleted (see next). |
| Hover implies read-only rows are clickable | low | patch | No button or selection on these rows; hover removed. |
| `px-4` misaligns with the Findings card's `px-5` | low | patch | First column now `pl-5`. |
| Spec says it copies the Estimate grid; tinted footer is new | low | patch | Implementation Notes corrected. |
| Footer weight set three times | low | patch | `text-body-strong` wrapper removed; `tr` sets it. |
| The `{" "}` in a flex row looks stray | low | patch | Comment added: it keeps the rowheader name "R1 text". |
| No tests for the new styling | low | rejected | Class-level assertions add brittleness; behaviour tests and axe still cover the table. |
| Spec lacks AC and Verification | false | rejected | The one-shot route drops those sections by design. |
| Without Estimate, Agents total is set apart only by weight | low | rejected | Same as before this change. |
| `Chip` is the wrong component for a Requirement label | false | rejected | `estimate-grid.tsx` `CoversChips` shows Requirement labels as `Chip` in a table. |
