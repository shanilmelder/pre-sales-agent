# Epic 17 Context: Redesign refit (visual identity and shell)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Apply the 2026-10-21 redesign (roomy, card-based, tint-filled pills, Inter 14px) to the built web app and to the shell later stories build on. It replaces the earlier dense 13px identity wholesale. No FR; built-screen behaviour does not change and existing tests pass with updated selectors. Story 17.1 must precede any new UI story in any epic. Epic 1 stays closed (Story 1.5 is superseded in visual identity, not reopened).

## Stories

- Story 17.1: Token layer and primitives
- Story 17.2: App shell, Settings and accessibility behaviours
- Story 17.3: Refit built tabs to the redesign
- Story 17.4: Opportunity list and Overview chrome

## Requirements & Constraints

- WCAG 2.1 AA with axe in CI; single-key shortcuts can be turned off (WCAG 2.1.4); every screen has a skip link as first tab stop; live changes announced politely (NFR-7).
- Desktop Chrome/Edge; minimum width 1280px; read-only notice below 1024px; tiers at >=1440 (right pane docks), 1280-1439 (pane overlays), 1024-1279 (sidebar collapses to icons), <1024 (NFR-8).
- Colour never carries meaning alone: every status/countdown has an icon or text.
- Voice: glossary terms, counts, specific failure reasons, agents named by role, no emoji or celebration copy.
- Product name on every page title: "Pre Sales Agent Framework".
- Running state is a static loader icon; remove the six `animate-pulse` dots and update tests that asserted them. No keyframe animations; transitions 0.12s (sidebar width 0.16s), all off under `prefers-reduced-motion`.
- `contrast.test.ts` must assert every pair in the table below (including the seven fixes) and fail CI otherwise. Any new colour token must state its ratio in DESIGN.md.

## Technical Decisions

- UI preferences (theme System/Light/Dark, density Comfortable/Compact, single-key shortcut switch) live in the `psa_prefs` cookie read by the root layout, so SSR paints the right theme. No server table, no localStorage.
- Single-key shortcuts default Off with a first-run hint explaining how to enable (built code defaults On; Story 17.2 changes it).
- Controls are outlined with `border-strong`; `border` is decoration only (card/row dividers). JetBrains Mono is removed; IDs, versions and excerpts use Inter. Tabular figures on the whole body.
- The shadcn primitives restyled: Button, Status pill, Card, Input, Select, Tabs (underline), Switch, Dialog, Table, Skeleton, Avatar, Tooltip.
- Where the spines are silent, `ux-designs/ux-pre-sales-agent-2026-10-01/imports/presales-agent-design-spec-standalone-v2.html` is the visual reference; the spines win on conflict. Its `border2` is replaced by `border-strong`. Older `mockups/` are superseded. Do not copy personal names or emails from its demo data.

### Tokens (must match DESIGN.md front matter exactly; light / dark)

- canvas #ECEDF2 / #0E1015; background #F7F7FA / #14161D; surface #FFFFFF / #1B1E27; surface-alt #F1F2F7 / #232734
- border #E3E5EE / #2B3040; border-strong #80869D / #737A94
- text #171A26 / #E9EBF3; text-secondary #555B72 / #A3AAC0
- primary #4F5BD5 both (foreground #FFFFFF both); primary-tint #ECEEFC / #262B52; primary-text, link, agent #3B45B8 / #B3BAFF; ring #4F5BD5 / #B3BAFF; agent-tint #ECEEFC / #262B52
- blocker #B42F29 / #FF9C94 (tint #FDECEA / #3B2026); gap #8F5200 / #F3BA5C (tint #FDF1D6 / #382D17); resolved #17753F / #78D6A0 (tint #E2F5E9 / #162F20; foreground #FFFFFF / #14161D); neutral #555B72 / #A3AAC0 (tint #EEF0F6 / #262A38)
- role-pm #1F8A7E / #5FCBBE; role-qa #6E7490 / #8A91AB; scrim rgba(10,12,20,.55)
- Graph (always dark): canvas #12192D, product #9AA3FF, integration-type #5FD0C2, knowledge-source #7CC8F5, checklist #F3BA5C, ready #6FD39A, missing #FF8A80, edge #6D7AA8, edge-selected #9AA3FF, edge-gap #F3BA5C, chip-background #1B2442, chip-border #4F5BD5, chip-text #E4E8F5, chip-off-text #9AA6C8
- Type (Inter, system-ui fallback, weights 400/500/600): title 24/32 600 -0.01em; section 16/24 600; body 14/21; body-strong 14/500; control 13/500 lh 1.4; meta 12/16; label 12/500; eyebrow 12/600 0.04em uppercase (inspector headings only); kpi 28/600 lh 1.2 (24 compact); numeric 14/500 tabular. No text below 12px in main UI (graph badge glyphs 10px and labels 11px excepted).
- Radii: sm 6, md 8, lg 10, xl 12, full 9999. Spacing 4/8/12/16/24; page-padding 20; card-header 18px 20px; page-header 28px 32px 20px; row-padding 12 (compact 6), rows ~56-72px; sidebar 220 (collapsed 64); right pane 420; graph detail 372; graph height 660; dialog 520; settings 760.
- Elevation: card 1px border + `0 1px 2px rgba(23,26,38,.06)` (dark `0 1px 2px rgba(0,0,0,.3)`); dialogs/palette `0 16px 40px rgba(0,0,0,.3)` over scrim; hover `filter: brightness(.97)`; selected-row inset 3px left edge (blocker for High open Gaps/Conflicts, gap for Low-confidence unconfirmed Requirements). Focus ring 2px outline, 2px offset.

### Component specs

- Button primary: primary fill, white, radius 8, padding 8x16, body-strong, ~38px tall. Secondary: surface, 1px border-strong, radius 8, 6x12, control, ~32px. Disabled opacity .4, `aria-disabled`, `cursor: not-allowed`, reason in adjacent text.
- Input: surface-alt fill, 1px border-strong, radius 8. Card: surface, 1px border, radius 12, soft shadow.
- Status pill: full radius, label type, 12px icon plus label, semantic tint fill with semantic text, no outline, padding 2px 10px 2px 8px. Count badge: radius 10, padding 0 7px; sidebar badge white on primary; tab badge surface-alt/text-secondary, or blocker tint on Gaps and Conflicts while blockers exist.
- Tabs: underline, 14px, 2px primary bottom border on active, active label 600 primary-text, inline count badge. Segmented control: surface-alt track, 1px border-strong, active segment surface.
- Evidence chip: primary-text on surface, 1px border-strong, radius 6, padding 2px 8px, 11px quote icon. Agent content on agent-tint with sparkles and role label; agent avatars 6px-radius squares, human avatars circles.
- Switch: 44x26, full radius, off track border-strong, on track primary, 20px white knob, adjacent On/Off text, `role="switch"`.
- Dialog: surface, 1px border, radius 12, padding 24, 520 wide, title 20/600. Skip link: primary fill, white text, hidden above viewport, `top: 8px` on focus. Skeleton: neutral rows, no shimmer.
- Inline alert (412): blocker-tint, radius 10, bold blocker lead "Not saved: this line changed (412)", text detail, Reload and View diff buttons, `role="alert"`, above the field. Offline banner: neutral-tint, 1px border-strong bottom rule, 10px 32px padding, wifi-off icon, Retry button, `role="alert"`. Empty tab card: 64px 24px padding, centred, 16/600 title, one sentence max 440px, one primary jump button, no illustration.
- Settings card: 760 wide, three 24px sections (Theme, Density, Single-key shortcuts), surface-alt footer note; option cards radius 10, selected = primary border on primary-tint.

### Contrast table (computed, WCAG 2.1 AA; light unless noted)

- Text on surface/background 17.32/16.20; text-secondary on surface/background/surface-alt 6.72/6.28/6.01; dark text on surface 13.98; dark text-secondary on surface/surface-alt 7.19/6.43
- White on primary 5.54 (both themes); primary-text on surface/background/primary-tint 7.69/7.20/6.67; dark #B3BAFF on surface/primary-tint 9.02/7.35
- Semantic on tint: blocker 5.43 (dark 7.35); gap 5.55 (dark 7.71); resolved 5.06 (dark 8.16); neutral 5.90 (dark 6.17)
- Fix 1 link dark #B3BAFF on surface/background/surface-alt 9.02/9.80/8.07; link light 7.69/7.20
- Fix 2 border-strong light on surface/surface-alt/background 3.61/3.23/3.38; dark 3.92/3.50/4.25
- Fix 3 role-qa light on surface/surface-alt 4.60/4.12; QA dark 5.33/4.76; PM light 4.20/3.76; PM dark on surface 8.54
- Fix 4 ring dark on surface/background/surface-alt 9.02/9.80/8.07; ring light on surface/surface-alt/background/primary-tint 5.54/4.96/5.18/4.80
- v2 gap text on surface/background/surface-alt 6.22/5.82/5.57; resolved text 5.75/n.a./5.14; dark gap on surface/surface-alt 9.50/8.50; dark resolved 9.45
- v2 ink on neutral/blocker/resolved/primary tints light 15.20/15.15/15.24/15.02; dark 12.00/12.42/12.07/11.38
- Fix 5 lifecycle check: #14161D on #78D6A0 10.26; white on #17753F 5.75
- Fix 6 switch off track/pending ring on surface: light 3.61, dark 3.92; white knob on border-strong 3.61/4.25; switch on track on surface-dark 3.00, white knob on it 5.54
- Fix 7 selected Challenge card border dark #B3BAFF on #262B52 7.35
- border-strong on neutral-tint (offline rule) 3.17/3.36; white on primary (skip link, Save, Rerun) 5.54
- Graph colours on #12192D: 7.53, 9.39, 9.51, 9.97, 9.53, 7.65; edge 4.16; chip border 3.15; chip off text #9AA6C8 on #1B2442 6.29
- Accepted: dark primary fill is 3.00 on surface-dark and 2.69 on surface-alt-dark (labelled button); switch on track exactly 3.00 with text label; disabled controls exempt.

## UX & Interaction Patterns

- Shell: sidebar (Inbox, My Opportunities, All Opportunities, Knowledge, Reports for Head of Delivery and platform admin only, Admin) collapses to 64px; header has organisation switcher, Search button and avatar button; shortcuts footer in the sidebar. One 420px right pane with Inspector and Activity tabs replaces the 300px activity rail; `]` cycles closed, open, closed.
- Settings opens from the avatar button or palette command "Open Settings". Notifications and roles are managed by an admin, not in Settings.
- Offline strip with Retry after 60 s down (state from Story 2.3). A polite live region announces the screen name.
- Opportunity workspace: 9 tabs (Overview, Sources, Requirements, Gaps, Assessments, Conflicts, Estimate, Trace, Actuals) with count badges.
- List rows: padded per density, hover/focus actions, selected indicator, `x` multi-select with visible checkboxes, no infinite scroll.
- Opportunity list columns: Opportunity (with customer), Status, Owner, Proposal date, Open items, Estimate; views All, Mine, Due in 14 days, Blocked. Header: breadcrumb, owner/collaborator chips, due-date countdown, Submit and "Resolve N blockers" buttons.
- Built tabs show the empty-tab card using EXPERIENCE State Patterns copy; stale save (412) uses the inline alert.
- Agent run panel rows: status pill, elapsed time, static loader for Running, model chip, Retry/Skip on failure, Resolve when waiting.

## Cross-Story Dependencies

- 17.1 precedes all new UI work in any epic. 17.2 depends on 17.1; 17.3 and 17.4 depend on 17.1 and 17.2.
- 17.2's Offline strip builds on the Story 2.3 offline state; 17.4 provides the Opportunity header and list chrome while the Overview body is Story 8.9.
- Story 11.1 has an unresolved pending decision about a notifications control in Settings.
