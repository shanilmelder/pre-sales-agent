---
title: 'Story 17.1a: Redesign tokens, contrast gate, product name and running state'
type: 'refactor'
created: '2026-10-21'
status: 'done'
baseline_commit: '78b2cb8ae81f354e57993034ce94e2c560927537'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/DESIGN.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The web app still uses the old dense identity: 13px type, 4/6/8 radii, 32px rows, JetBrains Mono, pulsing running dots and the title "Pre-Sales Agent". The DESIGN.md tokens are not applied, so every later Epic 17 story would build on the wrong base.

**Approach:** Replace the token layer in `globals.css` with the DESIGN.md values, rewrite the contrast test against the DESIGN.md contrast table, remove JetBrains Mono, retitle the pages, and replace the pulsing running dots with a static icon. Primitive components and the three status pills are Story 17.1b.

## Boundaries & Constraints

**Always:**
- Tokens equal the DESIGN.md front matter, light and dark. New tokens are plain hex custom properties inside `:root` and `.dark`, because `contrast.test.ts` parses only those two blocks.
- Keep `--spacing-row`, `--spacing-row-compact`, `p-gutter`, `w-sidebar`, `w-inspector`, `w-rail` and the `text-body`, `text-body-strong`, `text-label`, `text-meta`, `text-title`, `text-section` and `text-numeric` utilities. Change values only. Map DESIGN.md's row padding onto the existing row names so comfortable rows are about 56px and compact rows proportionally smaller, and note the mapping in Implementation Notes.
- Keep legacy aliases (`diff-tint`, `evidence-highlight`, `surface-sidebar`, `surface-inspector`) pointing at the new values until Story 17.3.
- Running is a static lucide `LoaderCircle` (no rotation, no keyframes) keeping `data-testid="running-dot"`.
- `data-density` and the `.dark` class keep working with `lib/preferences.ts` and `theme-script.tsx`.
- The product name is "Pre Sales Agent Framework".

**Never:**
- No new or restyled primitives, no pill migration, no tabs, shell, Settings or list layout changes (Stories 17.1b to 17.4).
- No new dependency, Storybook or visual-regression setup, and no backend change.

**Decisions:**
- The epics say six `animate-pulse` dots. The code has nine, plus one skeleton pulse in `opportunities-table.tsx`. All nine become the static icon, and the skeleton becomes a static `bg-muted` block.
- `font-mono text-meta` appears in 10 files. Replace it with Inter and remove JetBrains Mono from `layout.tsx` and `globals.css`.
- Rows become about 56px on every list at once. That visible change is intended.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Contrast gate | A DESIGN.md pair is below its minimum (4.5 text, 3 UI) | `contrast.test.ts` fails and names the pair and ratio | N/A |
| Token drift | A `:root` or `.dark` value differs from DESIGN.md | The pinned-value test fails | N/A |
| Running state | A task, run or source is Running | Static icon with `data-testid="running-dot"`, no `animate-pulse` | N/A |
| Dark theme | `.dark` on `<html>` | Dark values apply, no flash | N/A |

</frozen-after-approval>

## Code Map

- `web/src/app/globals.css` -- sole token source (Tailwind v4 `@theme inline`); `:root` about 99-158, `.dark` 164+, type roles 16-39, radii 90-96, row-height 146-148, `--font-mono` line 12, `text-numeric` 216-221. Missing tokens: `canvas`, `surface`, `surface-alt`, `border-strong`, `text-secondary`, `primary-tint`, `primary-text`, `link`, `agent-tint`, `gap-tint`, `resolved-tint`, `resolved-foreground`, `neutral(-tint)`, `role-*`, `scrim`, `graph-*`, `dialog-width`, `settings-width`, `--radius-xl`, shadows, `kpi` and `eyebrow` roles.
- `web/src/app/layout.tsx` -- Inter and JetBrains_Mono via next/font (2, 11-19, 33); title and description (22-23).
- `web/src/lib/contrast.test.ts` -- regex-parses globals.css; `PAIRS` 84-116, pinned old values 131-160. Rewrite whole.
- `web/src/lib/preferences.test.ts` (148-165) and `web/src/app/layout.test.tsx` (9-10, 40, 49) -- assert old row heights, `--spacing-*` strings and the JetBrains mock. Update.
- Running dots: `knowledge/sources-table.tsx:57`, `opportunities/assumptions-register.tsx:334`, `estimate-grid.tsx:688,700`, `gaps-list.tsx:405`, `red-team-list.tsx:219`, `requirements-list.tsx:394`, `sources-list.tsx:72`, `specialist-assessments.tsx:458`; skeleton `opportunities-table.tsx:85`. Their tests use `getByTestId("running-dot")`; only `specialist-assessments.test.tsx:1028` asserts `animate-pulse`.
- `web/src/components/access-gate.tsx:20` and 13 page `metadata` titles ending " · Pre-Sales Agent" -- product name.
- Do not break: `h-row`, `min-h-row` (43 uses), `data-density`, `p-gutter`, `w-sidebar`, `w-inspector`, `w-rail`, the `text-*` roles above.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/app/globals.css` -- apply DESIGN.md colours, radii 6/8/10/12, type roles, spacing, row padding, shadows and sizes; add the missing tokens; remove `--font-mono`; keep aliases -- UX-DR1.
- [x] `web/src/app/layout.tsx`, the 13 page metadata titles, `access-gate.tsx` -- title "Pre Sales Agent Framework", drop JetBrains_Mono -- product name.
- [x] The 10 `font-mono text-meta` files -- switch to Inter -- UX-DR1.
- [x] `web/src/lib/contrast.test.ts` -- rewrite: assert every DESIGN.md contrast-table pair (including the seven fixes) in light and dark, and pin each token value -- UX-DR23, NFR-7.
- [x] The nine running-dot components and `opportunities-table.tsx` -- static icon and static skeleton -- UX-DR10.
- [x] `preferences.test.ts`, `layout.test.tsx`, `specialist-assessments.test.tsx:1027-1029` and any test that breaks from the new values (`opportunities-table`, `workspace-tabs`, `workspace-header`, `app-shell`, `estimate-grid`, `min-h-row`, `bg-diff-tint`, `bg-evidence-highlight` checks) -- update selectors and values.

**Acceptance Criteria:**
- Given `globals.css`, when the app builds, then every token in `:root` and `.dark` equals DESIGN.md and no JetBrains Mono is loaded.
- Given the contrast test, when a pair falls below its minimum or a pinned value drifts, then it fails.
- Given a Running state, when shown, then it is a static icon and no `animate-pulse` remains under `web/src`.
- Given any page, when its title renders, then it reads "Pre Sales Agent Framework".

## Implementation Notes

- Row mapping: DESIGN.md row padding (12 comfortable, 6 compact) around a 32px content line gives `--row-height-comfortable: 56px` and `--row-height-compact: 44px`. `p-gutter` is now 20px (page-padding).
- shadcn names map onto DESIGN.md surfaces (`--card`/`--popover` = surface, `--muted`/`--secondary`/`--accent` = surface-alt, `--muted-foreground` = text-secondary, `--input` = border-strong, `--destructive` = blocker). Legacy aliases point at primary-tint and surface.
- The assumptions register's `proposing-dot` is also a static `LoaderCircleIcon`, keeping its test id.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Edge | Dark `text-primary` link text drops to 3.0:1 | high | `--primary` dark is #4F5BD5 (3.0:1 on surface). `text-primary` is used as text in access-gate.tsx:40, estimate-inspector.tsx:70, overview-summary.tsx:72, requirements-list.tsx:1383, trace-list.tsx:158 and button.tsx:19 (link variant). The old dark primary passed 4.5:1. Breaks NFR-7. | patch |
| 2 | Blind, Edge | Contrast test no longer gates blocker, agent, sidebar pairs on common surfaces | medium | The old test asserted blocker/agent on surfaces and the sidebar pairs. The new BOTH list has none for them. The values pass today, but a regression would not fail CI. | patch |
| 3 | Gap, Blind, Edge | Running-dot tests assert only that the class lacks "animate"; any element passes. No test for `proposing-dot` | medium | `getAttribute("class") ?? ""` + `not.toContain("animate")` passes for a removed or replaced element. grep finds no `proposing-dot` test. | patch |
| 4 | Blind | Static loader never rotates | false | The frozen block decides "static lucide LoaderCircle (no rotation, no keyframes)"; epics UX-DR10 says static loader icon. The text label stays. | rejected |
| 5 | Blind, Edge | No aria-busy/role=status; static icon looks stalled | false | The old dot was aria-hidden with no live region either. Intent is a static icon (spec, UX-DR10). | rejected |
| 6 | Blind | Same running-icon JSX copy-pasted nine times | low | Real, but a shared RunningIndicator is new public surface; 17.1b's primitives can absorb it. Drift today is cosmetic (size wrapper only). | rejected |
| 7 | Blind | Lucide import order inconsistent | low | `npm run lint` is clean; no sort rule. | rejected |
| 8 | Blind | contrast.test.ts rewrapped to narrower width | low | No formatter or printWidth is configured, and the file was rewritten wholesale. | rejected |
| 9 | Blind, Edge | `UI - 0.01` tolerance for dark primary on surface | low | DESIGN.md accepts exactly 3.00:1 for the switch track; the published-ratios test pins it at 3.0. | rejected |
| 10 | Blind, Edge | `.dark` drops sidebar, chart and scrim tokens and inherits from :root | false | `.dark` and `:root` match the same `<html>`, so `var()` aliases resolve with the dark values. Scrim is identical in both themes in DESIGN.md. `--chart-*` has no consumer (grep). | rejected |
| 11 | Blind | Type scale changes untested, font-mono usages may remain, body tabular-nums | false | grep finds no `font-mono` or `text-mono` in src; body tabular figures are specified at DESIGN.md:79; row heights are asserted in preferences.test.ts. | rejected |
| 12 | Blind | Brand name repeated in 13 titles; description still "Agentic AI Presales Platform" | low | Acceptance names page titles only. A title template or description rewrite is a refactor or new wording, and no test or user-visible title is wrong. | rejected |
| 13 | Blind | Unused graph, dialog, settings and role tokens | false | The acceptance criterion requires every DESIGN.md token to be present. | rejected |
| 14 | Blind | Legacy aliases flatten sidebar and inspector surfaces | false | DESIGN.md: sidebar and right pane use `surface`. Alias removal is Story 17.3. | rejected |
| 15 | Edge | Fixed px line-heights | false | DESIGN.md specifies px line-heights, and the font sizes are px too. | rejected |
| 16 | Edge | `--radius-2xl` to `4xl` capped at 12px | false | No `rounded-2xl` or larger in src; DESIGN.md has no larger step. | rejected |
| 17 | Edge | No grep gate for `font-mono` or `text-mono` | low | No matches exist today; not caused by this change. | rejected |
| 18 | Edge | Spec counts (13 titles, 10 files) are wrong | low | The fix is to edit this spec, which is not allowed. The grep gate finds no leftovers. | rejected |
| 19 | Edge | Status pill width shifts (icon size-3, no mx-0.5) | low | Pill migration is Story 17.1b. | rejected |
| 20 | Gap (other) | Skeleton rows and brand titles have no assertion | low | Static style and static text; no behavior to pin. | rejected |

## Verification

**Commands:**
- `npm run lint --prefix web` -- expected: no errors
- `npm run typecheck --prefix web` -- expected: no errors
- `npm test --prefix web` -- expected: all tests pass, including the rewritten contrast test
- `npm run build --prefix web` -- expected: build succeeds
- `grep -rn "animate-pulse\|JetBrains\|Pre-Sales Agent" web/src` -- expected: no matches

**Manual checks (if no CLI):**
- Open Opportunities, Gaps and Estimate in light and dark: rows are padded, no pulsing dots, no mono text.
