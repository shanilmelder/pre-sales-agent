---
title: 'Redesign the Estimate tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '8d1443233b2290e575b4eb285a1fec12021caa46'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3b-conflicts-estimate-trace-refit.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-overview-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Estimate tab (Stories 8.1–8.8, refit in 17.3b) does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Estimate). Its header is one neutral pill, a plain-text uncovered count and an Export menu; the grid shows Covers as a count, Role mix as text, conflicts as red text, no row tints, and a two-row footer.

**Approach:** Restyle the tab to the mockup's structure — toolbar, Version lifecycle card, uncovered banner, grouped grid card, Assumptions Register card, line inspector — using only data the API returns today, and move line editing from the grid into an "Edit line" form in the inspector. Polling, the edit server action (If-Match, reasons, failure handling), Assumption acceptance, selection, keyboard model and Export keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Toolbar** (one row, wraps): a version `Pill` "v{n}" with its status (Draft = primary tint, Superseded = neutral), "From Assessments (run {n})" in muted text when `source_run` is set, a spacer, then Export (outline button opening the existing `EstimateExport` menu). The building/rebuilding note stays under the toolbar.
- **Version lifecycle** (`Card`): an uppercase "Version lifecycle" label, a horizontal stepper Draft → Baseline → Superseded (circles with connecting lines; the current status filled primary with a ✓ on passed steps, others neutral), and one note line: draft — "v{n} is a draft built from {source}. Each edit needs a reason and is traced."; superseded — "v{n} is superseded and read only.". The uncarried-edits note moves under it.
- **Uncovered banner:** when `uncovered_count` > 0, an amber (`--gap-tint`/`--gap`) rounded banner with a triangle icon: "{n} Requirement(s) not covered by an Estimate line." No "Add line".
- **Grid card** (`Card`, overflow hidden, max-height scroll with sticky header and footer): header labels "Line · Covers · Role mix · Effort h · Cont. h · Total h"; section header rows uppercase, 12px semibold on `--background`; lines with title, then pills: red "Open Conflict" (alert icon, links to Conflicts as today), neutral "Edited, carried from v{n}" (pencil icon); Covers shows one small chip per Requirement label; Role mix is an 8px stacked bar (Engineer `--primary`, PM `--role-pm`, QA `--role-qa`, `aria-hidden`) above "E {e} · PM {p} · QA {q}"; numbers right-aligned, Total semibold. Conflict rows get `--blocker-tint` and a 3px red left edge; the selected row gets `--primary-tint` (selection wins). Subtotal rows muted on `--background`. One sticky footer row: "Total · v{n} · Engineer {e} h · PM {p} h · QA {q} h" (QA only when above zero) with the totals, Total in `--primary-text`. Unallocated contingency row stays.
- **Assumptions Register** (`Card` section): 16px semibold "Assumptions Register" heading, a red "{n} not accepted block submit" pill (alert icon) when `not_accepted` > 0, else green "All accepted". Rows: text, "{kind} · from Gap: {origin title}" muted, status ("Accepted by {name} · {date}" green with check icon, or red "Not accepted" with alert icon), Accept button; unaccepted rows red-tinted. Accept all, proposals and the Gap inspector keep their behaviour.
- **Line inspector:** "{section} · line {position}" over the title; uppercase section labels Basis, Role mix (bar + the existing Role/Share/Effort h table with colour squares), Covered Requirements (id chip + text), then the existing conflicts and edit history.
- **Edit line** (decision: editing moves to the inspector): the grid's Effort and Role mix cells become read-only (no `InlineInput`, `RoleMixEditor` or reason row in the grid). The inspector ends with an "Edit line" section: Effort (h) input, Engineer/PM/QA % inputs (must total 100, as `RoleMixEditor` validates today), a required "Reason for the change" textarea (prefilled from the remembered last reason as today), and a primary "Save" with the muted note "Each edit needs a reason and is traced." It calls the existing `editEstimateLine` with only the changed fields; Save is disabled until something changed and a reason is given. Stale (412), not-draft, forbidden and other failures show as an inline alert in that section with the existing wording; on success the grid and totals update and the line stays selected. Users without edit rights, and superseded versions, see no form.
- **Out-of-scope features** (decision 1a): version switcher, Diff, Set Baseline, uncovered ids/Add line, display ids, "Contingency linked to", agent confidence are left out; not logged.
- Use existing tokens and `ui/*` primitives; light and dark both work; every colour cue also has an icon or text.

**Never:** Show data the API lacks: version switcher or history, Diff, Set Baseline, uncovered Requirement ids, Add line, display ids (A2, L1), "Contingency linked to", agent/confidence pill, "Creates v3.1". Add any API call, backend change or new polling. Touch other tabs, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No Estimate | No version yet | Existing empty state, restyled as `EmptyTabCard` | N/A |
| Draft from run | v3 draft, run 2, 1 uncovered, L1 has a Conflict | Draft pill, "From Assessments (run 2)", amber banner, L1 red-tinted with "Open Conflict" | N/A |
| Superseded | Status superseded | Neutral pill, lifecycle on Superseded, note says read only; editing blocked as today | N/A |
| All accepted | `not_accepted` 0 | Green "All accepted" pill, no tints | N/A |
| Load fails | `getEstimate` not ok | Existing "could not be loaded" text | Unchanged |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `app/opportunities/[id]/estimate.tsx` -- composes the tab; keep `getEstimate` read and error text.
- `components/opportunities/estimate-grid.tsx` -- `EstimateHeader` (650–701) → toolbar + lifecycle + banner; `EstimateGrid` (211–640) row styling, Covers chips (replace `CoversChip` 93–101), role-mix bar, merged footer; `ConflictMarker` (158–192) and `EditedMarker` (142–154) → pills; `EstimateSection` (715–983) state, polling and edit wiring stay as is.
- `components/opportunities/estimate-inspector.tsx` -- header line, section labels, role bar, new Edit line section.
- `components/opportunities/estimate-line-edit.tsx` -- `RoleMixEditor` (29), `ReasonPrompt` (121), `onEscape`: reuse validation and reason handling in an inspector form; drop grid-only pieces. Server action `editEstimateLine` in `app/opportunities/actions.ts:2353` takes `effortHours`, `roleMix`, `reason`, `rowVersion` — unchanged. The edit callbacks/result handling now in `EstimateSection` pass down to the inspector via `RightPaneContent`.
- `components/opportunities/assumptions-register.tsx` -- card, summary pill, row layout.
- `components/opportunities/estimate-export.tsx` -- trigger styling only.
- `lib/estimates.ts` (+ test) -- `COLUMNS` labels; add pure helpers: lifecycle steps, version note, role-mix percentages, footer role label, register summary.
- Tokens: `--primary(-tint/-text)`, `--blocker(-tint)`, `--gap(-tint)`, `--resolved(-tint)`, `--neutral(-tint)`, `--role-pm`, `--role-qa`. Primitives: `ui/card`, `ui/pill`, `ui/chip`, `ui/button`, `ui/empty-tab-card`. Toggle pattern: `opportunity-views.tsx`.
- Tests: `estimate-grid.test.tsx` (~30 tests touch copy/markup: column labels, "Effort by role", version pill, markers, `CoversChip`, `data-subtotal`/`data-totals`/`data-role-totals`), `assumptions-register.test.tsx` (~6), `app/opportunities/pages.test.tsx` Estimate block. Keep `data-*` hooks where possible.

## Tasks & Acceptance

**Execution:**
- [x] `lib/estimates.ts` + test -- new helpers and labels
- [x] `components/opportunities/estimate-grid.tsx` -- toolbar, lifecycle, banner, grid and footer restyle
- [x] `components/opportunities/estimate-inspector.tsx`, `estimate-line-edit.tsx` -- inspector restyle and Edit line form; remove inline grid editing
- [x] `components/opportunities/assumptions-register.tsx` -- register card
- [x] `components/opportunities/estimate-export.tsx` -- outline trigger
- [x] tests -- update the three test files; one test per matrix row

**Acceptance Criteria:**
- Given the draft-from-run data, when the tab renders at 1440px, then it matches the mockup's order and styling in light and dark.
- Given a selected draft line, when Effort is changed in the inspector with a reason and saved, then the grid and totals update and the line stays selected.
- Given a stale line (412), when saved, then the inspector shows the stale alert and nothing changes.
- Given lint, typecheck, tests and build, when run in `web/`, then all pass.

## Implementation Notes

- Draft pill uses `Pill tone="agent"` (its tint and text equal `--primary-tint`/`--primary-text`); `Pill` has no primary tone and `ui/*` is out of scope.
- Lifecycle: the API has no Baseline status, so Baseline is never current or passed; a superseded version shows Draft passed, Baseline upcoming, Superseded current.
- The "All accepted"/"not accepted" pill shows only when the version has Assumptions; with none (e.g. while proposing) there is no pill.
- `e` on a focused line (with edit rights) now opens the line with focus in the inspector's Effort field. The inspector is keyed by version and line, so a new version drops an unsaved edit; when the form held changes, "A new Estimate version arrived; your change was not saved." shows above the grid.
- The Register's per-row "Gap" chip became a "from Gap: {title}" link button (same `data-gap-chip` and behaviour; its accessible name is its visible text). The old summary text ("7 · 6 accepted · 1 not accepted") is replaced by the pill; `registerSummary` stays for the live-region announcement.
- `acceptedLabel` now reads "Accepted by {name} · {date}". `uncoveredLabel`, `CoversChip`, `RoleMixEditor`, `ReasonPrompt` removed; `pill-migration.test.tsx` updated for `VersionPill`/`CoversChips`.
- Not done: the light/dark 1440px screenshot comparison (the mockup file is not in the repo and the app needs a signed-in stack).

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `editDirty` never reset when the form unmounts (blind, edge, verification) | medium | patch | No cleanup in `EditLineForm`'s dirty effect; `openGap` unmounts it, the next version shows a false "not saved" alert. |
| `dirty` compares raw text, not parsed values (blind, edge) | low | patch | "10" over "10.0": `dirty` true, `effortChanged` false; false alert, resync blocked. |
| Focus lost when Save disables itself while saving (blind) | low | patch | `disabled={!canSave}` includes `saving`; focus falls to body and stays. |
| Lifecycle shows Baseline passed for a superseded version (blind) | low | patch | `lifecycleSteps("superseded")` marks Baseline passed; the API has no Baseline, which the Never clause forbids showing. |
| Covers cell blank for a line with no Requirements (blind, edge) | low | patch | `CoversChips` maps an empty list to an empty span. |
| "from Gap" accessible name doesn't start with its visible text (blind) | low | patch | `aria-label="Gap: {title}"` vs visible "from Gap: {title}" (WCAG 2.5.3). |
| Section and form both named "Edit line" (blind) | low | patch | Both use `aria-labelledby={formId}`. |
| Replaced notice not cleared by opening a Gap (edge) | low | patch | Only `open()` calls `setReplaced(false)`. |
| No test saving Effort and Role mix together (verification) | low | patch | Pre-verified gap. |
| No test for no notice on a version change without edits (verification) | low | patch | Pre-verified gap. |
| `e` read-only test passes even if the inspector opened (verification) | low | patch | Pre-verified: it asserts only "no textbox". |
| Unsaved edits dropped silently on line/Gap switch (blind, edge) | low | rejected | Needs a confirm or per-line draft state (new branches); switching away is a deliberate act. |
| No Cancel/Reset/Esc in the form (blind, edge x2) | low | rejected | The spec's form is Save only (as the mockup); reselecting the line restores the stored values. |
| "was → will be" summary and rounding hint removed (blind, edge) | low | rejected | The grid shows the saved value immediately; the trace records before/after. |
| Reload resyncs before the reload returns (blind) | low | rejected | Only on a stale/replaced line, whose change cannot be saved anyway. |
| Hand-built alert with `data-slot="inline-alert"` (blind) | low | rejected | `InlineAlert` requires `onReload`; the markup matches it on purpose. |
| Announcement still uses `versionPillLabel` (blind) | false | rejected | The announced text names the version and run, which is correct; it is not shown text. |
| Copy: "built from a model draft", "block submit", "PM 0.0 h", abbreviations (blind) | low | rejected | "block submit" and the footer format are in the frozen spec; model drafts are legacy. |
| Spec claims matrix tests that don't exist (blind) | false | rejected | All five rows are covered and ran: grid tests 456, 1065, 1122; register 327; pages 1477. |
| Code Map line numbers stale (blind) | false | rejected | Fix is a spec edit. |
| Save in flight, then switching lines, loses the failure notice (edge x2) | low | rejected | Rare; the server result still updates the grid; guarding needs new state. |
| Poll brings a new `row_version` while dirty, so Save gives 412 (edge) | false | rejected | That is the intended If-Match protection, with the existing stale alert. |
| Effort-only edit blocked when stored mix ≠ 100 (edge) | false | rejected | The backend enforces `MIX_TOTAL = 100` (`domain/estimates.py:122`); a stored mix always sums to 100. |
| `e` while saving does not focus (edge) | low | rejected | Fields are disabled for under a second; rare. |
| No "All accepted" pill with zero Assumptions (edge) | low | rejected | Recorded choice: "All accepted" with nothing to accept (e.g. while proposing) would mislead. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare with the mockup.
