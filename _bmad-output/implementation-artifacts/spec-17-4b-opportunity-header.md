---
title: 'Story 17.4b: Opportunity header breadcrumb, people chips and due countdown'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '000a705ef24e01d13a861152c64f664c73be2ac3'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-4a-opportunity-list.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Opportunity header is a title over a plain-text meta row. It has no breadcrumb, shows the owner and collaborators as text, and shows the proposal date with no countdown (Story 17.4, UX-DR5, UX-DR9, UX-DR23).

**Approach:** Add a breadcrumb, move the status pill beside the title, show the owner and each collaborator as a chip, and add a day countdown after the proposal date. Use only data the Opportunity API returns. **Submit** and **Resolve N blockers** are not built: they need the blocker data from Story 8.9 and 8.6 (logged in deferred-work).

## Boundaries & Constraints

**Always:**
- **Breadcrumb:** `nav aria-label="Breadcrumb"` with an ordered list: link **All Opportunities** to `/opportunities`, then the title as the current item (`aria-current="page"`, truncated, no link). Shown above the title in both the read-only and the editable header.
- **Status pill** (`StatusPill`) sits on the title row, right of the title. It keeps its icon and label.
- **People chips:** the owner as a chip (initials avatar, name, visually hidden "Owner: " prefix); each collaborator as its own chip (initials avatar, name, hidden "Collaborator: " prefix). With none: the text "No collaborators". Chips wrap.
- **Countdown:** after the proposal date, with an icon and text: "{n} days left" (plural-aware), "Due tomorrow", "Due today", "{n} days overdue". The overdue case uses the blocker tone. Computed from the UTC calendar date; `today` is passed down from the server layout so server and client agree. The editable header recomputes it from the date being edited or saved.
- The editable header keeps all behaviour: inline title and date edits, 412 stale notice with Reload, errors, announcements, `aria-busy`. Non-owners still get no buttons.
- Type classes outside `cn()`; reuse `ui/avatar`, `status-pill`, `formatDate`, `utcToday`. Existing tests pass with updated selectors only.

**Never:** Add **Submit**, **Resolve N blockers**, the right-pane toggle or blocker counts. Touch the tab strip, the list, the shell, tokens, `ui/*`, or any API call, action or data layer.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Future date | Due in 11 days | "11 days left" with a clock icon | N/A |
| Tomorrow / today | Due in 1 day / today | "Due tomorrow" / "Due today" | N/A |
| Overdue | Due 3 days ago | "3 days overdue" with a warning icon, blocker tone | N/A |
| No collaborators | `collaborators` empty | Owner chip and "No collaborators" | N/A |
| Owner edits date | `can_edit`, save a new date | Countdown follows the saved date | Existing error handling |
| Non-owner | `can_edit` false | Breadcrumb, chips and countdown; no buttons | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/workspace-header.tsx` -- read-only header and the shared `meta`; add the breadcrumb, `PersonChip`, `DueCountdown`, title row with pill; pass `today`, `breadcrumb`, `badge` to the editable header.
- `components/opportunities/inline-field.tsx:266-470` -- `EditableWorkspaceHeader`: accept `breadcrumb`, `badge`, `today`; render them; countdown uses `targetDate`.
- `lib/opportunities.ts` -- add `daysUntil(date, today)` and `countdownLabel(days)` beside `utcToday`/`formatDate`.
- `app/opportunities/[id]/layout.tsx:55` -- pass `today={utcToday()}`.
- Reuse `ui/avatar.tsx` (`Avatar`, `AvatarFallback`), `status-pill.tsx`.
- Tests: `workspace-header.test.tsx` (text at ~45, 72), `inline-field.test.tsx` (header tests ~145-310), `lib/opportunities.test.ts`, `app/opportunities/pages.test.tsx` (~515, 540).

## Tasks & Acceptance

**Execution:**
- [x] `lib/opportunities.ts` + tests -- `daysUntil`, `countdownLabel` (future, tomorrow, today, overdue, month and leap-day ends)
- [x] `workspace-header.tsx`, `inline-field.tsx`, `layout.tsx` + tests -- breadcrumb, pill beside title, chips, countdown in both headers
- [x] Matrix tests -- each row above, plus axe on both headers

**Acceptance Criteria:**
- Given an Opportunity, when the header renders, then it shows the breadcrumb, the title with its status pill, the owner and collaborator chips, and the proposal date with a countdown.
- Given the owner saves a new date, when the save succeeds, then the countdown shows the new date's count.
- Given axe, when it runs on the header, then there are no violations, and the countdown always has an icon and text.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- `Breadcrumb`, `PersonChip` and `DueCountdown` live in `header-parts.tsx`, not `workspace-header.tsx`: `inline-field.tsx` needs them and `workspace-header.tsx` already imports it (circular otherwise).
- `EditableWorkspaceHeader` renders `Breadcrumb` itself instead of taking a `breadcrumb` prop, so the crumb follows an edited title.

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Countdown icon assertion falls back to the whole container | low | patch | Now asserts the icon inside the countdown element. |
| Owner test depends on `nextSibling` | low | patch | Replaced with text assertions. |
| Breadcrumb not checked after a title save | low | patch | Added an assertion to the title-save test. |
| `initials()` never asserted | low | patch | New `header-parts.test.tsx` (two words, three words, one word, spacing, emoji, blank). |
| Long chip name can overflow | low | patch | Name span now `min-w-0 max-w-64 truncate`. |
| Countdown stale after midnight UTC, or off by one outside UTC | low | rejected | The spec fixes UTC with `today` from the server; same choice as the list's Due view. |
| Invalid calendar date rolls over, or malformed `today` | false | rejected | The API validates dates; `today` comes from `utcToday()`. |
| `DueCountdown` renders nothing for a non-date | low | rejected | Unreachable with API data; `daysUntil` NaN is tested. |
| Countdown does not follow an unsaved draft date | low | rejected | The spec says edited or saved; the draft is not committed. |
| No countdown test on the editable header for overdue, today or tomorrow, or after a failed save | low | rejected | One component renders all cases; the editable header's saved-date case is tested. |
| `pages.test.tsx` not updated | false | rejected | Those tests pass unchanged. |
| Owner also in collaborators, duplicate keys | false | rejected | Keyed by user id; the API does not list the owner as a collaborator. |
| Empty title in the breadcrumb | false | rejected | The API requires a title; the editor falls back to the customer name. |
| Collaborators lose a group label | low | rejected | Each chip carries a hidden "Collaborator:" prefix. |
| Badge wraps while the title is edited | low | rejected | Cosmetic. |
| Two headers duplicate layout; third `initials` copy | low | rejected | Pre-existing duplication; unifying touches the shell files this story must not. |
| Breadcrumb not a prop on the editable header (spec Code Map) | low | rejected | Deliberate: it follows the edited title; see Implementation Notes. |
| Long lines, "left" wording, combining-mark initials, Users icon test | low | rejected | Cosmetic or no demonstrated harm. |
