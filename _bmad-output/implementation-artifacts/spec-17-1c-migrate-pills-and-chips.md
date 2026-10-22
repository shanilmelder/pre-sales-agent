---
title: 'Story 17.1c: Migrate status pills and chips onto Pill and Chip'
type: 'refactor'
created: '2026-10-22'
status: 'done'
baseline_commit: 'e24a708c2748b77a6888cfbf4310cbbba224b2c1'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-1b-ui-primitives.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** About 14 status pills and 14 chip sites still use the old outlined `h-5 rounded-full border bg-background` look with a tinted icon only. Story 17.1b added `Pill` (tint fill) and `Chip`, but nothing uses them.

**Approach:** Move every named pill and inline pill string onto `Pill`, and every evidence/count chip onto `Chip`, with no behaviour change. Map the lib `text-*` status tones to Pill tones in one helper instead of rewriting the lib maps.

## Boundaries & Constraints

**Always:** Keep every `data-status`, `data-severity`, `data-question-status`, `data-gap-status`, `data-recommendation`, `data-task-pill`, `data-eval-status`, `data-entry-status`, `data-label`, `data-passage-id`, `aria-pressed` and test id (`detected-from-text`, `running-dot`). Keep the label text and icon of each pill. Tone mapping: text-resolved to resolved, text-gap to gap, text-blocker to blocker, text-agent to agent, anything else to neutral. Fixed widths (`w-[5.5rem]`) pass through `className`. Type classes stay outside `cn()` (see 17.1b notes).

**Never:** Change lib status maps, labels or the `StatusTone` strings. Touch the count badge in `workspace-tabs.tsx`, the toggle in `settings-form.tsx`, or `kbd` elements. Add new Pill tones. Redesign the callout `<p>` at `gap-inspector.tsx:466`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Known status | `gaps_open` | Pill tone gap, icon plus label, `data-slot="pill"` | N/A |
| Unknown tone class | `text-muted-foreground` or unmapped | Pill tone neutral | Never throws |
| Interactive chip | EvidenceChip pressed | Chip look, `aria-pressed=true`, primary border and tint kept, focus ring kept | N/A |

</frozen-after-approval>

## Code Map

- `web/src/components/ui/pill.tsx`, `chip.tsx` -- primitives; Chip gains an exported `chipClassName` for button chips.
- `web/src/lib/pill-tone.ts` (new) -- `pillToneFor(tone: string): PillTone`.
- Pills: `opportunities/{status-pill,severity-pill,conflict-status-pill,gap-inspector,specialist-assessments,sources-list,estimate-grid}.tsx`, `knowledge/sources-table.tsx`, `admin/{evals-view,catalogue-table}.tsx`.
- Inline pill strings: `gaps-list.tsx:320,324`, `overview-summary.tsx:310`, `red-team-list.tsx:206`, `specialist-assessments.tsx:326`.
- Chips: `estimate-grid.tsx:90`, `gap-inspector.tsx:181,407`, `red-team-list.tsx:50`, `conflict-inspector.tsx:66,74`, `requirement-inspector.tsx:41` (button), `assumptions-register.tsx:108` (button), `conflicts-list.tsx:107`, `estimate-inspector.tsx:143`, `red-team-inspector.tsx:53`, `assessment-finding-inspector.tsx:65`, `gaps-list.tsx:355`, `DetectedFromTextTag`.
- Tests: `status-pill.test.tsx` (rewrite), plus conflicts, gaps, red-team, specialist-assessments, sources-table tests where they assert old classes.

## Tasks & Acceptance

**Execution:**
- [ ] `web/src/lib/pill-tone.ts` + test -- add helper and cover each mapping and the fallback.
- [ ] `web/src/components/ui/chip.tsx` -- export `chipClassName` -- button chips reuse the look.
- [ ] Pill files listed in the Code Map -- render `Pill` with `pillToneFor` and keep data attributes.
- [ ] Inline pill strings -- replace with `Pill tone="neutral"`.
- [ ] Chip sites -- replace with `Chip`, or `chipClassName` on buttons.
- [ ] Affected tests -- update class assertions to `data-slot`, `data-tone` and tint classes.

**Acceptance Criteria:**
- Given any migrated pill, when rendered, then it has `data-slot="pill"`, the right `data-tone`, its icon and label, and its original data attributes.
- Given the repo, when grepping `web/src` for `rounded-full border` or `rounded-sm border` pill/chip strings, then only the excluded sites remain.
- Given lint, typecheck, build and tests, when run, then all pass with axe clean.

## Implementation Notes

- Added `chipLayoutClassName` for button chips that recolour when pressed; `chipClassName` was dropped as unused.
- `gaps-list.tsx:355` is a `kbd`, left alone.
- New `ui/pill-migration.test.tsx` covers the tones the migrated tests did not assert.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Edge, Blind, Gap | `chipClassName` exported but unused | low | grep: no consumer outside chip.tsx. Dead export; both button chips use `chipLayoutClassName`. | patch (export removed) |
| 2 | Gap | No `data-tone` assertion for catalogue, eval, question, gap pills (task pill is not exported) | medium | No test asserted these tones; a swapped tone would pass. Added `ui/pill-migration.test.tsx` (16 tests). | patch |
| 3 | Gap, Blind | No tests for VersionPill, CoversChip, DetectedFromTextTag, Chip | low | Covered by the same new test file (neutral tone, chip classes, axe). | patch |
| 4 | Edge, Blind | `pillToneFor` silently falls back to neutral for an unmapped tone | low | Spec fixes this design (lib maps unchanged, unmapped is neutral); every current lib tone is in the five classes and the new tests assert each. | rejected |
| 5 | Edge | Caller className can override Pill tone colours | false | No migrated caller passes a text or bg colour; they pass `shrink-0` or width. | rejected |
| 6 | Edge, Blind | `w-[5.5rem]` too narrow for labels | false | Longest labels are Critical, Skipped, Running (about 80px with padding and icon, under 88px). | rejected |
| 7 | Edge | DetectedFromTextTag lost 4px icon-side padding | low | Cosmetic; Chip px-2 is the redesign chip. | rejected |
| 8 | Edge | CoversChip lacks `shrink-0` | false | The old CoversChip had none either. | rejected |
| 9 | Edge, Blind | Hover `brightness(.97)` weak or invisible | false | The redesign hover rule in the Epic 17 context. | rejected |
| 10 | Blind | Tint-on-text contrast not gated | false | `contrast.test.ts` already asserts blocker, gap, resolved, neutral, agent on their tints, light and dark. | rejected |
| 11 | Blind | Neutral Pill used for non-status text (version, review, Converted, Dismissed) | low | Spec's Always/approach maps inline pill strings to neutral Pill; design choice, not a defect. | rejected |
| 12 | Blind | Status tests assert class strings; dropped neutral-label assertion | low | Rendered colour is gated by contrast.test.ts; asserted classes exist in the built CSS. | rejected |
| 13 | Blind | Import placement and possibly unused `cn` | false | Lint and typecheck are clean; no enforced import order. | rejected |
| 14 | Gap | Svg-level `aria-hidden` check gone; sources-table `closest('span')` brittle | low | Pill wraps the icon in an aria-hidden span; the test passes and axe is clean. | rejected |
| 15 | Blind | Chip lacks an icon slot | low | Not in the spec; no consumer needs it. | rejected |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.
