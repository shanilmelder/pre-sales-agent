---
title: 'Redesign the Opportunities list to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'c4cd95f8c65501fae00258a982ab48108f0b0193'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-4a-opportunity-list.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-single-opportunities-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The `/opportunities` page body does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, the LIST screen). The views are an underlined tab strip. The filters are labelled selects and date inputs on their own row. The list is a bare four-column `table` on the canvas, with no open items and no Estimate.

**Approach:** Add open Gap and Conflict counts and the current Estimate to each list row in the API. Then restyle the page body to the mockup: one toolbar row with segmented views on the left and dashed filter chips on the right, followed by a six-column list inside a bordered card. The page header, routes, URL query, keyboard model and empty states keep their behaviour.

## Boundaries & Constraints

**Always:**
- **API:** `OpportunitySummary` gains three fields:
  - `open_gaps: int`: Gaps with status `open`.
  - `open_conflicts: int`: Conflicts that are open or escalated, the same rule as the workspace badge.
  - `estimate: {version: int, total_hours} | null`: the Opportunity's current draft Estimate version, with the same total hours as `get_estimate`'s `Totals.total_hours`, contingencies included. It is `null` when there is no draft.

  Each list page reads these with one batched query per module, not one per row. Both list endpoints (all and mine) return them.
- **Toolbar:** one row that wraps when narrow, with an 8px gap.
  - **Views (left):** a segmented `surface-alt` track (radius 9px, padding 3px) holding links at 13px/500, padding 5px 12px, radius 7px. The current view is `surface`/`text-foreground` and the others `text-secondary`. The views stay All, Mine and Due in 14 days. Keep `nav[aria-label="Views"]`, the hrefs and `aria-current`.
  - **Filters (right):** four dashed chips (`border-strong` dashed, 13px, radius 8px, padding 5px 10px, chevron): Status, Owner, Product and Proposal date. Each chip opens a popover holding today's labelled control(s); Proposal date holds From and To. A chip with a value applied shows it ("Status: Intake", "Proposal date: 1 Nov – 15 Nov") in a solid `primary-tint` style. Clear filters is a ghost link after the chips, shown only when a filter is applied. Mine shows no chips, as today.
- **List card:** `surface`, a `border`, radius 12px, the card shadow, clipped corners. The header row is `surface-alt` with a bottom border, 12px/500 `text-secondary`, padding 10px 20px. The columns, at the mockup's widths, are Opportunity, Status, Owner, Proposal date, Open items and Estimate (the last right-aligned). Rows have a top border, 20px horizontal padding and a muted hover.
- **Cells:**
  - Title at 500, with the customer below at 12px `text-secondary`.
  - `StatusPill`.
  - The owner as a 24px `primary-tint` circle with initials (10px/600 `primary-text`), then the name at 13px.
  - The proposal date at 13px, tabular.
  - Open items: "{n} gaps · {n} conflicts" (singular for 1). The Gaps count is in the gap tone when above 0 and the Conflicts count in `blocker` when above 0; otherwise both are `text-secondary`, at weight 500.
  - Estimate: "{hours} h" at 600 with one decimal and thousands separators, and "Draft v{n}" below at 12px `text-secondary`. With no draft it shows "—" and "No estimate".
- **The whole row opens the Opportunity** on click. The title link stays the only Tab target.
- Skeleton rows, the empty card, the filtered-empty text with Clear filters, and the "not reachable" text all render inside the card. Pagination sits below it.
- **Keep:** the table semantics (sr-only caption, `th scope="col"`), the roving tabindex, j/k/arrows/Enter, `data-opportunity-row`, the 150ms skeleton, and every filter behaviour (URL replace on page 1, the range error, facet fallbacks, `SELECTED_OWNER`).
- Light and dark both match the mockup's palettes.

**Never:**
- A Blocked view or a "Baseline" Estimate label (neither state exists).
- A database migration.
- Importing another module's `domain` or `adapters`.
- Changing routes, query keys, the page header or other pages.
- Editing existing `ui/*` primitives or tokens.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Counts | 3 open, 1 dismissed Gap; 1 open, 1 escalated, 1 resolved Conflict | `open_gaps` 3, `open_conflicts` 2; "3 gaps · 2 conflicts" | N/A |
| Estimate | Draft v3 (lines total 270 plus 8 h contingency), v2 superseded | `estimate` {3, 278.0}; "278.0 h", "Draft v3" | N/A |
| No Estimate | No draft version | `estimate` null; "—", "No estimate" | N/A |
| Batched | A page of 25 rows | Query count is the same for 1 or 25 rows | N/A |
| Filter chip | Pick Status Intake in the popover | URL `?status=intake`; chip reads "Status: Intake" | N/A |
| Mine | `?view=mine` | Mine selected; no chips | N/A |
| Row click | Click a row's Owner cell | Opens `/opportunities/{id}` | N/A |
| Keyboard | Tab into the list, j, Enter | Row 2's title link focused, then opened | N/A |
| Filtered empty | Filters match nothing | The card says "No Opportunities match these filters." with Clear filters | N/A |

</frozen-after-approval>

## Code Map

Backend (`backend/app/modules/`):
- `opportunities/application/models.py:96` `OpportunitySummary`; `opportunities.py` `_page` (~line 186) builds rows and already batches `identity.user_names(uow, ids)` (line 183). Follow that pattern.
- `gaps/application/public.py` -- add `open_gap_counts(uow, opportunity_ids) -> dict[str, int]` (a GROUP BY on `gaps_gaps`, status `open`; the index `(opportunity_id, status)` exists, models.py:99).
- `conflicts/application/public.py` -- add `open_conflict_counts(uow, ids)` that uses `BLOCKING` (`conflicts/domain/conflicts.py:54`), the same rule as `open_count` (`conflicts/application/conflicts.py:590`).
- `estimates/application/public.py` -- add `current_estimates(uow, ids) -> dict[str, (version, total_hours)]`, loading the draft versions (`repository.current_version` semantics, repository.py:326) with their lines and Assumptions in batch, and totalling with `domain/arithmetic.py:137 estimate_totals` so it equals `Totals.total_hours`.
- `backend/pyproject.toml:107` -- the opportunities import-linter contract: add `gaps` and `estimates` (domain/adapters/api) to its forbidden list. If importing gaps or estimates public at module level creates an import cycle, import inside `_page`.
- Tests: `backend/tests/test_opportunities.py` (`test_list_rows_and_pagination` :595, `test_my_vs_all` :575). Add count, estimate, null, superseded-ignored and query-count tests. Local pytest uses 127.0.0.1 and never the dev psa DB.

Web (`web/src/`):
- `lib/api/schema.d.ts` -- run `npm run gen:api` against a backend restarted on the new code (CI diffs it).
- `components/ui/popover.tsx` -- new thin wrapper over `@base-ui/react/popover` in the style of `ui/tooltip.tsx`.
- `components/opportunities/filter-bar.tsx` -- chips and popovers. Keep the control ids and labels inside the popovers, plus `commitDate`, `isCompleteDate` and the `role="group" aria-label="Filters"` wrapper.
- `components/opportunities/opportunity-views.tsx` -- segmented control.
- `components/opportunities/opportunities-table.tsx` -- card, six columns, initials (reuse `ui/avatar.tsx` with a `className` override), Open items, Estimate, and the row `onClick` (`router.push`, ignoring clicks on the link and modified clicks), with the empty states inside the card.
- `lib/opportunities.ts` -- `formatHours`, plus initials if no helper exists (grep first).
- `app/opportunities/list-page.tsx` -- toolbar row, card, Pagination below it.
- Mockup: lines 447–466 and 931–936 / 1019–1020 of the decoded template (`C:/Users/esm/AppData/Local/Temp/claude/D--Projects-Office-pre-sales-agent/cf4b25da-70fe-48a8-a7b6-3d832da29e5a/scratchpad/mock/template.html`).
- Tests: `opportunities-table.test.tsx`, `opportunity-views.test.tsx`, `filter-bar.test.tsx` (open the popover before `getByLabelText`), `app/opportunities/pages.test.tsx`, and fixtures that build `OpportunitySummary`.

## Tasks & Acceptance

**Execution:**
- [x] `gaps`, `conflicts`, `estimates` `application/public.py` -- batched readers
- [x] `opportunities/application/{models,opportunities}.py`, `pyproject.toml` -- new fields and contract
- [x] `backend/tests/test_opportunities.py` -- API matrix rows
- [x] `web/src/lib/api/schema.d.ts` -- regenerate
- [x] `components/ui/popover.tsx`, `filter-bar.tsx` + test -- chips
- [x] `opportunity-views.tsx`, `opportunities-table.tsx`, `list-page.tsx` + tests -- toolbar, card, cells, row click

**Acceptance Criteria:**
- Given `/opportunities` at 1440px in light and dark, when it renders, then the toolbar, card and rows match the mockup.
- Given the backend suite (including `test_architecture.py`) and the web lint, typecheck, test and build, when run, then all pass and axe stays clean.

## Implementation Notes

- Batched readers: `gaps.open_gap_counts` and `conflicts.open_conflict_counts` are one GROUP BY each; `estimates.current_estimates` is three queries (draft versions, their lines, their Assumptions) whatever the page size, and shares a new `_calculate` helper with `version_view`, so the list total is the same arithmetic as `get_estimate`'s `totals.total_hours`. One `draft` per Opportunity is guaranteed by a unique partial index, so no DISTINCT ON.
- `opportunities._page` imports the three public APIs inside the function (they import opportunities' public API). The import-linter contract now also forbids gaps and estimates domain/adapters/api.
- Web: date controls keep their labels ("Target date from/to") inside the Proposal date popover. A one-sided range reads "Proposal date: from 1 Nov" / "until 15 Nov". The old disabled Clear filters button is gone (link only when something is applied). The list's empty and filtered-empty states are a message row inside the card (with the header row), not the nested `EmptyTabCard`. `initials` moved into `lib/opportunities.ts` for the table; the three private copies elsewhere were left alone.
- schema.d.ts was generated from a dumped `app.openapi()` of the new code (not the Docker api).

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Alt-click on a row isn't covered by the modified-click test (verification) | low | patch | The test fires ctrl, meta, shift and middle clicks but never `altKey`; dropping that guard passes every assertion. |
| Drag-selecting text in a row opens the Opportunity (blind, edge) | low | patch | `openRow` doesn't check the selection; mouseup inside the `tr` fires a click. The fix is one guard. |
| Fixed 722px of columns in an `overflow-hidden` card crushes the title or clips cells when narrow or with the pane open (blind) | medium | patch | `table-fixed` with five fixed `col` widths; the card clips and can't scroll. The fix: scroll the card horizontally and give the table a minimum width. |
| Status, Owner and Product popovers stay open over the list after a pick (blind) | low | patch | One pick finishes the filter; users meet this on every filter. Close the select chips on change; Proposal date stays open for From/To. |
| Chip dates drop the year, so ranges across years or in another year are ambiguous (blind, edge) | low | patch | `formatShortDate` never shows the year. Show it when the years differ or aren't the current UTC year. |
| `FilterBar` doc comment line is well over ~100 columns (blind) | low | patch | Breaks the repo's hand-formatting width. |
| Estimate total reads every line and Assumption of the page's drafts (blind) | low | rejected | Three queries at most a few thousand rows per page; reusing `arithmetic` is what keeps it equal to `get_estimate`, and a SQL sum would duplicate the contingency rules. |
| `populate_existing=True` on read-only batch helpers (blind) | low | rejected | Copied from `lines_of`, which has the same option; list reads have no pending writes in their session. |
| Function-local imports hide an import cycle (blind) | low | rejected | The spec sanctions the local import; the boundary contract (public APIs only) holds. |
| `CurrentEstimate` and `EstimateSummary` duplicate a shape; `list` vs `Sequence` params (blind) | low | rejected | Each module owns its own contract type (AD-2); the param types are internal and both work. |
| Link-click branch of the row test goes through `defaultPrevented`, not `closest("a")` (blind) | low | rejected | Both guards are present; jsdom can't follow a Link click without it, and the behaviour is the same. |
| Empty `flex-1` spacer wraps oddly (blind) | low | rejected | When the row wraps, the spacer takes the leftover width of the first line; the chips start on line two as expected. |
| No tests for Escape, outside click or Clear with a popover open (blind) | low | rejected | That behaviour is Base UI's, not ours. |
| Arbitrary `text-[13px]` instead of a token (blind) | low | rejected | `text-control` is 13px at weight 500; the chips and cells are 13px at 400 in the mockup, and no such token exists (same ruling as the shell redesign). |
| Open items separator is read aloud; counts don't link to their tabs (blind) | low | rejected | "3 gaps · 2 conflicts" reads clearly; linking the counts isn't in the intent. |
| Backend tests miss converted Gaps, a no-draft query count, cross-row leakage and a contingency-only draft (blind) | low | rejected | The status filter is `== 'open'` and grouping is by `opportunity_id`; the existing tests show both. |
| "Draft v" is hard-coded and would break with a non-draft current version (blind) | false | rejected | `VersionStatus` is only draft or superseded, and the current version is always the draft (`current_version`). |
| Closed date chip hides a pending range error (edge) | low | rejected | The error shows in the popover where it was made, and the old range is still the one applied, so the chip is right. |
| `current_versions` relies on the one-draft index instead of ORDER BY/LIMIT (edge) | false | rejected | `uq_estimates_estimate_versions_one_draft` (models.py:65) guarantees at most one draft. |
| Counts and Estimate come from separate reads, not one snapshot (edge) | low | rejected | The page's own total and items already come from separate reads; a list showing a moment-apart count is harmless. |

## Verification

**Commands:**
- `uv run pytest` (in `backend/`, against 127.0.0.1) -- expected: pass.
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: pass.

**Manual checks:**
- Screenshot `/opportunities` (All with data, a chip open, filtered empty, Mine) in light and dark at 1440px and compare with the mockup.
