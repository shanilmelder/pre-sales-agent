---
title: 'Story 17.5a: Page header, New Opportunity card, Inbox and Reports headers'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '21b01809add994867f39d31366c70ed559f127ed'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-4b-opportunity-header.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Pages outside the workspace each hand-roll a title row (or none): no shared header, no subtitle, and New Opportunity is a bare form (Story 17.5, UX-DR2, UX-DR5).

**Approach:** Add one `PageHeader` (title, one-line subtitle, optional primary action) and use it on All and My Opportunities, New Opportunity, Inbox, Reports and Settings. Put the New Opportunity form in a card with import-from-file above the fields and add **Cancel**. Knowledge and Admin (headers, **Add source**, segmented control, rows) are Story 17.5b, logged in deferred-work.

## Boundaries & Constraints

**Always:**
- `PageHeader` renders an `h1`, a one-line subtitle (`text-muted-foreground`) and an optional action slot. The right-pane toggle stays in the shell bar built in 17.2b.
- Actions: Opportunities and My Opportunities → **New Opportunity** (only with create permission, link to `NEW_OPPORTUNITY_HREF`, `title` keeps "(C)"); New Opportunity, Inbox, Reports, Settings → none. Inbox and Reports have **no** action (decision): **Mark all read**, the two-pane Inbox and **Export** wait for Stories 9.2 and the reports story.
- New Opportunity: the form sits in `Card`; the import section (button, **Clear import**, status line) is the card's first block, then the fields; footer has **Create Opportunity** and **Cancel** (link to `/opportunities`). Hints stay as built ("Leave empty to use the customer name.", "One per line, up to N."). No import or create behaviour changes.
- Use `Button`/`buttonVariants`, `Card`, `ui/input` where the file already uses an equivalent; type classes outside `cn()`. Existing tests pass with updated selectors only; axe clean on each page.

**Never:** Touch Knowledge, Admin, the Opportunity workspace, the shell, tokens, `ui/*`, or any API call, action or data layer. Do not build Inbox data, **Mark all read** or **Export**.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Can create | Opportunities list, create permission | Header with subtitle and **New Opportunity** link | N/A |
| Cannot create | List, no create permission | Header with subtitle, no action | N/A |
| Placeholder pages | Inbox, Reports | Header with subtitle, no action; placeholder body kept | N/A |
| New Opportunity | Page loads | Card: import section first, fields, **Create Opportunity**, **Cancel** | Existing validation and import errors unchanged |
| Cancel | Press **Cancel** | Goes to `/opportunities` with nothing created | N/A |
| Settings | Page loads | Header with subtitle, no action, then the settings card | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/shell/page-header.tsx` -- new `PageHeader({ title, subtitle, action })`; sits beside `app-shell.tsx` (which keeps `PlaceholderPage`; give it the same subtitle slot or replace its title row with `PageHeader`).
- `app/opportunities/list-page.tsx:104-119` -- title row and inline **New Opportunity** link become `PageHeader`; `title` prop still sets the `h1` and table caption.
- `app/opportunities/new/page.tsx` -- `PageHeader`; keep the no-access message.
- `components/opportunities/create-form.tsx:385-540` -- wrap in `Card`, import block first, add **Cancel**; keep ids, refs and `aria-*`.
- `app/inbox/page.tsx`, `app/reports/page.tsx`, `app/settings/page.tsx` -- `PageHeader`.
- Reuse `ui/card.tsx`, `ui/button.tsx`. Do not change `app-shell.tsx` layout.
- Tests: `app/opportunities/pages.test.tsx`, `create-form.test.tsx`, `app-shell.test.tsx`, `app/page.test.tsx`; add `page-header.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `components/shell/page-header.tsx` + test -- component with and without action; axe
- [x] `list-page.tsx`, `new/page.tsx`, `inbox`, `reports`, `settings` pages -- adopt `PageHeader` with subtitles and the actions above
- [x] `create-form.tsx` + `create-form.test.tsx` -- card layout and **Cancel**; behaviour tests unchanged
- [x] Matrix tests -- each row above, plus axe on each page

**Acceptance Criteria:**
- Given any of these pages, when it renders, then it has a title, a one-line subtitle and only the primary action listed.
- Given New Opportunity, when it renders, then import-from-file is above the fields inside a card, with **Create Opportunity** and **Cancel**.
- Given lint, typecheck, build and tests, when run, then all pass with no behaviour change.

## Implementation Notes

## Spec Change Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Unrelated prettier reflow in `create-form.tsx`, `list-page.tsx`, four `metadata` exports | low | patch | Reverted to the repo's existing layout. |
| Subtitle text per scope not asserted; test name hides the extra assertion; brittle sibling check | low | patch | `SUBTITLES` map asserted for both scopes; test renamed; sibling-tag check replaced. |
| `PlaceholderPage` message has no bottom padding | low | patch | Added `pb-gutter`. |
| Cancel not disabled while create pending or import in flight | low | rejected | Create navigates on completion anyway; an orphan import is harmless; the guard adds complexity. |
| Cancel discards typed input without confirmation | low | rejected | The spec says Cancel goes to `/opportunities`; no confirm was asked for. |
| Cancel ignores where the user came from | low | rejected | The spec fixes the target as `/opportunities`. |
| Subtitle can wrap or overflow | low | rejected | Copy is short; no truncation required, and the guard adds complexity. |
| `action` falsy `0` or empty string | false | rejected | Callers pass an element or `null`. |
| `PlaceholderPage` required `subtitle` breaks other callers | false | rejected | Typecheck and build pass; every caller passes it. |
| `aria-disabled` submit can fire mid-upload | false | rejected | `onSubmit` returns early on `pending` or `uploading`. |
| Hand-built `text-control` / `text-body-strong` on button links | false | rejected | Same idiom as `EmptyTabCard`. |
| Header shown when the list failed to load | low | rejected | The page title and action still apply; adds a branch for no demonstrated harm. |
| No `<header>` landmark, no `aria-describedby` on the subtitle | low | rejected | Cosmetic; axe passes. |
| Subtitle wording invented by the implementer | low | rejected | The spec gives no copy; wording is short and neutral. |
