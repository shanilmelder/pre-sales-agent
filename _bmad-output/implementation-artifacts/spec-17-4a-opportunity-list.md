---
title: 'Story 17.4a: Opportunity list columns, view tabs and empty card'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'acd1ac96a069ffe2a846666563bfe3425fd8ad1b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3b-conflicts-estimate-trace-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Opportunity list is a dense 32px table headed Customer, Status, Owner and Target proposal date. It has no view tabs, shows its empty state as a bare sentence, and leads with the customer instead of the Opportunity (Story 17.4, UX-DR5, UX-DR6, UX-DR20, UX-DR23).

**Approach:** Redesign the list table and add fixed view tabs, using only data the list API returns. The Opportunity header is Story 17.4b and is deferred.

## Boundaries & Constraints

**Always:**
- **Columns:** Opportunity, Status, Owner, Proposal date. The Opportunity cell is two lines: the title as the row link, the customer below it. Header "Target proposal date" becomes "Proposal date". Rows are padded (`min-h-row`, `py-3`) and keep the roving tabindex, j/k and arrow keys, and Enter.
- **View tabs** (`nav aria-label="Views"`, links, current one `aria-current="page"`): **All** to `/opportunities`; **Mine** to `/my-opportunities`; **Due in 14 days** to `/opportunities` with `from` set to today and `to` set to today plus 14 days (UTC), the existing date filters. It is current when the filters equal that range. The tabs show on both list pages.
- **Empty state** with no filters: `EmptyTabCard`, title "No Opportunities yet", body "Create an Opportunity from a customer email, transcript or RFP. The first file becomes its first Source.", and for people who can create, a **New Opportunity** link to `NEW_OPPORTUNITY_HREF` (no button for others). The filtered-empty state and its Clear filters link stay as they are.
- Loading skeleton, `aria-busy`, the 150 ms minimum and pagination stay. The skeleton gets four cells to match the columns. Status stays a `Pill` with its icon or text, and the proposal date stays text.
- Reuse `ui/card`, `ui/empty-tab-card`, `ui/pill`; type classes outside `cn()`; existing tests pass with updated selectors only.

**Never:** Add Open items, Estimate, Blocked or Submit (the list API has no counts, estimate summary or blocker data; logged for the backend). Touch the Opportunity header, the workspace, the filter bar logic or saved views (Story 1.11), `ui/*`, the shell, or the data layer and API calls.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rows | Opportunities returned | Opportunity cell shows title link and customer; Status, Owner, Proposal date follow | N/A |
| Loading | First mount, under 150 ms | Skeleton rows with `aria-busy` | N/A |
| Empty, creator | No items, no filters, can create | Empty card with **New Opportunity** | N/A |
| Empty, other user | No items, no filters, cannot create | Empty card, no button | N/A |
| Filtered empty | No items, filters set | "No Opportunities match these filters." and Clear filters | N/A |
| Due view | `from` = today, `to` = today + 14 | **Due in 14 days** tab is current | N/A |
| Mine | `/my-opportunities` | **Mine** tab is current; no filter bar | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/opportunities-table.tsx` -- `Header` (~24-42), skeleton (~76-93), empty branches (~96-117), row (~140+): columns, two-line cell, padding, empty card.
- `app/opportunities/list-page.tsx` -- add the view tabs under the title bar; compute the Due range from today (UTC).
- `app/opportunities/filters.ts` -- add a `dueSoonFilters(today)` helper and an `isDueSoon(filters, today)` check beside `parseFilters`.
- New `components/opportunities/opportunity-views.tsx` (+ test): the tabs.
- `lib/opportunities.ts:24-29,42` -- empty copy constants; keep `EMPTY_FILTERED`, `SKELETON_MIN_MS`.
- Reuse `ui/empty-tab-card.tsx`, `lib/shortcuts.ts` `NEW_OPPORTUNITY_HREF`, `formatDate`.
- Tests: `opportunities-table.test.tsx` (skeleton ~55-64, headers ~68-76, empty ~92-96, axe ~150), `app/opportunities/pages.test.tsx` (~225-230, 323-324, 364), `filter-bar.test.tsx` if it asserts the table.

## Tasks & Acceptance

**Execution:**
- [x] `filters.ts` + tests -- Due range helpers
- [x] `opportunity-views.tsx`, `list-page.tsx` + tests -- tabs on both pages
- [x] `opportunities-table.tsx`, `lib/opportunities.ts` + tests -- columns, padding, empty card
- [x] Matrix tests -- each row above, plus axe on the list

**Acceptance Criteria:**
- Given the Opportunity list, when it loads, then the columns are Opportunity (title and customer), Status, Owner and Proposal date, and the views All, Mine and Due in 14 days show.
- Given no Opportunities, when the list renders, then it shows "No Opportunities yet" with **New Opportunity** for people who can create.
- Given axe, when it runs on the list, then there are no violations, and status always shows an icon or text.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `text-label` inside `cn()` in the view tabs | low | patch | Spec says type classes outside `cn()`; moved out. |
| No leap-day test for `dueSoonFilters` | low | patch | Added a 2028-02-20 case. |
| `min-h-row` on `<tr>` does not enforce a height | low | rejected | Spec mandates `min-h-row` with `py-3`; the padding and two-line cell set the height, as in 17.3. |
| Empty card body invites creating for people who cannot | low | rejected | The body is the EXPERIENCE copy and the spec hides only the button; new copy for non-creators is not specified. |
| "Press c" hint gone; two New Opportunity links for creators | low | rejected | Spec decision; the page test pins both links. |
| Midnight-UTC flake in the Due-current page test | low | rejected | The window is a few milliseconds a day; fixing needs an injected clock. |
| Due view looks forward only, in UTC; any other filter drops the highlight | low | rejected | The spec defines the range and says current only when the filters equal it. |
| Skeleton cells do not match two-line rows | low | rejected | Cosmetic. |
| Empty or blank `title` leaves an empty link | false | rejected | The API requires a title. |
| `addDays` does not validate its input | false | rejected | Its only input is the page's own UTC date string. |
| Header renamed to "Proposal date" | false | rejected | Spec and epic call for it. |
| Mine tab has no role check | false | rejected | `/my-opportunities` already serves every signed-in user. |
