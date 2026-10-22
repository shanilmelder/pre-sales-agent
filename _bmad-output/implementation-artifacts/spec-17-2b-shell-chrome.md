---
title: 'Story 17.2b: Shell chrome (sidebar, user card, pane tabs, skip link, announcements)'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: '3d5de23a6c45c5f69599d1d87706e29dd4cec903'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-1b-ui-primitives.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-2a-settings-and-preferences.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The built shell has none of the redesigned chrome: the sidebar has no organisation switcher and its footer avatar is a bare initials menu with no role or theme toggle, the right pane has no Inspector and Activity tabs and says "Nothing selected.", there is no skip link, and navigating announces nothing (Story 17.2, UX-DR2, UX-DR4, UX-DR7, UX-DR23, NFR-7).

**Approach:** Per EXPERIENCE.md the sidebar holds the chrome, top to bottom: an organisation switcher, the Search button, the navigation, and a footer with Keyboard shortcuts, Collapse sidebar and the user card. Tab the one right pane, add a skip link and announce the screen name on navigation. Offline strip and responsive checks are Story 17.2c.

## Boundaries & Constraints

**Always:** Organisation switcher is a static label with the text "Pre Sales Agent Framework" and no menu (one organisation; no API organisation name exists). Sidebar 220px, collapses to 64px with a 0.16s width transition, off under `prefers-reduced-motion`; labels stay in the accessibility tree when collapsed. The user card shows the avatar (`ui/avatar`, circle), name, role label and a theme toggle button (cycles Light and Dark, saves through `savePreferences` with the other stored values kept); the avatar button opens Settings. Keep `[`, `?`, Ctrl/Cmd+K and the existing nav and Reports/Admin visibility. Right pane stays 420px: Inspector and Activity tabs, closed by default, selecting a row opens it on Inspector, `]` cycles closed/open/closed, `Esc` closes it; empty Inspector text is "Select a gap or estimate line to see its details."; the Activity tab says "No activity yet." Skip link: first tab stop on every shell page, primary fill, white text, hidden above the viewport, `top: 8px` on focus, jumps to `<main id>`. A polite live region announces the screen name on navigation (use the page title without the product suffix, through the existing `useAnnounce`). Use 17.1b primitives; type classes outside `cn()`.

**Never:** Add a global header, a real organisation switcher or API change. Touch the Offline strip or responsive tiers (17.2c). Change Settings or preferences defaults (17.2a). Build an activity feed.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First tab stop | Any shell page loads, press Tab | Skip link is focused and visible; Enter moves focus to main | N/A |
| Navigation | Go from Inbox to Knowledge | Live region announces "Knowledge" once | No title: announce nothing |
| Pane, nothing selected | Press `]` | Pane opens on Inspector with the empty text | N/A |
| Pane, row selected | Select a gap row | Pane opens on Inspector with its content even if Activity was active | N/A |
| Activity tab | Choose Activity | Shows "No activity yet."; Inspector content stays mounted | N/A |
| Theme toggle | Click toggle in user card | Theme flips, cookie saved, other preferences kept | Save fails: roll back, announce |
| Collapsed sidebar | Press `[` | 64px, icons only, labels still readable by screen readers | N/A |

</frozen-after-approval>

## Code Map

- `web/src/components/shell/{app-shell,sidebar,right-pane,shell-context,live-region}.tsx` -- shell layout, nav, pane (already 420px via `w-inspector`; `]`, `Esc`, state, focus return exist), announcements.
- `web/src/components/avatar-menu.tsx` -- bare initials menu; replace in the sidebar with the user card (reuse the menu for Sign out).
- `web/src/app/layout.tsx` -- source of stored preferences; pass theme and density into the shell for the toggle.
- New: `components/shell/{skip-link,screen-announcer,user-card}.tsx`.
- `web/src/lib/navigation.ts` -- nav items. `app/settings/actions.ts` -- `savePreferences`.
- Reuse `ui/avatar`, `ui/tooltip`, `ui/button`. Tests: `components/shell/app-shell.test.tsx`, `live-region.test.tsx`, new tests for the three new components, `pages.test.tsx` suites that render the shell.

## Tasks & Acceptance

**Execution:**
- [ ] `skip-link.tsx`, `app-shell.tsx` -- skip link and `<main id>`.
- [ ] `screen-announcer.tsx` + test -- announce the screen name on navigation.
- [ ] `sidebar.tsx`, `user-card.tsx` + tests -- org label, Search, footer user card with role and theme toggle, 0.16s collapse.
- [ ] `right-pane.tsx` + tests -- Inspector and Activity tabs, empty text, content kept mounted.
- [ ] Existing shell tests -- update selectors and add the matrix rows.

**Acceptance Criteria:**
- Given any shell page, when the page loads, then the skip link is the first tab stop and the screen name is announced politely.
- Given the sidebar, when it renders, then the organisation label, Search, navigation, Keyboard shortcuts, Collapse sidebar and the user card show in that order, and collapse to 64px keeps every control reachable by keyboard and screen reader.
- Given the right pane, when it opens, then Inspector and Activity are tabs (arrow keys move between them), and axe is clean in the shell tests.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- The avatar is a link to /settings; a compact "…" menu beside it holds Settings and Sign out.
- The theme toggle flips the `dark` class at once and saves; `ThemeScript` keeps it in step under System.
- `RightPaneContent` returns the pane to Inspector when it mounts or its keyed child changes; opening the pane always starts on Inspector.
- Icon-only sidebar width is now 64px (`w-sidebar-collapsed`) on every collapsed tier.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Gap | No test that reopening the pane returns to Inspector | medium | Verified: the reset line could be deleted with every test passing. Added a reopen-after-Activity test. | patch |
| 2 | Gap | Theme toggle takes density from the shell context but no test uses a non-default density | medium | Verified: tests only used the default. Added a compact-density case (renderShell takes density). | patch |
| 3 | Edge, Blind | Theme toggle uses `disabled`, which drops keyboard focus mid-save | medium | Real: a disabled button blurs. Now `aria-disabled` with clicks ignored while pending. | patch |
| 4 | Edge | Alt/Ctrl/Meta+Arrow on a tab swallows browser Back | low | Direct one-line guard; test added. | patch |
| 5 | Blind | Doc comments lost their full stops in 4 files | low | Real, trivial; sentences restored. | patch |
| 6 | Gap, Blind, Edge | EMPTY_INSPECTOR wording (gap or estimate line) shows on every page with a pane | medium | The spec's frozen AC dictates that text; per-page copy is a spec decision, so not patched here. | defer |
| 7 | Edge, Blind | `RightPaneContent` switches to Inspector only on mount or a child key change (unkeyed or background key change) | maybe-false | Cannot tell without auditing the 12 consumers: whether each keys its inspector by selection id, and whether polls change keys. Would be medium. | defer |
| 8 | Gap | `ScreenAnnouncer` mount in AppShell is not asserted | low | Component is covered; the mount is one line. | rejected |
| 9 | Edge | Toggle under System with an OS-dark browser flips the wrong way | false | ThemeScript keeps `.dark` in step with the resolved theme, so the class read is correct. | rejected |
| 10 | Edge, Blind | `theme` in the shell context is unused | low | Harmless; Story 17.2c or 17.3 can use or drop it. | rejected |
| 11 | Edge | Both pane panels are `flex` and rely on `hidden` | false | Built CSS has `[hidden]{display:none!important}`. | rejected |
| 12 | Edge | Skip link click does nothing when `#main-content` is missing | false | The skip link renders only inside AppShell, which renders the main element. | rejected |
| 13 | Edge, Blind | ScreenAnnouncer: fixed 100ms wait, 5s throttle, pathname-only deps, duplicated product string | low | Behaviour is the spec's polite announcement; throttle is the shell's single live region. | rejected |
| 14 | Edge, Blind | roles[0] only; initials() duplicated; org label and test ids hard-coded | low | Cosmetic or a single-organisation constant; no named caller to break. | rejected |
| 15 | Edge | Collapsed or 48px footer controls may overflow | low | Sidebar is 64px (token verified); below-1280px tier belongs to 17.2c. | rejected |
| 16 | Edge | No skip link outside AppShell (login, error pages) | low | The spec says shell pages. | rejected |
| 17 | Blind, Edge | Tabpanels lack tabindex, Home/End untested, class-string tests, test leaks `dark` | low | Style or coverage nits; the leaked class is removed in the same test. | rejected |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.
