---
title: 'Story 1.8 (Part A): Opportunity workspace with tabs and status'
type: 'feature'
created: '2026-10-04'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '81b69a930df076d347df2b02e014c8bbd60afe04'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Opening an Opportunity shows a flat list of fields. There are no workspace tabs, no keyboard tab switching, and the status pill has no colour token. Later epics need a workspace to plug their tabs into.

**Approach:** Turn `/opportunities/{id}` into the workspace, web-only.
- **Header:** title, derived status pill, owner, collaborators and target proposal date.
- **Tab strip:** the nine EXPERIENCE.md tabs, each with its own URL and reachable with keys `1`–`9`.
- **Content:** a real Overview. The other eight tabs show "Not available yet."
- **Pill:** gains the Status Vocabulary colour tokens.

## Boundaries & Constraints

**Always:**
- **Tabs:**
  - Order: Overview, Sources, Requirements, Gaps, Assessments, Conflicts, Estimate, Trace, Actuals.
  - Routes are `/opportunities/{id}/{slug}`, with lowercase slugs (`overview`, `sources`, …). `/opportunities/{id}` serves Overview, and an unknown slug gives the not-found page.
  - The strip is a `tablist` of links. The active tab has `aria-selected="true"` and a 2px primary underline, and each tab shows its key number before the label.
  - The header and strip sit in a layout shared by all tabs, so the Opportunity is fetched once per navigation into the workspace.
- **Keys:**
  - `1`–`9` navigate to the matching tab.
  - Like the shell's other single-key shortcuts, they do nothing when single-key shortcuts are off, a dialog is open, focus is in a text field or menu, or a modifier is held.
  - The cheat sheet lists "Switch workspace tab" with keys `1`–`9`.
- **Unbuilt tabs:** show the plain text "Not available yet." and are never hidden or disabled.
- **Header:** follows `mockups/opportunity-overview.html` for density: 18px/600 title, then a 12px meta row with the pill, owner, collaborators and target proposal date (calendar icon, formatted with `formatDate`). Later-epic items (Submit, Cancel run, estimate version, badges, blockers, activity) are not built. Where the mockup and the UX spines disagree, the spines win.
- **Overview:** status, owner, collaborators (keeping Part A's management controls), created date, customer, products in scope and industry.
- **Status pill (AD-26, UX-DR8):**
  - Status stays derived by the API. The web never computes it.
  - The pill stays 20px high, fully rounded, with a neutral outline and the label in foreground.
  - Only the icon takes the mapped token: `gaps_open` → `gap`, `assessing` → `agent`, `baselined` → `resolved` with the `Anchor` icon, every other status → `muted-foreground`.
  - Icon and label always render together, and the icon is `aria-hidden`.
- **Access:** a non-reader or unknown id sees "You don't have access to this Opportunity" on every tab URL, with no tab strip.

**Never:** No backend or API changes, no inline editing (Part B), no tab badges or counts, no blockers (Epic 8), no SSE, no stored status.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open | Reader opens `/opportunities/{id}` | Header + Overview, tab 1 selected | API down: "The platform is not reachable right now. Try again in a moment." |
| Tab URL | `/opportunities/{id}/gaps` | Header, tab 4 selected, "Not available yet." | Unknown slug: not-found page |
| Key | Press `4` on Overview | Navigates to `/gaps` | N/A |
| Key ignored | `4` while typing in collaborator search, with the palette open, with single-key off, or with Ctrl held | No navigation | N/A |
| No access | Non-reader on any tab URL | "You don't have access to this Opportunity", no tabs | N/A |
| Pill | Each of the 8 statuses | Icon + label, mapped token class on the icon | N/A |

</frozen-after-approval>

## Code Map

- `web/src/app/opportunities/[id]/page.tsx` -- the current detail page (access gate, `getOpportunity`, `Detail` rows, `Collaborators`). Turn it into `[id]/layout.tsx` (gate, fetch, header, tab strip) plus `[id]/page.tsx` (Overview) and `[id]/[tab]/page.tsx` (validates the slug, renders the placeholder or `notFound()`). The layout can't read the active segment, so the tab strip is a client component using `useSelectedLayoutSegment()`.
- `web/src/app/opportunities/data.ts` -- `getOpportunity` (`not-found`, `error`). Wrap it in React `cache()` if the layout and pages both need the Opportunity.
- `web/src/components/opportunities/collaborators.tsx` -- reuse as is on Overview.
- `web/src/components/opportunities/status-pill.tsx`, `web/src/lib/opportunities.ts` (`STATUSES`, `formatDate`) -- add `tone` to each `STATUSES` entry and switch baselined to `AnchorIcon`. Tokens exist as Tailwind colours `text-gap`, `text-agent`, `text-resolved` and `text-muted-foreground` (`globals.css:51-53`).
- `web/src/components/shell/keyboard-shortcuts.tsx` -- reuse the global handler's rules: `isEditableTarget`, `modifiers`, `shell.singleKeyShortcuts`, `shell.dialog` and the `[role="menu"]` check. Do not duplicate them. Either extend the handler with a workspace-tab hook (e.g. a `tabTargets` registration in shell context), or export a shared `singleKeyAllowed(event, shell)` that the workspace's own listener calls.
- `web/src/lib/shortcuts.ts`, `web/src/components/shell/cheat-sheet.tsx` -- add the display entry for `1`–`9`. Existing entries and tests show the shape.
- `web/src/components/shell/app-shell.tsx:59` -- `PlaceholderPage` shows the "Not available yet." copy. The tab body uses the same sentence without the h1.
- `web/src/app/opportunities/pages.test.tsx` -- existing page tests and mocks for `getMe`/`getOpportunity`. Extend them.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/opportunities.ts`, `web/src/components/opportunities/status-pill.tsx` -- per-status tone and the anchor icon
- [x] `web/src/lib/workspace.ts` -- the tab list (slug, label, key) and `tabHref(id, slug)`, the single source for strip, routes, keys and cheat sheet
- [x] `web/src/app/opportunities/[id]/{layout.tsx,page.tsx,[tab]/page.tsx}`, `web/src/components/opportunities/{workspace-header.tsx,workspace-tabs.tsx}` -- layout, header, strip, Overview and placeholder tabs
- [x] `web/src/components/shell/{keyboard-shortcuts.tsx,shell-context.tsx,cheat-sheet.tsx}`, `web/src/lib/shortcuts.ts` -- `1`–`9` handling under the shared single-key rules, and the cheat-sheet entry
- [x] Tests (`status-pill.test.tsx`, `workspace-tabs.test.tsx`, `workspace-header.test.tsx`, `pages.test.tsx`, `keyboard-shortcuts`/`app-shell` tests) -- every matrix row, plus axe on the header, tabs and Overview

**Acceptance Criteria:**
- Given a reader on Overview, when they press `1`–`9` in turn, then the URL and the selected tab follow each key, and Back returns to the previous tab.
- Given CI, when it runs, then web lint, typecheck, tests (axe included) and build pass, and backend checks are unchanged and green.

## Implementation Notes

- Keys: the shell context holds `workspaceTabs` (registered by the tab strip through `useWorkspaceTabKeys`); the global handler runs `1`–`9` after its existing single-key checks, so the rules are not duplicated. `SHORTCUTS` gains a `digit` match kind for the cheat-sheet entry.
- Every tab href is `/opportunities/{id}/{slug}` (Overview included); `/opportunities/{id}` also serves Overview.
- Overview is gated in the page too (`OverviewTab`), since a layout can't keep a page out of the payload; `getOpportunity` is wrapped in `cache()` so layout and page share one fetch per request.
- Known gap: after a collaborator change on Overview, the header's collaborator list updates only on the next navigation into the workspace (the Collaborators component is reused as is).

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, VG, ECH | Header collaborator list goes stale after an add or remove on Overview, and no test catches it | medium | `Collaborators` only calls `setOpportunity` (`collaborators.tsx:115,157`) and nothing refreshes the layout. Fix: `router.refresh()` after success, plus a test | patch |
| 2 | ECH | Layout keeps its first fetch across tab switches, so the header can be older than the tab | low | Only visible when someone else changes the Opportunity; #1 covers own changes. A fix means refetching on every navigation | reject |
| 3 | BH, ECH | Digit for the open tab pushes a duplicate history entry | low | `router.push(href)` runs unconditionally; the fix is a direct pathname comparison | patch |
| 4 | BH | Overview has two URLs (`/{id}` and `/{id}/overview`) | low | Required by the frozen spec (routes per slug, `/opportunities/{id}` serves Overview) | reject |
| 5 | BH, ECH | Space doesn't activate a link tab | low | Links activate on Enter, which is not a WCAG failure. Adds a key branch for a rare path | reject |
| 6 | BH | `aria-keyshortcuts` still announced with single-key shortcuts off | low | Always set in `workspace-tabs.tsx`; direct conditional on `singleKeyShortcuts` | patch |
| 7 | BH | Palette could run `switch-workspace-tab` by id as a no-op | false | `command-palette.tsx` runs nav items only and never uses `SHORTCUTS`; the frozen spec requires the cheat-sheet entry | reject |
| 8 | BH | Selected tab can scroll out of view | false | Minimum supported width is 1280px; nine 34px-high label tabs fit without overflow | reject |
| 9 | BH | Placeholder tabs lack the sr-only heading Overview has | low | Inconsistent heading navigation; direct fix (sr-only h2 with the tab label) | patch |
| 10 | BH | Placeholder branch doesn't gate access itself | false | It renders only static "Not available yet." text and no Opportunity data; the layout shows no-access | reject |
| 11 | BH, ECH | Unknown slug 404s before the access check | low | The not-found page leaks nothing, and the frozen spec specifies not-found for an unknown slug | reject |
| 12 | BH, ECH | Created date uses the UTC calendar day | low | Project convention: `formatDate` is UTC-based "the same in every time zone" | reject |
| 13 | BH | Empty products or industry render blank | false | The API requires 1–20 products and a non-empty industry (`domain/opportunity.py`) | reject |
| 14 | BH | `getMe` called twice per workspace load | false | `getMe` is wrapped in React `cache` (`lib/api/server.ts:26`) | reject |
| 15 | BH | Pages call `OverviewTab` as a function | low | Works today with no named harm; a refactor would only affect tests | reject |
| 16 | BH, ECH | Tabpanel unnamed when the segment is unknown | maybe-false | `notFound()` renders the root boundary in place of the `[id]` layout; would need a render with an unknown segment inside the layout. Low at most | reject |
| 17 | BH | Platform-down message is a duplicated literal | low | Pre-existing copy, moved unchanged | reject |
| 18 | BH | axe runs on only some workspace paths | low | Overview, a placeholder, tabs, header and pill all have axe checks; the remaining paths are plain text | reject |
| 19 | BH | `data-status` on the pill is unused | low | Nothing reads it; direct deletion | patch |
| 20 | ECH | Ctrl+Alt+digit (AltGr) switches tabs | low | AltGr digit chords produce other characters on layouts that use them; rare | reject |
| 21 | ECH | Cheat-sheet "1–9" and the index mapping aren't derived from `workspace.ts` | low | Keys equal position by construction; no caller diverges today | reject |
| 22 | VG | No test that layout and tab share one fetch | low | Performance only; jsdom can't observe the request-scoped `cache` | reject |

## Verification

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks (human):**
- Open an Opportunity, press 1–9, check the tab URLs and placeholders, turn single-key shortcuts off in Settings and confirm the digits stop working.
