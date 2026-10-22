# Epic 17 Context: Redesign refit (visual identity and shell)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Apply the 2026-10-21 redesign to the built web app and to the shell that later stories build on: one token layer and primitive set, a new app shell with Settings and accessibility behaviours, built Opportunity tabs refitted, the Opportunity list and header chrome, and the built pages outside the workspace refitted. Behaviour of built screens does not change. The epic has no FR and Epic 1 stays closed (its visual identity is superseded, not reopened). The token and primitive story must land before any new UI story in any epic.

## Stories

- Story 17.1: Token layer and primitives
- Story 17.2: App shell, Settings and accessibility behaviours
- Story 17.3: Refit built tabs to the redesign
- Story 17.4: Opportunity list and Overview chrome
- Story 17.5: Refit built pages outside the workspace

## Requirements & Constraints

- Every colour, type, radius, spacing and shadow token must match the design spec in light and dark. Contrast pairs are asserted in a test that fails CI on regression.
- Primitives (Button, Status pill, Card, Input, Select, Tabs, Switch, Dialog, Table, Skeleton, Avatar, Tooltip) follow the design spec: tint-filled pills, 12px cards, disabled opacity .4, strong borders on inputs, secondary buttons, chips and the switch. The mono font is removed. Page titles read "Pre Sales Agent Framework".
- Running state is a static loader icon, with no pulsing dots.
- Status and countdowns always show an icon or text, never colour alone.
- Accessibility: WCAG 2.1 AA, axe in CI with no violations on refitted pages; skip link is the first tab stop; a polite live region announces the screen name.
- Responsive tiers: >=1440 all panes docked; 1280-1439 right pane overlays; 1024-1279 sidebar collapses to icons; <1024 read-only notice. Minimum supported width is 1280.
- No behaviour change: existing test suites must pass with updated selectors only.
- Empty-tab, loading (skeleton rows), 412 stale-save (inline alert with Reload and View diff) and Offline (strip with Retry after 60 s down) states follow the shared state patterns.
- Non-Opportunity pages share a page header (title, one-line subtitle, one primary action, right-pane toggle). Admin "Invite user" appears only once Story 1.10 is built.

## Technical Decisions

- UI preferences (theme, density, single-key shortcut switch) live in the `psa_prefs` cookie read by the root layout. No server table and no localStorage, so server rendering paints the correct theme.
- The shortcut switch defaults to Off on first visit with a first-run hint (the built code defaults to On, so this changes).
- Web uses only the client generated from the API's OpenAPI spec; live updates use the per-Opportunity SSE stream.
- Stack: Next.js with Tailwind CSS 4.x and shadcn/ui as the primitive seed.

## UX & Interaction Patterns

- One 420px right pane with Inspector and Activity tabs replaces the 300px activity rail. Closed by default; selecting a row opens it on Inspector; `]` toggles; `Esc` closes. Empty Inspector reads "Select a gap or estimate line to see its details."
- Sidebar collapses to 64px (0.16s transition) via `[` or button. Top to bottom: organisation switcher, Search, navigation, footer (Keyboard shortcuts `?`, Collapse sidebar, user card with avatar opening Settings, role and theme toggle).
- Settings card (760px): Theme and Density radio cards plus the shortcut switch with a visible On/Off label. Also opened by the palette command "Open Settings".
- Assessments tab adds a run header, task counters, per-agent cards and Cancel run / Start new run over existing run data.
- Opportunity list: columns Opportunity (with customer), Status, Owner, Proposal date, Open items, Estimate; views All, Mine, Due in 14 days, Blocked. Header: breadcrumb, owner and collaborator chips, due-date countdown, Submit and "Resolve N blockers".
- Inbox: Mark all read clears the sidebar badge and keeps order; two-pane list and detail with unread dots and kind pills. New Opportunity is a card with import-from-file above fields. Knowledge and Admin sub-tabs use a segmented control.

## Cross-Story Dependencies

- 17.1 precedes all other 17.x stories and any new UI story in any epic; 17.2 follows 17.1.
- 17.3, 17.4 and 17.5 depend on 17.1 and 17.2.
- 17.2 builds on the Offline state from Story 2.3.
- 17.4 covers only list and header chrome; the Overview body is Story 8.9.
- 17.5 shows Admin "Invite user" only after Story 1.10.
