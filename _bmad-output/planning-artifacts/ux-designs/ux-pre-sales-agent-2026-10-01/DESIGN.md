---
name: Pre Sales Agent Framework
description: Roomy, card-based workspace for presales engineers and reviewers, with tint-filled status pills and visible agent reasoning. Built with shadcn/ui on Next.js and Tailwind; this file specifies the brand-layer delta.
status: final
created: 2026-10-01
updated: 2026-10-21
colors:
  # Light values are the base keys; "-dark" keys are the dark theme. Tokens not listed (popover, card-foreground, muted, input, destructive) inherit shadcn defaults mapped onto the surfaces below.
  canvas: '#ECEDF2'
  canvas-dark: '#0E1015'
  background: '#F7F7FA'
  background-dark: '#14161D'
  surface: '#FFFFFF'
  surface-dark: '#1B1E27'
  surface-alt: '#F1F2F7'
  surface-alt-dark: '#232734'
  border: '#E3E5EE'
  border-dark: '#2B3040'
  border-strong: '#CDD1E0'
  border-strong-dark: '#3A4054'
  text: '#171A26'
  text-dark: '#E9EBF3'
  text-secondary: '#555B72'
  text-secondary-dark: '#A3AAC0'
  primary: '#4F5BD5'
  primary-dark: '#4F5BD5'
  primary-foreground: '#FFFFFF'
  primary-foreground-dark: '#FFFFFF'
  primary-tint: '#ECEEFC'
  primary-tint-dark: '#262B52'
  primary-text: '#3B45B8'
  primary-text-dark: '#B3BAFF'
  link: '#3B45B8'
  link-dark: '#B3BAFF'
  ring: '#4F5BD5'
  ring-dark: '#B3BAFF'
  agent: '#3B45B8'
  agent-dark: '#B3BAFF'
  agent-tint: '#ECEEFC'
  agent-tint-dark: '#262B52'
  blocker: '#B42F29'
  blocker-dark: '#FF9C94'
  blocker-tint: '#FDECEA'
  blocker-tint-dark: '#3B2026'
  gap: '#8F5200'
  gap-dark: '#F3BA5C'
  gap-tint: '#FDF1D6'
  gap-tint-dark: '#382D17'
  resolved: '#17753F'
  resolved-dark: '#78D6A0'
  resolved-tint: '#E2F5E9'
  resolved-tint-dark: '#162F20'
  resolved-foreground: '#FFFFFF'
  resolved-foreground-dark: '#14161D'
  neutral: '#555B72'
  neutral-dark: '#A3AAC0'
  neutral-tint: '#EEF0F6'
  neutral-tint-dark: '#262A38'
  role-pm: '#1F8A7E'
  role-pm-dark: '#5FCBBE'
  role-qa: '#6E7490'
  role-qa-dark: '#8A91AB'
  scrim: 'rgba(10,12,20,.55)'
  graph-canvas: '#12192D'
  graph-product: '#9AA3FF'
  graph-integration-type: '#5FD0C2'
  graph-knowledge-source: '#7CC8F5'
  graph-checklist: '#F3BA5C'
  graph-ready: '#6FD39A'
  graph-missing: '#FF8A80'
  graph-edge: '#6D7AA8'
  graph-edge-selected: '#9AA3FF'
  graph-edge-gap: '#F3BA5C'
  graph-chip-background: '#1B2442'
  graph-chip-border: '#4F5BD5'
  graph-chip-text: '#E4E8F5'
  graph-chip-off-text: '#9AA6C8'
typography:
  # Inter for every role; no mono face. Tabular figures on the whole body.
  title:
    fontFamily: 'Inter'
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '32px'
    letterSpacing: -0.01em
  section:
    fontFamily: 'Inter'
    fontSize: 16px
    fontWeight: '600'
    lineHeight: '24px'
  body:
    fontFamily: 'Inter'
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '21px'
  body-strong:
    fontFamily: 'Inter'
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '21px'
  control:
    fontFamily: 'Inter'
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.4'
  meta:
    fontFamily: 'Inter'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '16px'
  label:
    fontFamily: 'Inter'
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '16px'
  eyebrow:
    fontFamily: 'Inter'
    fontSize: 12px
    fontWeight: '600'
    lineHeight: '16px'
    letterSpacing: 0.04em
    note: 'uppercase; inspector section headings only'
  kpi:
    fontFamily: 'Inter'
    fontSize: 28px
    fontWeight: '600'
    lineHeight: '1.2'
    note: '24px in compact tiles'
  numeric:
    fontFamily: 'Inter'
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '21px'
    note: 'tabular-nums for every effort, count, version and date'
rounded:
  sm: 6px
  md: 8px
  lg: 10px
  xl: 12px
  full: 9999px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 24px
  page-padding: 20px
  card-header: 18px 20px
  page-header: 28px 32px 20px
  row-padding: 12px
  row-padding-compact: 6px
  sidebar-width: 220px
  sidebar-width-collapsed: 64px
  right-pane-width: 420px
  graph-detail-width: 372px
  graph-height: 660px
  dialog-width: 520px
  settings-width: 760px
components:
  button-primary:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    radius: '{rounded.md}'
    padding: '8px 16px'
    typography: '{typography.body-strong}'
  button-secondary:
    background: '{colors.surface}'
    foreground: '{colors.text}'
    border: '1px {colors.border-strong}'
    radius: '{rounded.md}'
    padding: '6px 12px'
    typography: '{typography.control}'
  input:
    background: '{colors.surface-alt}'
    border: '1px {colors.border-strong}'
    radius: '{rounded.md}'
  card:
    background: '{colors.surface}'
    border: '1px {colors.border}'
    radius: '{rounded.xl}'
    shadow: '0 1px 2px rgba(23,26,38,.06)'
  list-row:
    padding: '{spacing.row-padding} 16px'
    typography: '{typography.body}'
  list-row-selected:
    background: '{colors.primary-tint}'
  status-pill:
    radius: '{rounded.full}'
    typography: '{typography.label}'
    padding: '2px 10px 2px 8px'
  count-badge:
    radius: '{rounded.lg}'
    typography: '{typography.label}'
    padding: '0 7px'
  evidence-chip:
    foreground: '{colors.primary-text}'
    background: '{colors.surface}'
    border: '1px {colors.border-strong}'
    radius: '{rounded.sm}'
    typography: '{typography.label}'
  agent-content:
    background: '{colors.agent-tint}'
    label: '{typography.label}'
  sidebar:
    background: '{colors.surface}'
    width: '{spacing.sidebar-width}'
  right-pane:
    background: '{colors.surface}'
    width: '{spacing.right-pane-width}'
  kpi-tile:
    number: '{typography.kpi}'
    label: '{typography.label}'
  switch:
    track-off: '{colors.border-strong}'
    track-on: '{colors.primary}'
    knob: '{colors.primary-foreground}'
    width: 44px
    height: 26px
    radius: '{rounded.full}'
  dialog:
    background: '{colors.surface}'
    border: '1px {colors.border}'
    radius: '{rounded.xl}'
    padding: '24px'
    width: '{spacing.dialog-width}'
    scrim: '{colors.scrim}'
  version-state-pill:
    radius: '{rounded.full}'
    padding: '0 7px'
    typography: '{typography.label}'
  lifecycle-step:
    node-done: '{colors.resolved}'
    node-done-foreground: '{colors.resolved-foreground}'
    node-current: '{colors.primary-tint}'
    ring-current: '{colors.primary}'
    ring-pending: '{colors.border-strong}'
    connector-pending: '{colors.border-strong}'
  inline-alert:
    background: '{colors.blocker-tint}'
    foreground: '{colors.blocker}'
    radius: '{rounded.lg}'
    body: '{colors.text}'
  role-mix-bar:
    engineer: '{colors.primary}'
    pm: '{colors.role-pm}'
    qa: '{colors.role-qa}'
---

## Brand & Style

Pre Sales Agent Framework is a working tool for presales engineers, reviewers and delivery leads. It reads as a calm, roomy dashboard-workspace: white cards on a pale bluish canvas, comfortable rows, tint-filled status pills and KPI tiles that answer "where do I stand" before any list is opened. It replaces the earlier dense 13px Linear-style identity wholesale (user decision, 2026-10-21).

Colour carries meaning. Red marks a blocker, amber a gap or unknown, indigo an agent, green a resolved item and grey everything neutral. Agent reasoning is shown inline, on an indigo tint with a role label, so a reader can judge output on its Evidence. There are no hero graphics, illustrations, gradients or celebratory moments.

The product inherits shadcn/ui defaults. This file specifies the deltas: surfaces, one primary colour, semantic tints, Inter at 14px, rounder corners, roomy density tokens and product components. The redesign import ([`imports/presales-agent-design-spec-standalone-v2.html`](imports/presales-agent-design-spec-standalone-v2.html), which adds Settings, Trace detail, Findings, Actuals, the Estimate lifecycle, the Challenge dialog, empty states and Offline; the earlier file is kept as `-v1`) is the visual reference. The spines win on conflict. The three mockups in `mockups/` predate the redesign and are superseded visually. They are kept for layout history only.

## Colors

Every colour has a light and a dark value (`-dark` suffix). Tokens are semantic first; the redesign's raw names map as red to `blocker`, amber to `gap`, green to `resolved`, and indigo text to `primary-text` / `agent`.

- **Canvas and surfaces.** `{colors.canvas}` sits behind the app frame. `{colors.background}` is the main pane. `{colors.surface}` is cards, sidebar and right pane. `{colors.surface-alt}` is table headers, segmented tracks and input fills. Panes are separated by 1px `{colors.border}` lines, not by tonal steps alone.
- **Text.** `{colors.text}` for content, `{colors.text-secondary}` for meta and helper text.
- **Primary Indigo (`{colors.primary}`)** is the fill for the primary button and count badges, and is the same in both themes with white text. Use it for one primary action per view. `{colors.primary-tint}` fills selected rows, active navigation and agent content. `{colors.primary-text}` is the indigo for text and icons.
- **Link (`{colors.link}`)** equals `{colors.primary-text}` in each theme. Links never use the primary fill colour as text, because it fails on dark surfaces.
- **Control border (`{colors.border-strong}`)** outlines inputs, textareas, secondary buttons, segmented tracks, evidence chips, unticked checkboxes, the switch's off track, and pending Version lifecycle rings and connectors. It takes the mockup's `border2` value (`#CDD1E0` light, `#3A4054` dark). These values were accepted below the 3:1 non-text minimum, so input boundaries are lighter than WCAG asks. `{colors.border}` is for decorative card and row dividers only.
- **Focus ring (`{colors.ring}`)** is a 2px outline with a 2px offset. In dark it is `{colors.ring-dark}`, a light indigo.
- **Blocker Red (`{colors.blocker}` on `{colors.blocker-tint}`)** marks items that block submission or Baseline (open Conflicts, High-impact open Gaps, uncovered Requirements, unaccepted Assumptions, critical Findings without an override), plus failures (Parse failed, Failed task, Embedding failed), mandatory Checklist items and variance above +10%.
- **Gap Amber (`{colors.gap}` on `{colors.gap-tint}`)** marks what the platform does not know yet or needs a human for: Medium Gaps, Low confidence, Waiting for you, Stale, Partial, In review, Needs review, and increases in a diff.
- **Agent Indigo (`{colors.agent}` on `{colors.agent-tint}`)** marks agent output and agent activity: Running, Parsing, Embedding, and agent content blocks. Running is shown with a static loader icon, not a pulse.
- **Resolved Green (`{colors.resolved}` on `{colors.resolved-tint}`)** marks Parsed, Completed, Confirmed, Approved, Accepted, Ready, Baselined and Pass. Green may fill pills, step nodes and matrix cells. A check mark on a solid green fill (the Version lifecycle node) uses `{colors.resolved-foreground}`, white in light and `#14161D` in dark, because white on the dark-theme green fails.
- **Neutral (`{colors.neutral}` on `{colors.neutral-tint}`)** marks Draft, Queued, Dismissed, Invited, Disabled, Pending, Medium confidence and Superseded.
- **Scrim (`{colors.scrim}`)** dims the app behind Dialogs and the command palette.
- **Role mix (`{colors.primary}` Engineer, `{colors.role-pm}` PM, `{colors.role-qa}` QA)** colours the Estimate role-mix bar. Segments are separated by a 1px `{colors.surface}` gap and always repeated as text ("E 70.4 · PM 11.6 · QA 0").
- **Knowledge graph (`{colors.graph-canvas}`)** is always dark, even in the light theme. Node colours: `{colors.graph-product}`, `{colors.graph-integration-type}`, `{colors.graph-knowledge-source}`, `{colors.graph-checklist}`. Status badges use `{colors.graph-ready}`, `{colors.graph-checklist}`, `{colors.graph-missing}` and `{colors.graph-product}` with a glyph and a text label. Edges are `{colors.graph-edge}`, selected `{colors.graph-edge-selected}`, missing coverage `{colors.graph-edge-gap}` dashed.

Colour never carries meaning alone. Every semantic colour is paired with an icon and a label (WCAG 1.4.1).

**Contrast targets and computed ratios** (WCAG 2.1 AA: 4.5:1 text, 3:1 UI components and graphical objects; WCAG relative-luminance formula). Any new colour token must state its ratio here.

| Pair | Ratio |
| --- | --- |
| Text `#171A26` on surface / background (light) | 17.32 / 16.20 |
| Text-secondary `#555B72` on surface / background / surface-alt (light) | 6.72 / 6.28 / 6.01 |
| Text `#E9EBF3` on surface (dark); text-secondary `#A3AAC0` on surface / surface-alt (dark) | 13.98; 7.19 / 6.43 |
| White on primary `#4F5BD5` (both themes) | 5.54 |
| Primary-text `#3B45B8` on surface / background / primary-tint (light) | 7.69 / 7.20 / 6.67 |
| Primary-text `#B3BAFF` on surface / primary-tint (dark) | 9.02 / 7.35 |
| Blocker on tint: `#B42F29` on `#FDECEA` / `#FF9C94` on `#3B2026` | 5.43 / 7.35 |
| Gap on tint: `#8F5200` on `#FDF1D6` / `#F3BA5C` on `#382D17` | 5.55 / 7.71 |
| Resolved on tint: `#17753F` on `#E2F5E9` / `#78D6A0` on `#162F20` | 5.06 / 8.16 |
| Neutral on tint: `#555B72` on `#EEF0F6` / `#A3AAC0` on `#262A38` | 5.90 / 6.17 |
| **Fix 1, link on dark:** `{colors.link-dark}` `#B3BAFF` on surface / background / surface-alt (was `#4F5BD5` at 3.00 on surface) | 9.02 / 9.80 / 8.07 |
| Link `#3B45B8` on surface / background (light) | 7.69 / 7.20 |
| **Fix 2, control border (withdrawn):** `{colors.border-strong}` is back to the mockup's `#CDD1E0` light and `#3A4054` dark. These were accepted below 3:1 in the theme and shell redesign. The `#80869D` and `#737A94` values and their ratios no longer apply. | below 3:1 (accepted) |
| **Fix 3, QA bar light:** `{colors.role-qa}` `#6E7490` on surface / surface-alt (was `#9AA0B4` at 2.61 on white) | 4.60 / 4.12 |
| QA bar dark `#8A91AB` on surface / surface-alt; PM bar `#1F8A7E` on surface / surface-alt (light); PM `#5FCBBE` on surface (dark) | 5.33 / 4.76; 4.20 / 3.76; 8.54 |
| **Fix 4, focus ring dark:** `{colors.ring-dark}` `#B3BAFF` on surface / background / surface-alt (was `#4F5BD5` at 3.00 on surface) | 9.02 / 9.80 / 8.07 |
| Focus ring light `#4F5BD5` on surface / surface-alt / background / primary-tint | 5.54 / 4.96 / 5.18 / 4.80 |
| **v2 Gap and Resolved text on surface / background / surface-alt (light):** Gap `#8F5200` (High Finding label, increased variance); Resolved `#17753F` (reduced variance) | Gap 6.22 / 5.82 / 5.57; Resolved 5.75 / n.a. / 5.14 |
| v2 Gap `#F3BA5C` on surface-dark / surface-alt-dark; Resolved `#78D6A0` on surface-dark | 9.50 / 8.50; 9.45 |
| **v2 ink on tints (Trace and 412 body copy, offline banner, selected Trace row):** `#171A26` on neutral / blocker / resolved / primary tint (light) | 15.20 / 15.15 / 15.24 / 15.02 |
| Ink `#E9EBF3` on neutral / blocker / resolved / primary tint (dark) | 12.00 / 12.42 / 12.07 / 11.38 |
| **Fix 5, lifecycle check on dark green:** `{colors.resolved-foreground-dark}` `#14161D` on `#78D6A0` (was white at 1.76); light white on `#17753F` | 10.26; 5.75 |
| **Fix 6, switch off track and pending ring or connector (withdrawn):** these follow `{colors.border-strong}`, so with the mockup's values they, and the white knob on the off track, sit below 3:1. This was accepted in the theme and shell redesign; the switch keeps its "On"/"Off" label. | below 3:1 (accepted) |
| Switch on track `#4F5BD5` on surface-dark; white knob on it | 3.00; 5.54 |
| **Fix 7, selected Challenge card border, dark:** `{colors.ring-dark}` `#B3BAFF` on primary-tint-dark `#262B52` (was `#4F5BD5` at 2.45) | 7.35 |
| White on primary (skip link, Save and Rerun buttons) | 5.54 |
| Graph node and badge colours on `#12192D` (`#9AA3FF`, `#5FD0C2`, `#7CC8F5`, `#F3BA5C`, `#6FD39A`, `#FF8A80`) | 7.53, 9.39, 9.51, 9.97, 9.53, 7.65 |
| Graph edge `#6D7AA8` on `#12192D`; chip border `#4F5BD5` on `#12192D` | 4.16; 3.15 |
| Graph chip off-state text `{colors.graph-chip-off-text}` `#9AA6C8` on `#1B2442` (was `#7F8BB0` at 4.52) | 6.29 |

The role-mix segments sit next to each other, so distinguishing PM from QA by colour alone is not relied on: the 1px gap and the text legend carry it. The dark-theme primary fill is 3.00:1 on `{colors.surface-dark}` and 2.69:1 on `{colors.surface-alt-dark}`. It is a labelled button (white text, 5.54:1), so its boundary is not the only cue. The switch's on track is exactly 3.00:1 on dark surfaces and always carries an "On" or "Off" text label. Disabled controls are exempt from contrast rules.

## Typography

Inter for every role, with `system-ui` fallback, weights 400, 500 and 600. Tabular figures are applied to the whole body so every number aligns. There is no mono face: IDs (R1, S2, L1, SEC-01), versions and source excerpts use Inter.

- `{typography.title}` (24/32, 600) is the page and Opportunity title.
- `{typography.section}` (16/24, 600) is card and section headings.
- `{typography.body}` (14/21) is the base. `{typography.body-strong}` (14/500) is primary buttons and emphasised cells.
- `{typography.control}` (13/500) is secondary buttons and dense controls.
- `{typography.meta}` (12/16) is timestamps, helper text and table notes. `{typography.label}` (12/500) is pills, chips, column headers and form labels.
- `{typography.eyebrow}` is uppercase 12px with 0.04em tracking, used for inspector section headings such as "Why it matters".
- `{typography.kpi}` (28/600, or 24 in compact tiles) is KPI numbers. `{typography.numeric}` is numeric columns.

Text below 12px is not used in the main UI. The Knowledge graph's 10px badge glyphs and 11px status labels are the exception and each is paired with a larger text label in the detail drawer.

## Layout & Spacing

The layout has a **sidebar** (`{spacing.sidebar-width}`, collapsing to `{spacing.sidebar-width-collapsed}`), a fluid **main** pane on `{colors.background}`, and an optional **right pane** (`{spacing.right-pane-width}`) that holds the Inspector or Activity, never both. The spacing scale is `{spacing.1}` 4, `{spacing.2}` 8, `{spacing.3}` 12, `{spacing.4}` 16, `{spacing.5}` 24.

Page and section padding is `{spacing.page-padding}`. Card headers use `{spacing.card-header}`. Non-Opportunity page headers use `{spacing.page-header}`. List rows use `{spacing.row-padding}` vertically in comfortable density and `{spacing.row-padding-compact}` in compact, giving rows of roughly 56 to 72px comfortable. Table header rows are `8px 16px`. Primary buttons are about 38px tall; secondary controls about 32px.

Viewport rules: the minimum supported width is **1280px**. At 1440px and above the right pane docks beside the main pane. From 1280 to 1439px it overlays the main pane. From 1024 to 1279px the sidebar collapses to icons (best effort). Below 1024px a read-only notice replaces editing (see EXPERIENCE.md, Responsive & Platform). The redesign was drawn on a fixed 1440 x 900 frame; that frame is the reference size, not the only size.

## Elevation & Depth

Cards are a 1px `{colors.border}` outline plus a soft `{components.card.shadow}` (dark: `0 1px 2px rgba(0,0,0,.3)`). Selected rows add an inset 3px left edge: `{colors.blocker}` for High-impact open Gaps and open Conflict lines, `{colors.gap}` for Low-confidence unconfirmed Requirements. Hover is a slight darkening (`filter: brightness(.97)`). Dialogs and the command palette are floating layers with a heavy shadow (`0 16px 40px rgba(0,0,0,.3)`) over a scrim. Transitions on colour, background and border are 0.12s; the sidebar width transition is 0.16s. All transitions are disabled under `prefers-reduced-motion`. There are no keyframe animations.

## Shapes

`{rounded.md}` (8px) for buttons, inputs and controls. `{rounded.xl}` (12px) for cards, dialogs and the app frame. `{rounded.lg}` (10px) for count badges. `{rounded.sm}` (6px) for evidence chips and agent avatars. `{rounded.full}` for status pills and human avatars (50%). Progress bars and checkboxes use 3 to 5px.

## Components

These shadcn components are used with the tokens above: Input, Textarea, Select, Command, Dialog, Sheet, Popover, DropdownMenu, Tabs (restyled as underline tabs), Tooltip, Toast (sonner), Table, Avatar, Skeleton, Separator, ResizablePanel.

- **Button.** Primary: `{colors.primary}` fill, white text, `{rounded.md}`, `8px 16px`, hover brightens. Secondary: `{colors.surface}` with a 1px `{colors.border-strong}` outline, `{typography.control}`. A disabled button is opacity .4 (redesign v2 value) with `aria-disabled` and `cursor: not-allowed`, and its reason is stated in adjacent text.
- **Card.** `{colors.surface}`, 1px `{colors.border}`, `{rounded.xl}`, soft shadow, header `{spacing.card-header}`.
- **Status pill.** Fully rounded, `{typography.label}`, a 12px icon plus a label, filled with the semantic tint and the semantic colour as text, no outline. Pill vocabulary follows EXPERIENCE.md Status Vocabulary. Example pairings: Draft (neutral, pencil), Approved (resolved, check-circle), Parsing (agent, loader), Parse failed (blocker, alert), Open Conflict (blocker, alert), Gap High (gap, triangle), Agent running (agent, sparkles), Waiting for you (gap, clock).
- **Count badge.** `{rounded.lg}`, `{typography.label}`. Sidebar badge: white on `{colors.primary}`. Tab badge: `{colors.surface-alt}` with `{colors.text-secondary}`, or `{colors.blocker-tint}` with `{colors.blocker}` on Gaps and Conflicts while blockers exist.
- **Tabs.** Underlined, 14px, a 2px `{colors.primary}` bottom border on the active tab, active label 600 in `{colors.primary-text}`, inline count badge.
- **Segmented control.** `{colors.surface-alt}` track with a 1px `{colors.border-strong}` outline. The active segment is `{colors.surface}` with `{colors.text}`. Used for versions, Condition/Contingency, list views, sub-tabs and Inspector/Activity.
- **List row.** `{spacing.row-padding}` padding, hover darkening, selected state `{colors.primary-tint}`. High-impact open Gap rows and conflicting Estimate lines add `{colors.blocker-tint}` and a 3px `{colors.blocker}` left edge. Row actions appear on hover or focus.
- **Evidence chip.** Inline, `{typography.label}`, `{colors.primary-text}` on `{colors.surface}`, 1px `{colors.border-strong}`, `{rounded.sm}`, padding `2px 8px`, an 11px quote icon and a label such as `S2 · email-it-systems`. Clicking opens the source in the Inspector with the cited span highlighted. A superseded reference is struck through with a "superseded" label.
- **Agent content.** Agent output sits on `{colors.agent-tint}` with a sparkles icon and a role label ("Engineering Agent · Medium confidence"). Human content stays on `{colors.surface}`. Agent avatars are `{rounded.sm}` squares with role initials; human avatars are circles with initials.
- **KPI tile.** A label (`{typography.label}`, `{colors.text-secondary}`), a number (`{typography.kpi}`), an optional progress bar and a sub-line (`{typography.meta}`).
- **Submission pipeline.** A vertical 8-step stepper in a card: numbered or check nodes joined by a connector line, each step with a title, a one-line state and a status pill. Complete steps use `{colors.resolved}` check nodes; Blocked steps use `{colors.blocker}`; In progress uses `{colors.agent}`; Pending is neutral. The footer reads "2 of 8 steps complete" and "3 steps blocked". It is a read-only progress view, not a forced flow.
- **Submission Blockers card.** Two groups, "Blockers to submit · N" and "Blockers to Baseline · N", each row with a blocker icon, type label, subject, and a jump button. Baseline-gate rows may be informational. When both are empty the card shows a `{colors.resolved}` check-circle "0 blockers — ready to submit".
- **Needs-you card.** A list of items waiting on the user, each with a state pill and an action, and a footer count.
- **Agent decision card.** Sparkles header with the agent role, a headline, a Reasoning bullet list, Evidence chips, Proposed next steps, a priority and confidence line, and actions on `{colors.agent-tint}`.
- **Agent run table.** One row per task with agent avatar, role, status pill, elapsed time, a one-line detail and row actions (Resolve, Open Gap, Retry, Skip). Progress is a 5 to 8px bar.
- **Run metrics.** Four KPI tiles (tokens, model calls, tool calls, elapsed) with a correlation ID. A bar turns `{colors.gap}` at its limit.
- **Role-mix bar.** A 5 to 8px stacked bar of Engineer, PM and QA, with `{colors.surface}` gaps and a text legend.
- **Inspector and Activity pane.** `{colors.surface}`, `{spacing.right-pane-width}`, header with an Inspector | Activity segmented control and close. Inspector sections use `{typography.eyebrow}` headings.
- **Estimate grid.** A table with tabular figures, sticky header and totals rows, right-aligned numbers, category groups with subtotals, and a Contingency column separated by a left rule. Columns: Line, Covers, Role mix, Effort, Cont., Total.
- **Gap row.** A 3-bar impact indicator filled in the impact colour (High `{colors.blocker}`, Medium `{colors.gap}`, Low `{colors.neutral}`) plus the word, a title, an area, a sparkles trigger label and a question status pill. High open rows use the blocker row treatment.
- **Conflict view.** Two or more selectable position cards (`aria-pressed`), each with the agent, assessment version, value, basis and Evidence chips, then a required Reason field and the Resolve and Escalate buttons.
- **Baseline marker.** A small `{colors.resolved}` tint tag reading "Baseline" with an anchor icon on the version segment and wherever versions are listed.
- **Version state pill.** A `{rounded.full}` pill inside each version segment, 11px label, `0 7px` padding: Superseded (neutral), Baseline (resolved), Draft (agent tint).
- **Version lifecycle stepper.** A card with a `{typography.eyebrow}` "Version lifecycle" label, four steps (Draft, In review, Approved, Baseline) as 18px round nodes joined by 24 x 2px connectors, and a note sentence below. Done nodes are `{colors.resolved}` with a `{colors.resolved-foreground}` check and a green connector. The current node is `{colors.primary-tint}` with a `{colors.primary}` ring and a 600 `{colors.primary-text}` label. Pending nodes use a `{colors.border-strong}` ring and connector and a `{colors.text-secondary}` label.
- **Findings table.** A card table (Severity 110, Type 110, Finding flexible, Raised by 150, Evidence 60 right). Severity is an icon plus a label: Critical `{colors.blocker}` (alert icon, whole row on `{colors.blocker-tint}`), High `{colors.gap}` (triangle), Medium and Low `{colors.text-secondary}` (alert and clock). A partial Finding adds an amber line "Partial result · blocks submission until resolved".
- **Trace event inspector.** A header (event, time, actor chip), then eyebrow-headed Payload (120px key column), Version comparison and Evidence sections, and an append-only note.
- **Settings card.** One card, `{spacing.settings-width}` wide, three 24px sections (Theme, Density, Single-key shortcuts) and a `{colors.surface-alt}` footer note. Theme and Density are radiogroups of `{rounded.lg}` option cards (16px radio dot, selected = `{colors.primary}` border on `{colors.primary-tint}`). The shortcuts row uses the Switch.
- **Switch.** 44 x 26px, `{rounded.full}`, off track `{colors.border-strong}`, on track `{colors.primary}`, a 20px white knob and an adjacent "On" or "Off" label. `role="switch"`.
- **Dialog.** `{colors.surface}`, 1px `{colors.border}`, `{rounded.xl}`, 24px padding, `{spacing.dialog-width}` wide for the Challenge dialog, shadow `0 16px 40px rgba(0,0,0,.3)` over `{colors.scrim}`. Title 20/600. The Challenge dialog's Assessment toggle cards are `{rounded.lg}` with an 18px checkbox, `{colors.primary-tint}` fill when ticked, and a selected border of `{colors.primary}` in light and `{colors.ring-dark}` in dark.
- **Skip link.** The first tab stop: `{colors.primary}` fill, white text, hidden above the viewport and moved to `top: 8px` on focus.
- **Diff view.** In the Estimate grid and the pending Requirement diff, changed values sit on `{colors.primary-tint}`, never the semantic red or green, with `+`/`−` text markers. Increases in a delta column use `{colors.gap}` text. The Trace inspector's **Version comparison** is the one exception (redesign v2): each row is a `{rounded.md}` row with a bold `+` or `−` marker in `{colors.resolved}` on `{colors.resolved-tint}` (added) or `{colors.blocker}` on `{colors.blocker-tint}` (removed), with the row text in `{colors.text}`. The marker, not the colour, carries the meaning. `[ASSUMPTION]` red and green are kept here because the redesign draws them and the sign is always present.
- **Banners and alerts.** A full-width card strip with a semantic tint, an icon, a bold lead sentence, a detail sentence and actions. Informational banners use `role="status"`; blocking ones use `role="alert"`.
- **Offline banner.** A full-width strip at the top of the main pane: `{colors.neutral-tint}` fill, `{colors.text}` ink, a 1px `{colors.border-strong}` bottom rule, `10px 32px` padding, a wifi-off icon, a lead sentence and a **Retry** secondary button. `role="alert"`.
- **Inline alert (412).** A `{components.inline-alert.background}` block with `{rounded.lg}`, a bold `{colors.blocker}` lead ("Not saved: this line changed (412)"), a `{colors.text}` detail sentence and **Reload** and **View diff** secondary buttons. `role="alert"`. It sits above the field it concerns.
- **Empty tab card.** A card with `64px 24px` padding, centred: a 16/600 title, one sentence (max 440px, `{colors.text-secondary}`) and one primary button that jumps to the tab that fixes the emptiness. No illustration.
- **Skeleton.** Neutral placeholder rows matching the layout, without shimmer.
- **Knowledge graph.** A 660px high force-directed canvas on `{colors.graph-canvas}`, filter chips, a legend (solid link, dashed missing coverage, dashed ring stale or failed), and a 372px node-detail drawer.
- **Coverage matrix and variance bars.** Cells and bars use the semantic tint plus an icon and a text value.

## Do's and Don'ts

| Do | Don't |
| --- | --- |
| Pair every semantic colour with an icon and a label | Signal state by colour alone |
| Use tint-filled pills with icon and label | Use outline-only pills or bare coloured text |
| Use 14px body, comfortable rows and 38px primary buttons | Shrink back to 13px or 32px rows |
| Use `{colors.border-strong}` for control outlines and `{colors.border}` only for decoration | Rely on `{colors.border}` to show where an input or button is |
| Use `{colors.link}` for links, `{colors.ring-dark}` for the dark focus ring | Use the primary fill colour as text on dark surfaces |
| Use tabular figures in every numeric column | Use proportional numbers in tables |
| Show agent output on `{colors.agent-tint}` with a sparkles icon and role label | Personify agents with names, faces or chat bubbles |
| Use `{colors.border-strong}` on the switch off track, pending stepper rings and unticked boxes | Use `{colors.border}` for any shape that must be seen |
| Use one primary button per view, plus the jump-to-blockers action while Submit is disabled | Use several competing primary actions |
| Keep transitions at 0.12s and drop them under reduced motion | Add keyframe pulses, confetti or long shimmer |
| Use the redesign import and the spines as the visual reference | Copy colours from the older `mockups/` files |
