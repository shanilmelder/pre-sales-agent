---
name: Agentic AI Presales Platform
description: Dense, keyboard-first workbench for presales engineers, inspired by Linear. Built with shadcn/ui on Next.js and Tailwind; this file specifies only the brand-layer delta.
status: final
created: 2026-10-01
updated: 2026-10-01
colors:
  # Tokens not listed here (background, foreground, card, popover, muted, border, input, ring, destructive) inherit shadcn defaults (neutral base).
  primary: '#4F5BD5'
  primary-foreground: '#FFFFFF'
  primary-dark: '#7C86E8'
  primary-foreground-dark: '#0E1030'
  blocker: '#DC2626'
  blocker-dark: '#F87171'
  gap: '#B45309'
  gap-dark: '#FBBF24'
  resolved: '#15803D'
  resolved-dark: '#4ADE80'
  agent: '#4F5BD5'
  agent-dark: '#7C86E8'
  diff-tint: '#EEF0FC'
  diff-tint-dark: '#1E2140'
  blocker-tint: '#FEF2F2'
  blocker-tint-dark: '#2A1414'
  surface-sidebar: '#F7F7F8'
  surface-sidebar-dark: '#111113'
  surface-inspector: '#FBFBFC'
  surface-inspector-dark: '#16161A'
typography:
  # Inter for all roles. Sized one notch denser than shadcn defaults.
  body:
    fontFamily: 'Inter'
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.5'
  body-strong:
    fontFamily: 'Inter'
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.5'
  label:
    fontFamily: 'Inter'
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1.4'
  meta:
    fontFamily: 'Inter'
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1.4'
    letterSpacing: 0.01em
  title:
    fontFamily: 'Inter'
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: -0.01em
  section:
    fontFamily: 'Inter'
    fontSize: 14px
    fontWeight: '600'
    lineHeight: '1.4'
  numeric:
    fontFamily: 'Inter'
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.5'
    note: 'tabular-nums for every effort, cost, count and date column'
  mono:
    fontFamily: 'JetBrains Mono'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.5'
rounded:
  sm: 4px
  md: 6px
  lg: 8px
  full: 9999px
spacing:
  # Tailwind 4-based scale inherited. Named density tokens added.
  row-height: 32px
  row-height-compact: 28px
  sidebar-width: 220px
  inspector-width: 420px
  activity-rail-width: 300px
  page-gutter: 16px
components:
  button-primary:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    radius: '{rounded.md}'
    height: 28px
  list-row:
    height: '{spacing.row-height}'
    typography: '{typography.body}'
    radius: '{rounded.sm}'
  list-row-selected:
    background: 'shadcn accent'
    indicator: '2px left bar in {colors.primary}'
  status-pill:
    radius: '{rounded.full}'
    typography: '{typography.label}'
    height: 20px
  blocker-badge:
    foreground: '{colors.blocker}'
    icon: 'octagon-alert'
  gap-badge:
    foreground: '{colors.gap}'
    icon: 'circle-help'
  agent-running-dot:
    color: '{colors.agent}'
    motion: '1.5s opacity pulse; static when prefers-reduced-motion'
  evidence-chip:
    typography: '{typography.meta}'
    radius: '{rounded.sm}'
    border: '1px shadcn border'
  inspector-panel:
    background: '{colors.surface-inspector}'
    width: '{spacing.inspector-width}'
  sidebar:
    background: '{colors.surface-sidebar}'
    width: '{spacing.sidebar-width}'
---

## Brand & Style

The platform is a working tool for presales engineers who spend whole days inside it. Like Linear, it's quiet, dense and fast. Colour is almost all neutral, so the few colours that do appear carry meaning: something is blocking, something is unknown, an agent is working, something is resolved. The surface should feel like an engineering instrument, not a sales dashboard. There are no hero graphics, illustrations, gradients or celebratory moments.

The product inherits shadcn/ui defaults with a neutral base. This file specifies only the deltas: one primary colour, four semantic colours, Inter at a denser size, tighter corners, density tokens, and a handful of product-specific components.

## Colors

- **Primary Indigo (`{colors.primary}` / `{colors.primary-dark}`)** is used for primary buttons, the selected-row indicator, active navigation, links and keyboard focus accents. One primary action per view.
- **Blocker Red (`{colors.blocker}`)** marks only items that block submission or Baseline: open critical Findings, unresolved Gaps at submit time, and failed tasks. It is never used for decoration or general emphasis. Destructive buttons use shadcn's `destructive`, not this token.
- **Gap Amber (`{colors.gap}`)** marks open Gaps, Unknowns and unanswered Clarification Questions: things the platform doesn't know yet.
- **Agent Indigo (`{colors.agent}`)** marks agent-running state, shown as a pulsing dot next to the task or section. It shares the primary hue on purpose: the platform is working.
- **Resolved Green (`{colors.resolved}`)** marks answered Gaps, resolved Conflicts and approved Reviews. It is shown as an icon tint, never as a filled background.
- **Sidebar and inspector surfaces** are slightly tinted neutrals that separate the three panes without borders.
- **Everything else** inherits shadcn neutral tokens.

**Contrast targets.** All text and icon colours meet WCAG 2.1 AA on their surfaces: 4.5:1 for text and 3:1 for icons and non-text UI. Measured against `#FFFFFF` and `{colors.surface-sidebar}` in light mode: primary 5.5/5.2, blocker 4.8/4.5, gap 5.0/4.7, resolved 5.0/4.7. In dark mode, every semantic colour is above 5.7:1 on `#111113`. Any new colour token must state its ratio here.

Colour never carries meaning on its own. Every semantic colour is paired with an icon and a text label (WCAG 1.4.1).

## Typography

Inter is used for every role. Body text is **13px** (`{typography.body}`), one notch denser than shadcn, to match Linear's information density. The roles are:
- `{typography.label}` (12px/500) for column headers, pills and form labels;
- `{typography.meta}` (11px) for timestamps, versions and evidence chips;
- `{typography.title}` (18px/600) for the Opportunity title;
- `{typography.section}` (14px/600) for section headers within a tab.

All numbers (effort, cost, counts, versions, dates) use tabular figures (`{typography.numeric}`), so columns align. `{typography.mono}` is used only for IDs, prompt or model versions in admin screens, and source excerpts shown verbatim.

## Layout & Spacing

The layout has three panes: **sidebar** (`{spacing.sidebar-width}`), **main** (fluid), and an optional **right pane**. The right pane is either the inspector (`{spacing.inspector-width}`) or the activity rail (`{spacing.activity-rail-width}`), never both at once. List rows are `{spacing.row-height}` high (28px in compact density). Page gutter is `{spacing.page-gutter}`. Lists and tables fill the main pane's width; there is no max-width reading column, because this is a table-heavy tool.

The minimum supported width is 1280px. The inspector overlays the main pane below 1440px and docks beside it at 1440px and above.

## Elevation & Depth

The panes are flat and separated by tonal surfaces. Shadows appear only on floating layers: the command palette, popovers, dropdowns and dialogs. These inherit shadcn shadows.

## Shapes

Corners are tighter than shadcn's: `{rounded.sm}` (4px) for rows, inputs and chips, `{rounded.md}` (6px) for buttons and cards, and `{rounded.lg}` (8px) for dialogs and the command palette. `{rounded.full}` is used only for status pills and avatars.

## Components

These shadcn components are used unchanged: Button (non-primary variants), Input, Textarea, Select, Command, Dialog, Sheet, Popover, DropdownMenu, Tabs, Tooltip, Toast (sonner), Table, Badge, Avatar, Skeleton, Separator, ResizablePanel.

Brand and product components:
- **Button (primary):** `{colors.primary}` fill, 28px high, `{rounded.md}` corners.
- **List row:** 32px high, hover background shadcn `accent`. When selected, a 2px left bar in `{colors.primary}`. Row actions appear on hover or focus at the right edge.
- **Status pill:** 20px high, `{rounded.full}`, a neutral outline with a coloured leading icon. Pill vocabulary follows EXPERIENCE.md statuses.
- **Blocker / gap badge:** an icon with a count, in `{colors.blocker}` or `{colors.gap}`. Used in tab labels and the Overview blockers list.
- **Agent running dot:** 6px dot in `{colors.agent}`, pulsing. Static when the user prefers reduced motion.
- **Evidence chip:** an inline, bordered `{typography.meta}` chip with a kind icon (requirement, source, knowledge, research, actual) and a short label. Clicking it opens the cited passage in the inspector.
- **Inspector panel:** right pane on `{colors.surface-inspector}` with a header (title, status pill, close), a scrollable body, and a footer for primary actions.
- **Estimate grid:** a dense table built on shadcn Table. It has tabular figures, sticky header and totals rows, right-aligned numbers, and a Contingency column visually separated by a left rule.
- **Gap card:** a list row with an impact bar (1–3 segments, neutral), a trigger label in `{typography.meta}`, and a Clarification Question status pill. When expanded in the inspector, the question draft sits in a bordered textarea, with the Convert form below a separator.
- **Conflict view:** two or more equal-width columns, one per position, each a card with the agent name in `{typography.section}`, the position value in `{typography.numeric}`, and Evidence chips. A Negotiation proposal (R3) sits above in a card with a 2px `{colors.primary}` top border.
- **Agent run panel:** a list of `{spacing.row-height-compact}` rows, each with the agent name, a status pill, elapsed time in `{typography.numeric}`, and the running dot. Failed rows add inline Retry and Skip ghost buttons.
- **Review panel:** the inspector variant. Target summary at the top, Evidence chips, then a footer action bar: Approve (primary), Reject (destructive outline), and the other actions in a "More" dropdown.
- **Submission Blockers list:** a card on Overview. The header shows the gate name and count; each row shows a blocker icon, type label, subject title and a jump link. When empty, the header reads "0 blockers — ready to submit" with a `{colors.resolved}` check icon, and the Submit button becomes primary.
- **Blocker row:** a `{colors.blocker-tint}` background with a 2px `{colors.blocker}` left bar, for rows that currently block a gate (for example an unaccepted Assumption).
- **Baseline marker:** a small neutral pill reading "Baseline" with an anchor icon, shown next to the version number wherever Estimate Versions are listed.
- **Diff view:** added or changed values shown with a `{colors.diff-tint}` background, never the semantic green or red, plus `+`/`−` markers in text for colour-blind users. Used for Estimate Version comparison and pending Requirement changes.

## Do's and Don'ts

| Do | Don't |
| --- | --- |
| Keep surfaces neutral; reserve colour for blocker, gap, agent and resolved states | Colour cards, headers or charts decoratively |
| Pair every semantic colour with an icon and a label | Signal state by colour alone |
| Use tabular figures in every numeric column | Use proportional numbers in tables |
| Keep 13px body text and 32px rows | Inflate spacing to look "friendly" |
| Use one primary button per view | Use several competing primary actions |
| Animate only agent-running and transitions under 150 ms | Use celebratory animations, confetti or skeleton shimmer longer than needed |
