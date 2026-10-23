---
title: 'Redesign the theme and App Shell to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '2cf03b93d12b1910b81b7f9767f5d21f51e15e1f'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-2b-shell-chrome.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app's colour tokens already match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`), but the shell and page frame don't. The sidebar is a dense icon list with a building-icon label, a 48px empty top bar holds only the pane toggle, page headers sit on the canvas with a 20px gutter, the workspace tabs are 13px with digit hints, and the right pane tabs are underlined rather than segmented.

**Approach:** Restyle the shell chrome and the page frame to the mockup. That covers the sidebar, the page header band on every shell page, the Opportunity header and tabs, the right pane header, the content padding, and the outline and border strength. Keep every behaviour, shortcut, ARIA contract and API call as it is today.

## Boundaries & Constraints

**Always:**
- **Sidebar** (`surface`, right `border`, padding 12px 10px, gap 4px, 220px collapsing to 64px as today):
  - **Org row:** a 26px `primary` tile with white initials (radius 7px), the org name at 14px semibold, then a chevron. It stays static with no menu.
  - **Search:** a `surface-alt` box with a `border`, 13px `text-secondary` text, and the ⌘K hint on the right.
  - **Nav items:** 18px icons, gap 10px, padding 7px 8px, radius 8px, 14px text. Inactive items are `text-secondary` at weight 500. The active item is `primary-tint` with `primary-text` at weight 600.
  - **Footer:** Keyboard shortcuts and Collapse sidebar at 13px `text-secondary` with a `surface-alt` hover. Then, above a top border, the user card: a 32px `primary-tint` avatar, the name at 13px/500, the role at 12px, and a 30px bordered theme toggle. Keep the account menu.
- **Remove the top bar.** The right-pane toggle (same id, `aria-pressed` and title) moves into the page header. It is a bordered `surface` button, 34px on plain pages and 28px on the Opportunity breadcrumb row.
- **Page header** (new shared component, used by every shell page except the Opportunity workspace):
  - **Band:** `surface` with a bottom `border`, padding 28px 32px 20px.
  - **Text:** an h1 at 24/32 semibold, then a 13px `text-secondary` subtitle.
  - **Actions:** an optional primary action, then the pane toggle.
  - **Subtitles:** use the mockup's copy for Opportunities, New Opportunity, Inbox, Knowledge, Reports and Admin. Settings reads "Saved in this browser." (the mockup's copy; preferences are a browser cookie)
  - **Primary actions:** show only actions that exist today (New Opportunity, Create Opportunity).
- **Content area:** `background` (`#F7F7FA` light), padding 28px 32px 40px, sections spaced 24px apart. Add one spacing token for the 32px page inset. Leave `--spacing-gutter` and inner component padding alone.
- **Opportunity header:**
  - **Band:** a `surface` band with padding 24px 32px 0 and a bottom border, wrapping the breadcrumb row (with the 28px pane toggle on the right), the title row and the tab strip.
  - **Tabs:** 14px, padding 12px 10px. Inactive tabs are `text-secondary` at weight 500. The active tab is `primary-text` at weight 600 with a 2px `primary` underline.
  - **Count pills:** a `surface-alt`/`text-secondary` pill at 12px/500. Gaps and Conflicts counts use `blocker-tint`/`blocker`.
- **Right pane header:** padding 12px 16px. The Inspector and Activity tabs become segmented buttons at 13px/500, radius 7px; the selected one is `primary-tint`/`primary-text`. Close is a 28px ghost button. Keep the tablist semantics and arrow keys.
- **Global CSS:** a 120ms colour transition on buttons and links, off under reduced motion. Thin scrollbars in `border-strong`.
- Light and dark both match the mockup's two palettes.
- Keep `ShellProviders`, shortcuts (`[`, `]`, `?`, Ctrl/Cmd+K, Esc), the skip link, announcements, the Offline strip, the read-only notice and the narrow-viewport tiers.

**Decisions:**
- **Organisation:** keep the text "Pre Sales Agent Framework", with a "PS" tile in place of the building icon.
- **Borders:** match the mockup. `--border-strong` becomes `#CDD1E0` (light) and `#3A4054` (dark), so outline buttons and inputs get the mockup's lighter borders. This was accepted knowing input boundaries then fall below WCAG 3:1 non-text contrast.
- **Tab digits:** remove the shortcut digits from the workspace tab labels. The shortcuts, `aria-keyshortcuts` and the cheat sheet entries stay.

**Never:** Show data or actions the API lacks: an Inbox count, Submit, Resolve blockers, Mark all read, Add source, Export or Invite user. Add the mockup's demo bar or its 1440×900 frame. Change API calls, routes or tab content components. Add a real organisation switcher.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plain page | Open Knowledge | Page header band with title, subtitle and pane toggle; no top bar | N/A |
| List page, can create | Open All Opportunities with create permission | "New Opportunity" primary action beside the pane toggle | N/A |
| Workspace | Open an Opportunity | Breadcrumb row with the 28px toggle, title row, 14px tabs; Gaps count in red tint | N/A |
| Pane toggle | Press `]` or click the header toggle | Pane opens; focus returns to the toggle on Esc as today | N/A |
| Collapsed sidebar | Press `[` | 64px, org tile and icons only, labels still sr-only | N/A |
| Dark theme | Toggle theme | Every surface uses the dark palette | N/A |
| Error page | Opportunity not found | Header band still renders the toggle | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `app/globals.css` -- tokens already equal the mockup's, apart from `--border-strong` (see Decisions). Add `--spacing-page` (32px), the global transitions and the scrollbar rules here.
- `components/shell/sidebar.tsx` -- restyle the org row, Search, nav and footer per the Boundaries. Keep the collapse logic (`label`/`hint` classes) and `data-testid="org-switcher"`.
- `components/shell/user-card.tsx` -- avatar, name and role sizes, plus the bordered theme toggle. Keep the save and rollback logic.
- `components/shell/app-shell.tsx` -- delete the `h-12` top bar. Export `RightPaneToggle` with a `size` prop. `PlaceholderPage` uses the new header.
- New `components/shell/page-header.tsx` -- `PageHeader({ title, subtitle, action? })` renders the band and the toggle. Use the page-content wrapper for the 28/32/40 padding.
- `components/shell/right-pane.tsx` -- header and segmented tabs only.
- `components/opportunities/workspace-header.tsx`, `inline-field.tsx` (`EditableWorkspaceHeader`), `header-parts.tsx` (`Breadcrumb`) -- the surface band, and the toggle on the breadcrumb row.
- `components/opportunities/workspace-tabs.tsx` -- tab and count-pill styling; drop the digit `<span>`. Keep roving focus, `aria-keyshortcuts` and the sr-only count labels.
- Pages that use `AppShell`: `app/{inbox,reports,settings,knowledge,knowledge/checklists,admin,admin/users,admin/catalogue,admin/evals,not-found}`, `app/opportunities/{list-page,new/page,[id]/layout}.tsx`. Replace each hand-made `h1` block with `PageHeader`. Keep `KnowledgeNav` and the admin sub-navs below it.
- `components/ui/button.tsx` -- the outline variant takes `border-border-strong` (its value changes in `globals.css`).
- Tests: `components/shell/app-shell.test.tsx` (top-bar and toggle selectors), new `page-header.test.tsx`, plus the `pages.test.tsx` suites that query headings or the toggle.

## Tasks & Acceptance

**Execution:**
- [x] `app/globals.css` -- page spacing token, transitions, scrollbars, and the `--border-strong` values
- [x] `components/shell/page-header.tsx` + test -- shared header band with the toggle
- [x] `components/shell/app-shell.tsx`, `right-pane.tsx` -- remove the top bar, export the toggle, restyle the pane header
- [x] `components/shell/sidebar.tsx`, `user-card.tsx` -- mockup sidebar
- [x] `components/opportunities/{workspace-header,inline-field,header-parts,workspace-tabs}.tsx` -- workspace band and tabs
- [x] Every `AppShell` page -- adopt `PageHeader` and the content padding
- [x] Shell and page tests -- update selectors and add the matrix rows

**Acceptance Criteria:**
- Given any shell page at 1440px in light and dark, when it renders, then the sidebar, header band, content area and right pane match the mockup's spacing, type and colours.
- Given the shell tests, when run, then axe stays clean and the skip link, announcements and shortcuts behave as before.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- The toggle lives in `components/shell/right-pane-toggle.tsx` and is re-exported from `app-shell.tsx`, so `page-header.tsx` (imported by `app-shell`) has no import cycle.
- `PageHeader` and `PageContent` (28/32/40, gap 24) are both in `page-header.tsx`, with the subtitles in `PAGE_SUBTITLES`. The Opportunity workspace keeps its tab panel as it is. Its band is the header (`WORKSPACE_BAND`, `bg-surface px-page pt-6`) plus the tab strip (`bg-surface`, bottom border).
- Users & roles keeps its "roles as of last sign-in" note and Auth0 link as its subtitle. Catalogue and Evals use the Admin subtitle.
- The no-access and not-found states, including the workspace's "Opportunity" not-found and error states, render a `PageHeader` so the toggle is always there.
- New Opportunity's header button submits the form through `form={CREATE_FORM_ID}`. The form's own button stays.
- The page frame alone owns the outer inset (verification fix). The strips and toolbars directly inside `PageContent` no longer carry an outer gutter: the nav strips, filter bar, toolbars, Pagination, create form, evals view and empty states. The first cell of each table now uses `px-3`, so text sits about 44px from the edge instead of 52px. The workspace tab route wrappers use `px-page pt-7 pb-10`, and the Offline strip, read-only notice and shortcut hint use `px-page`. The New Checklist form (`checklists-tab.tsx:217`) is right-pane content, so it keeps its padding.
- `contrast.test.ts` drops the `border-strong` 3:1 pairs and records the new values, as the Decisions accept.

## Spec Change Log

- **Review 1, Settings subtitle (intent_gap, resolved by the human without a revert):** the frozen text "Saved for your account." was false, because preferences live in a browser cookie. The human changed it to the mockup's "Saved in this browser." and chose to keep the code and patch only the string. KEEP: everything else in the implementation.

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Settings subtitle "Saved for your account." contradicts the body's "Saved in this browser." (blind) | medium | intent_gap | Preferences are a cookie (`app/settings/actions.ts`), so the frozen subtitle is false; only the human can change the frozen text. |
| `border-strong` below 3:1 on inputs, switch off track, chips and radio cards; contrast pairs removed (verification, edge, blind) | low | rejected | The human chose to match the mockup knowing it fails 3:1; the mockup's own switch off track and inputs use `--border2` (#CDD1E0). |
| DESIGN.md still lists `#80869D`/`#737A94` and the old ratios, while `contrast.test.ts` "DESIGN.md colour values" asserts the new ones (blind) | low | patch | The design source and its mirror test now disagree; the next token edit will follow the wrong source. |
| Stale comments: "No title" above `title="Opportunity"`; "no section title" above `title="No access"` (blind) | low | patch | Comments contradict the code beside them. |
| `px-page pt-7 pb-10` copied into nine tab wrappers plus `PageContent` (blind) | low | patch | A change to the page inset has to be made in 10 places, and a missed one will misalign the tab content with its header. |
| Header Create Opportunity has no pending or "Creating…" state (blind, edge x2) | low | rejected | `onSubmit` guards against a double submit, and the form's own button shows "Creating…"; a fix needs a new client component sharing form state. |
| Tab strip hides its scrollbar (blind, edge) | low | rejected | The mockup's tablist uses `scrollbar-width:none`; the strip fits at 1440px. |
| Digit hints gone for sighted users (blind, edge) | false | rejected | Removing them was a human decision; they stay in the cheat sheet. |
| Chevron on a static org row (blind) | false | rejected | The frozen spec asks for the chevron with no menu. |
| Raw px sizes instead of type tokens; classes outside `cn()` (blind) | false | rejected | No 13px token exists; type classes outside `cn()` are the repo convention (`ui/button.tsx` comment). |
| Toggle scrolls away with the header (blind) | low | rejected | The mockup's header also scrolls inside `main`; `]` still works. |
| `.h-12` and direct-child-only test checks are brittle (blind) | low | rejected | No demonstrated miss; the behaviour is also covered by toggle-placement tests. |
| Admin subtitle names "agents"; Knowledge names "coverage" (blind) | low | rejected | The frozen spec says to use the mockup's copy. |
| Page header row cannot wrap (edge) | false | rejected | The title block is `min-w-0 flex-1`, so the h1 text wraps; only the action and toggle are `shrink-0`. |
| Esc focus falls to body when no toggle exists (edge) | false | rejected | Every `AppShell` page, including the error states, now renders a header with the toggle; only an isolated test tree lacks one. |
| Current breadcrumb item same colour as the link (edge) | low | rejected | Matches the mockup (both `text2`); the current item is plain text with `aria-current`. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot Opportunity Overview, All Opportunities and Knowledge in light and dark at 1440px and compare them with the mockup.
