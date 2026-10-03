---
title: 'Story 1.5 (Part B): App shell and keyboard model'
type: 'feature'
created: '2026-10-02'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'f04788b4b9b34d5e3201263657f118a075f25500'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A signed-in user with a role lands on a placeholder page that has no navigation, no keyboard model and no responsive layout. Every later screen needs the shell.

**Approach:** Build the shell: a sidebar, a main pane, and a right-pane container toggled with `]`. Add the `⌘K`/`Ctrl+K` palette, `g` navigation, the `?` cheat sheet and `Esc` layering, and honour the single-key-shortcuts preference from Part A. Follow the EXPERIENCE.md responsive tiers, with a read-only notice below 1024px. Each nav item gets a placeholder page. Axe and keyboard tests run in the existing Vitest suite.

## Boundaries & Constraints

**Always:**
- **Sidebar:** 220px wide, in this order: Inbox, My Opportunities, All Opportunities, Knowledge, Reports, Admin, each with a lucide icon. Admin appears only for `platform_administrator`. The avatar menu (with Settings and Sign out) sits in the sidebar footer.
- **Landing:** `/` redirects users with `presales_engineer` to My Opportunities and everyone else to Inbox.
- **Keyboard:**
  - `g` then `i`, `m`, `a`, `k` or `r` within 1s navigates. `]` toggles the right pane, `[` collapses the sidebar, `?` opens the cheat sheet, and `Esc` closes the topmost layer: palette or cheat sheet first, then the right pane.
  - All shortcuts are ignored while focus is in an input, textarea, select or contenteditable.
  - When single-key shortcuts are off, `g`, `]`, `[` and `?` are ignored. `Ctrl+K`/`⌘K` and `Esc` always work.
  - Every shortcut also has a visible control.
- **Palette:** lists the navigation commands (Admin only for admins) and Settings, is fuzzy-filtered as you type, runs on Enter and closes after running.
- **Responsive tiers:**
  - ≥1440: all panes docked.
  - 1280–1439: the right pane overlays the main pane; the sidebar can collapse.
  - 1024–1279: the sidebar shows icons only.
  - <1024: the shell shows "The workbench needs a wider screen. You can view Opportunities here, but editing is disabled." Navigation still works.
- **Accessibility:**
  - Landmarks: `nav[aria-label="Primary"]`, `main` and `aside[aria-label]`. Tab order runs sidebar → main → right pane.
  - One polite `aria-live` region is mounted, with a throttled `announce()` (one message per 5s).
  - The palette and cheat sheet trap focus and return it on close.
- **Access gating:** stays per page via `getMe`/`hasAccess`/`AccessGate`, never only in a layout. The no-roles, signed-out and unavailable states render without the shell.

**Never:** No Opportunity data, lists, inspector or activity content, Inbox items, or Admin features. No backend changes. No Playwright and no auth bypass. No new preference storage, because Part A's cookie is reused.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Landing PSE | Roles include `presales_engineer` | `/` → `/my-opportunities` | N/A |
| Landing other | e.g. `pm_reviewer` only | `/` → `/inbox` | N/A |
| Admin nav | Non-admin / admin | Admin hidden / shown; non-admin `/admin` shows "You don't have access to this page" | N/A |
| Palette | `Ctrl+K`, type "know", Enter | Navigates to Knowledge; palette closes | N/A |
| g-nav | `g` then `r` | Reports | Another key, or more than 1s, cancels |
| Typing | `g r`, `?` or `]` inside an input | Nothing happens | N/A |
| Shortcuts off | Preference off; `?`, `g r`, `]` | Ignored; `Ctrl+K` and `Esc` still work | N/A |
| Esc layering | Palette open over an open right pane | First `Esc` closes the palette, the second closes the pane | N/A |
| Narrow | Width 1000px | Read-only notice; nav still works | N/A |
| No roles | User with no roles opens any shell page | Only the Story 1.4 no-access message and avatar menu, no sidebar | N/A |
| Unknown page | Signed in with a role, `/nope` | "This page does not exist." inside the shell | N/A |

</frozen-after-approval>

## Code Map

- `web/src/app/page.tsx`, `web/src/app/not-found.tsx`, `web/src/app/settings/page.tsx` -- each runs `getMe()`, then `hasAccess`/`AccessGate`, then `SignedInHeader`. Replace `SignedInHeader` with the shell for users with access. `/` becomes the landing redirect.
- `web/src/components/access-gate.tsx` -- `hasAccess`, `AccessGate`, `SignedInHeader`. The doc comment explains why gating isn't done in a layout; keep the gate. `SignedInHeader` stays for the no-roles state, because the avatar menu is needed to sign out.
- `web/src/components/avatar-menu.tsx` -- a `@base-ui/react/menu` with Settings and Sign out; move it into the sidebar footer.
- `web/src/lib/preferences.ts` -- `getPreferences()` (server) and `Preferences.singleKeyShortcuts`. Client code must `import type` only, and receives the value as a prop.
- `web/src/lib/api/server.ts` -- `Me.roles` is typed as `components["schemas"]["Role"][]`.
- `web/src/app/globals.css` -- size tokens `w-sidebar`, `w-inspector`, `w-rail`, `h-row`, `p-gutter`; `bg-surface-sidebar`, `bg-surface-inspector`; text roles.
- `web/components.json` -- shadcn `base-nova` (Base UI). Add `command` (cmdk) and `dialog` through the shadcn CLI. The `@/hooks` alias folder doesn't exist yet.
- `web/vitest.config.mts`, `web/src/test/{setup,axe}.ts` -- Vitest + jsdom, with `axeViolations(container)`. Mock patterns are in `access-gate.test.tsx` and `layout.test.tsx`.
- jsdom has no layout. Implement the tiers with Tailwind breakpoint classes (`min-[1024px]`, `min-[1280px]`, `min-[1440px]`, configured as custom breakpoints), so tests assert the classes and the notice, not the measured widths.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/navigation.ts` -- nav items (label, href, icon, g-key, adminOnly), `visibleNav(roles)` and `landingFor(roles)`
- [x] `web/src/components/shell/{app-shell,sidebar,right-pane,read-only-notice,live-region,shell-context}.tsx` -- the shell layout and client state (sidebar collapsed, right pane open, a layer stack for `Esc`); `AppShell({me, preferences, children})`
- [x] `web/src/components/shell/{command-palette,cheat-sheet,keyboard-shortcuts}.tsx`, `web/src/components/ui/{command,dialog}.tsx` -- palette, cheat sheet, global key handler with `g`-sequence timer, input guard and single-key toggle
- [x] `web/src/app/{inbox,my-opportunities,opportunities,knowledge,reports,admin}/page.tsx`, `web/src/app/page.tsx`, `web/src/app/not-found.tsx`, `web/src/app/settings/page.tsx` -- gated pages rendered inside `AppShell`. Each placeholder shows its title and "Not available yet."; Inbox shows "Nothing waiting for you."; Admin is gated to admins; `/` redirects via `landingFor`.
- [x] `web/src/lib/navigation.test.ts`, `web/src/components/shell/*.test.tsx`, `web/src/app/**/page.test.tsx` -- every matrix row; axe finds no WCAG 2.1 AA violations on the shell, open palette, cheat sheet, right pane and read-only notice; tab order sidebar → main → right pane

**Acceptance Criteria:**
- Given any shell page, when it renders, then exactly one `nav[aria-label="Primary"]`, one `main` and one polite live region exist.
- Given the cheat sheet, when opened, then it lists every shortcut that the key handler implements, from one shared definition.
- Given CI, when it runs, then lint, typecheck, `npm test` and the build pass, along with the existing compose checks.

## Implementation Notes

- Shortcuts are defined once in `web/src/lib/shortcuts.ts` (`SHORTCUTS`, derived g-keys from `NAV_ITEMS`); the key handler matches against it and the cheat sheet renders it. A test iterates `SHORTCUTS` and fails for any id without an implemented effect.
- The key handler listens on `window` in the capture phase, so `Esc` with a dialog open closes only that dialog (and stops propagation) before Base UI sees it; with no dialog it closes the right pane. `Esc` inside a text field or an open menu is left to that control. Single keys are also inert while a dialog is open. `Ctrl+K` inside the palette's own field closes it.
- Tiers use Tailwind's arbitrary `min-[1024px]`/`min-[1280px]`/`min-[1440px]` variants (no theme config needed). Below 1440 the right pane overlays the main pane (including 1024-1279); the sidebar is icons-only below 1280 and whenever collapsed with `[`.
- One live region: `SettingsForm`'s own `role=status` region was removed; it now calls `announce()` and keeps the visible error text.
- shadcn `add command dialog` also brought in `input`, `input-group` and `textarea` (dependencies of `command`) and the `cmdk` 1.1.1 package (with its Radix deps).
- Review fixes: `ShellProviders` (live region + shell state, no page content) now wraps `children` in the root layout, with `singleKeyShortcuts` from the layout's `getPreferences()`, so sidebar/right-pane state survives navigation. `AppShell` is therefore `AppShell({me, children})` (no `preferences` prop) and still renders only after each page's gate. Closing the right pane with focus inside it moves focus to its toggle. The live region empties itself 50ms before each write, so repeats are re-read.
- `AvatarMenu` gained optional `side`/`align` props so it opens upward from the sidebar footer.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | Sidebar-collapse and right-pane state reset on every navigation | medium | Each page renders its own `AppShell`, so a route change unmounts the providers. Moving `LiveRegionProvider` and `ShellProvider` (state only, no content) into the root layout keeps per-page gating intact | patch |
| 2 | ECH | `[`/`]` never fire on AltGr layouts (German, Nordic) | medium | Windows reports AltGr as Ctrl+Alt, and `matchesKey` requires `!mod && !altKey`. The users are EU-based | patch |
| 3 | BH, ECH | Closing the right pane drops focus to `<body>` | medium | `RightPane` returns `null` while its close button is focused; focus doesn't go back to the toggle | patch |
| 4 | BH | The input guard treats radios and checkboxes as text fields | medium | `closest("input, ...")` matches every input, so shortcuts die while a Settings radio is focused | patch |
| 5 | BH, VG, ECH | Repeating the same announcement is silent | low | The live-region text doesn't change on a second identical message. Clearing it first is direct | patch |
| 6 | BH | `CommandDialog`'s sr-only title and description render outside the popup | low | `DialogHeader` is a sibling of `DialogContent` under Root, so it sits in the page DOM while closed; moving it inside is direct | patch |
| 7 | BH | The palette search field shows no focus indicator | low | The input has `outline-hidden` without `data-slot="input-group-control"`, so the group ring never applies | patch |
| 8 | ECH | The palette has no visible close control | low | `showCloseButton=false`; the spec requires a visible control for each shortcut (Esc) | patch |
| 9 | BH, ECH | `g` sequences fail with Caps Lock or Shift | low | Exact `event.key` comparison; lowercasing letters is direct | patch |
| 10 | ECH | Key repeat floods toggles | low | Holding `]` re-toggles; an `event.repeat` guard is direct | patch |
| 11 | ECH | Ctrl+Shift+K takes over browser shortcuts | low | `shiftKey` unchecked; direct | patch |
| 12 | ECH | Typing in the open avatar menu triggers single-key shortcuts | low | `g i` inside `role="menu"` navigates; extend the existing menu guard | patch |
| 13 | BH | Icon-only sidebar buttons have no tooltip | low | Links have `title`, buttons don't; direct | patch |
| 14 | VG | Ctrl+K closing an open palette untested | medium | Deleting that branch leaves the suite green | patch |
| 15 | VG | Esc in a field or menu keeping the right pane open untested | medium | Deleting the guard leaves the suite green | patch |
| 16 | VG | ⌘/Ctrl label untested | low | Inverting `isMac()` stays green; one assertion | patch |
| 17 | BH | Throttle can delay or drop an error announcement | low | The one-per-5s throttle is mandated by the frozen spec | reject |
| 18 | BH | Ctrl+K does nothing inside a text field | false | The frozen spec says all shortcuts are ignored in inputs | reject |
| 19 | BH | The read-only notice isn't enforced (Settings still saves below 1024px) | low | Real; enforcement needs a read-only context that later editing stories will consume, so the fix adds a mechanism | reject |
| 20 | BH, ECH | Collapse does nothing visible at 1024–1279px; its label never changes | low | Icon-only already; `aria-pressed` toggle with a fixed name is a valid pattern | reject |
| 21 | BH | Non-admin `/admin` has no `<h1>` and returns 200 | low | No named harm; the matrix asks only for the message | reject |
| 22 | BH | Palette has only navigation | false | The spec scopes it to navigation and Settings | reject |
| 23 | BH, ECH | `useAnnounce` silent without a provider | low | `SettingsForm` always renders inside the shell | reject |
| 24 | BH | Settings test weakened to `findAllByText` | low | Duplicate text (visible plus live region) is intended | reject |
| 25 | BH | Generated shadcn files: style and unused exports | low | CLI output, kept as generated | reject |
| 26 | BH | Diff omits lockfile and spec | false | Deliberately excluded from the review diff | reject |
| 27 | BH | Key listener re-registers on every state change | low | Negligible cost; no named harm | reject |
| 28 | ECH | Stale closure in `toggleRightPane` on rapid keydowns | maybe-false | React flushes discrete events synchronously between keydowns; would be low | reject |

## Verification

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
- `curl -I localhost:3000/inbox` without a session -- expected: 307 to `/auth/login?returnTo=%2Finbox`

**Manual checks (human, signed in with roles):**
- Palette, `g` sequences, `?`, `]`, `[` and `Esc` behave as in the matrix. Turning shortcuts off in Settings disables the single keys. Resizing through 1440, 1280 and 1024 shows each tier.
