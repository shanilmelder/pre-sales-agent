---
title: 'Story 17.2a: Settings card, shortcuts default Off and first-run hint'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: '998fb08c0fe95219e152908d6538cdde09a2b0a4'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-1b-ui-primitives.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Settings still uses the old hand-rolled radios and checkbox in a narrow form, single-key shortcuts default to On, there is no first-run hint, and the command palette item reads "Settings", not "Open Settings" (Story 17.2, UX-DR4, UX-DR26, NFR-7).

**Approach:** Rebuild the Settings page as the redesigned 760px card on the 17.1b primitives, default `singleKeyShortcuts` to Off, show a first-run hint while no `psa_prefs` cookie exists, and rename the palette command. Shell chrome and the Offline strip are separate stories (17.2b, 17.2c).

## Boundaries & Constraints

**Always:** Preferences stay in the `psa_prefs` cookie via `savePreferences`; no server table, no localStorage. Keep autosave, rollback on failure and the polite failure announcement. Settings card 760 wide, three 24px sections (Theme, Density, Single-key shortcuts), surface-alt footer note. Theme and Density are radio groups of option cards (radius 10, selected = `primary` border on `primary-tint`, visible focus ring). The shortcut control is `ui/switch` with visible On/Off text and an accessible name. Density hints read 56px and 44px rows. Missing, malformed or partial cookies parse to the new default (Off). An existing cookie that stores `true` keeps its value.

**Never:** Add a header theme toggle, user card, org switcher or pane tabs (17.2b). Touch the Offline strip (17.2c). Add notification or role settings. Use localStorage.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First visit | No `psa_prefs` cookie | Shortcuts Off; shell shows the hint with Turn on and Dismiss | N/A |
| Turn on from hint | Click Turn on | Cookie saved with shortcuts On; hint gone; shortcuts work | Save fails: hint stays, failure announced |
| Dismiss hint | Click Dismiss | Cookie saved with current defaults (Off); hint gone | Same as above |
| Saved preference | Cookie exists | No hint; stored values apply, including `true` | N/A |
| Change setting | Pick Dark, Compact or toggle switch | Cookie updates, UI reflects it, `<html>` attributes follow on re-render | Save fails: roll back to last saved, announce |
| Palette | Open palette | Item "Open Settings" goes to /settings | N/A |

</frozen-after-approval>

## Code Map

- `web/src/lib/preferences.ts` -- default `singleKeyShortcuts: false`; add a server helper that says whether the cookie exists.
- `web/src/app/layout.tsx`, `components/shell/shell-context.tsx`, `components/shell/app-shell.tsx` -- carry the first-run flag; render a new `ShortcutHint` strip above the top bar.
- `web/src/components/shell/shortcut-hint.tsx` (new) -- hint with Turn on and Dismiss, both call `savePreferences`.
- `web/src/components/settings-form.tsx`, `app/settings/page.tsx` -- card, option cards, `ui/switch`, `ui/card`; keep the save logic.
- `web/src/components/shell/command-palette.tsx` -- label "Open Settings".
- Reuse `ui/card`, `ui/switch`, `ui/button`. Type classes go outside `cn()` (17.1b notes).
- Tests: `lib/preferences.test.ts`, `components/settings-form.test.tsx`, `components/shell/app-shell.test.tsx`, `app/layout.test.tsx`, new `shortcut-hint.test.tsx`; update any test that assumes the default On.

## Tasks & Acceptance

**Execution:**
- [ ] `lib/preferences.ts` + test -- default Off, cookie-exists helper, existing `true` preserved.
- [ ] Layout, shell context, app shell, `shortcut-hint.tsx` + test -- first-run hint per the matrix.
- [ ] `settings-form.tsx`, `settings/page.tsx` + tests -- redesigned card on the primitives.
- [ ] `command-palette.tsx` + test -- "Open Settings".
- [ ] Existing tests that assumed shortcuts On -- set the preference explicitly.

**Acceptance Criteria:**
- Given no cookie, when any shell page loads, then shortcuts are Off and the first-run hint explains how to turn them on.
- Given the Settings page, when it renders, then Theme, Density and the shortcut switch show in a 760px card, are operable by keyboard, and axe is clean in light and dark.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- `ShortcutHint` saves literal defaults (system, comfortable) because client code cannot import runtime values from `lib/preferences.ts` (next/headers).
- The card footer holds only "Saved in this browser."; the old sentence about administrators managing notifications and roles was dropped to match the existing page test.
- Full-suite failures seen during implementation came from concurrent test runs; idle runs are green.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Gap | No test that the layout passes `firstRun` to the shell (inverting or dropping it passes every test) | medium | Verified: layout.test never set `stored=false`; app-shell and hint tests feed the prop directly. Added two layout cases with a `useShell` probe. | patch |
| 2 | Edge, Blind | Turn on may not enable shortcuts until a server re-render | false | `savePreferences` sets the cookie in a Server Action, which re-renders the route and layout (the same path Theme and the Settings switch already rely on); the hint hides on `ok`. | rejected |
| 3 | Edge, Blind | Visible On/Off text removed from Settings | false | `ui/switch` renders the `switch-label` span with On/Off; the settings tests assert it. | rejected |
| 4 | Edge, Blind | Settings change leaves the hint showing on the same page | false | The same Server Action re-renders the layout; `hasStoredPreferences` is then true and `firstRun` false. | rejected |
| 5 | Blind | Existing users flip to Off silently | false | A stored `true` is kept and tested; the cookie always writes the field, so partial cookies are not produced by the app. | rejected |
| 6 | Edge, Blind, Gap | Hint saves hard-coded BASE (theme, density), can overwrite or drift from DEFAULT_PREFERENCES | low | The hint shows only when no cookie exists, so BASE equals the defaults; a client component cannot import the runtime defaults (next/headers), noted in code. | rejected |
| 7 | Edge | Concurrent saves from hint and Settings reorder | low | Needs two tabs saving at once; last write wins, harmless. | rejected |
| 8 | Edge | Corrupt cookie: no hint, shortcuts Off | low | Safe default (Off); user can use Settings. | rejected |
| 9 | Blind, Edge | Hint failure announced only, no visible text | low | A save failure is unlikely; the hint stays so the user can retry. | rejected |
| 10 | Blind, Edge | Hint sits inside the scrolling main | low | Design placement; 17.2b may move it into the chrome. | rejected |
| 11 | Blind, Edge | Clicking the switch title no longer toggles it | low | Name via aria-labelledby; no requirement for a clickable title. | rejected |
| 12 | Blind | Density hint text not tied to the CSS tokens | low | Tokens are pinned by preferences.test and the hint test asserts 56 and 44. | rejected |
| 13 | Blind | Class-name-only tests for option cards, no real focus test | low | Same approach as the other primitives; axe is clean. | rejected |
| 14 | Blind | Palette rename: inconsistent verbs, no shortcut-toggle command | false | The spec names the command "Open Settings"; other commands are out of scope. | rejected |
| 15 | Blind | CardFooter `rounded-b-xl` hard-coded; empty error `<p>` reserves space | low | Card is `rounded-xl`; the spacer predates this story. | rejected |
| 16 | Edge, Gap | Turn on test does not assert shortcuts become true | false | The action is mocked in jsdom; the real re-render is Next's mechanism. | rejected |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.
