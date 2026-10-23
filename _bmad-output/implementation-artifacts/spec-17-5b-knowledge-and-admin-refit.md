---
title: 'Story 17.5b: Knowledge and Admin page header, segmented control and card rows'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '9e4d2fb5d220ebbbb0bf4308fb2a2afa61c32240'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-5a-page-header-and-new-opportunity.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Knowledge and Admin still use a hand-rolled title, an underline sub-nav and bare full-width tables, and Knowledge's register button sits in a filter row (Story 17.5, UX-DR2, UX-DR6, UX-DR8, UX-DR21).

**Approach:** Give both pages the shared `PageHeader`, replace the underline sub-nav with a segmented control, and put each built list in a card with padded rows. Pills are already tint-filled (Story 17.1c); keep them.

## Boundaries & Constraints

**Always:**
- **Headers:** Knowledge → title "Knowledge", subtitle, action **Add source**. Admin (all three sections) → title "Admin", one subtitle, **no action** (**Invite user** waits for Story 1.10). The old section titles ("Catalogue", "Evals", "Users & roles") are no longer the `h1`; the segmented control marks the section.
- **Add source** is the existing **Register Source** button moved to the header and renamed: same handler (`startCreate`), `aria-keyshortcuts="c"`, shown only when `canRegister`. It stays out of the filter row.
- **Segmented control:** one new component, `nav` with a label, links (`aria-current="page"` on the current one), a pill-shaped track with the current item raised. Knowledge uses it with its one section (Sources); Admin with Users & roles, Catalogue, Evals. Keyboard and focus ring as before; never colour alone (current item also bold).
- **Card rows:** Knowledge Sources, Users, each Catalogue kind (its `h2` stays) and each Evals section render inside `Card`; rows keep the 32px height, roving tabindex, `j`/`k`/arrow keys, `data-*-row` attributes and button names, with horizontal padding that fits the card (not the page gutter). Status pills unchanged.
- Existing tests pass with updated selectors only; axe clean on all four pages. Type classes outside `cn()`.

**Never:** Touch the inspectors, forms, right-pane behaviour, filters' logic, pagination, API calls, actions or data layer, the shell, tokens or existing `ui/*` files. Do not add **Invite user**.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Knowledge, may register | Role allowed | Header with **Add source**; it opens the register form; `c` still works | N/A |
| Knowledge, may not register | Other role | Header, no action | N/A |
| Admin section | Any of three | Title "Admin", no action, segmented control marks the section | N/A |
| Keyboard in a list | Focus a row, press `j`/`k`/arrows/Enter | Same roving focus and inspector open as before | N/A |
| Empty or error list | No rows / API down | Existing messages, shown inside or beside the card | Existing |
| Non-admin on Admin | No admin permission | Existing "You don't have access" state | Existing |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/ui/segmented-nav.tsx` -- new (`SegmentedNav({ label, items, current })`); model on `admin-nav.tsx`, whose usage it replaces.
- `components/admin/admin-nav.tsx` -- keep the `SECTIONS` list; render `SegmentedNav`.
- `app/admin/users/page.tsx`, `catalogue/page.tsx`, `evals/page.tsx` -- `PageHeader` "Admin"; `app/admin/page.tsx` keeps its redirect.
- `app/knowledge/page.tsx` + `components/knowledge/sources-tab.tsx:221-240` -- header with **Add source** (the tab owns `creating`; it may render `PageHeader` itself, the page does so for the error branch); segmented control in place of the inline `nav`.
- `components/knowledge/sources-table.tsx`, `components/admin/users-table.tsx`, `catalogue-table.tsx`, `evals-view.tsx` -- card wrapper and padding; keep keyboard code.
- Reuse `components/shell/page-header.tsx`, `ui/card.tsx`, `ui/pill.tsx`.
- Tests: `sources-table.test.tsx`, `users-table.test.tsx`, `users-admin.test.tsx`, `catalogue-table.test.tsx`, `catalogue-admin.test.tsx`, `app/page.test.tsx`; add `segmented-nav.test.tsx` and page-level header tests.

## Tasks & Acceptance

**Execution:**
- [x] `ui/segmented-nav.tsx` + test -- component, current item, axe
- [x] `admin-nav.tsx` and the three Admin pages + tests -- "Admin" header, segmented control
- [x] `knowledge/page.tsx`, `sources-tab.tsx` + tests -- header with **Add source**, segmented control
- [x] `sources-table.tsx`, `users-table.tsx`, `catalogue-table.tsx`, `evals-view.tsx` + tests -- card rows, keyboard unchanged
- [x] Matrix tests -- each row above, plus axe on Knowledge and the three Admin sections

**Acceptance Criteria:**
- Given Knowledge or Admin, when it renders, then it has the page header, the segmented control marks the current section, and only Knowledge has an action (**Add source**, for those who may register).
- Given any built sub-tab, when it renders, then its list sits in a card with padded rows and tint-filled pills.
- Given lint, typecheck, build and tests, when run, then all pass with no behaviour change.

## Implementation Notes

## Spec Change Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Add source absent while the list or types fetch errors | low | rejected | Without the types the register form cannot work; the error message explains the page state. |
| Admin routes share one `h1` | low | rejected | Per-route `metadata` titles remain distinct; the spec fixes the title "Admin". |
| `SegmentedNav` shows no current item for an unmatched `current`; hardcoded `/knowledge`; no overflow | low | rejected | Callers pass a matching href; three short items fit the supported widths. |
| Type class built by hand around `cn()` | false | rejected | The spec and repo idiom put type classes outside `cn()`. |
| Header and nav built twice (page error branch and `SourcesTab`) | low | rejected | The tab owns the Add source state; the page needs the header only for the error branch. |
| Roles note and Auth0 link show beside no-access or error | false | rejected | Pre-existing: the note was in the header before this story. |
| Focus ring clipped by card `overflow-hidden` | low | rejected | Row buttons are shorter than the row; the ring has room inside the cell. |
| Evals cards touch the viewport edge | false | rejected | `EvalsView` wraps the sections in `p-gutter`. |
| Evals card section landmark nested, spacing differs from users page | low | rejected | Cosmetic. |
| Import order, reflowed lines, duplicate mock in the new test | low | rejected | Cosmetic; no demonstrated harm. |
| No axe call added to catalogue and evals page tests; `c` shortcut not exercised; empty-list wrapper unchecked | low | rejected | Existing axe tests cover those pages; the handler is unchanged and its tests pass. |
| "Register Source" label elsewhere | false | rejected | No other reference outside tests. |
