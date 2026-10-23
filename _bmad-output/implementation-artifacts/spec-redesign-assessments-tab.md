---
title: 'Redesign the Assessments tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '1b36e909bb3512d0f4a8ffa630034cc2c35f1efd'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3c-assessments-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Assessments tab (Story 17.3c) does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Assessments). It is a vertical stack of a small header, full-width task rows, tall per-agent cards, Effort comparison, and a separate Red Team section.

**Approach:** Rebuild the tab to the mockup's structure: a run header card, a run alert, an "Agent tasks" grid, a "Results so far" grid and one consolidated "Findings" table, with Red Team folded in as a fourth agent. Use only data the API returns today. Polling, SSE, retry, cancel, permissions, Finding selection and the inspectors keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Run header** (`Card`): an indigo icon tile, "Assessments", a run-status `Pill`, and "Started {time}" below. On the right, large tabular counters each sit above a label: "{done}/{total}" Complete, then Failed, Running, Queued and Skipped, each shown only when above zero. **Cancel run** (outline) is stacked over **Start new run** / **Run assessment** (primary), both gated by `can_start`. The counters cover the specialist tasks plus the Red Team task when a Red Team run exists.
- **Run alert:** for a failed, partially failed or cancelled run, an amber banner under the header says why it stopped and that completed results are kept.
- **Agent tasks:** a heading with a running/queued summary on the right, then a 3-column grid (1 column below `md`) of task cards. Each card has an icon tile, the name, the role, a status icon at top right, a **state bar**, the `TaskStatusPill`, the elapsed time, the note, and Retry. The state bar is full green when succeeded, an indeterminate indigo sweep while running (static under reduced motion), empty when queued or skipped, and full red when failed. It is decorative (`aria-hidden`) and shows no percentage. Borders follow the status: succeeded green, running indigo, failed red tint plus red border, others neutral. Keep `ul[aria-label="Agent progress"]` and `li[data-task-status]`.
- **Red Team folded in:** the Red Team run gets a task card (role "Argues integrations are harder and Requirements incomplete", Retry as today, no elapsed time because the API has no timestamps). The Red Team review gets a result card. Red Team Findings join the Findings table (Type = category label, Raised by "Red Team", Evidence = Requirement count plus Estimate line count) and open the existing Red Team inspector. The separate Red Team section is removed. Only one Finding is selected at a time across both sources, as today.
- **Results so far:** a 2-column grid of compact `Card role="article"` items, one per agent with an Assessment or review. Each shows the name, `v{n}`, the `RecommendationPill` (Red Team: a severity-count summary instead), the confidence label, the confidence basis as summary text, and up to 3 Requirement evidence `Chip`s. Specialist cards have a **Show effort** disclosure (button with `aria-expanded`) that reveals the existing per-Requirement effort table.
- **Findings:** one table with the columns Severity, Type, Finding, Raised by and Evidence, ranked from critical to low. A severity summary sits on the right of the heading, and critical rows get a red tint. It keeps the roving-tabindex keyboard model (j/k, arrows, Enter/Space).
- **Effort comparison** stays, below the Findings table, restyled only by its position.
- Use existing tokens and `ui/*` primitives only. Light and dark themes both work.

**Never:** Show data the API lacks: run number, starter, input versions, model chip, tokens, Run metrics, a percentage, "Waiting for you", Resolve or Skip. Change any API call, SSE or polling logic. Touch other tabs, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No run | No runs, no Assessments | No header card; **Run assessment** if `can_start`; "no Assessment" text | N/A |
| Running | 1 succeeded, 1 running, 1 queued; Red Team queued | "1/4 Complete", "1 Running", "2 Queued"; green, indigo and neutral cards | N/A |
| Failed | Run failed, 1 task failed | Amber alert; red card with Retry if `can_start`; "1 Failed" | Retry as today |
| Cancelled | Run cancelled | Alert says cancelled; no Retry | N/A |
| Mixed Findings | 2 specialist Findings + 1 Red Team Finding | 3 rows sorted by severity; a click opens the matching inspector | N/A |
| No Findings | Assessments with zero Findings | "No Findings." under the heading | N/A |
| Viewer | `can_start` false on both | No start, cancel or Retry | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/specialist-assessments.tsx` -- `SpecialistAssessmentsHeader` (547-639) becomes the run header with counters and alert. `AgentRunPanel` (414-498) becomes the task grid and accepts an extra Red Team task. `AssessmentCard` (304-360) becomes the compact result card with Show effort; `EffortTable` (249-300) is reused inside it. `AssessmentFindingList` (150-246) becomes the consolidated table (reuse its keyboard model). `SpecialistAssessmentsSection` (663-953) renders the whole tab body. Keep `TaskStatusPill`, `RecommendationPill`, `CancelRunButton` and `useNow`.
- `components/opportunities/red-team-list.tsx` -- extract `RedTeamSection` state, polling and retry (261-440) into a `useRedTeam(opportunityId, initial)` hook that the Assessments section consumes. Delete the section UI once it has no users; keep `CountChip` and its helpers if they are reused.
- `lib/assessments.ts` -- counters as value plus label (`taskCounters` 214), a merged and sorted findings helper (specialist and Red Team), run alert text, and the Red Team role. Reuse `agentRole`, `runStatusTone` and `failureReason`.
- `app/opportunities/[id]/assessments.tsx` -- pass `redTeam` into `SpecialistAssessmentsSection`; drop `<RedTeamSection>`; Effort comparison goes last.
- Reuse `ui/card`, `ui/pill`, `ui/chip`, `ui/button`, `SeverityPill`, `pillToneFor`, `AssessmentFindingInspector`, `red-team-inspector.tsx` and `useFindingSelection` (keys "red-team" and agent).
- Tests: `specialist-assessments.test.tsx`, `red-team-list.test.tsx` (move the behaviour tests onto the hook or the merged section), `app/opportunities/pages.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `lib/assessments.ts` + tests -- counters, merged findings, alert text, Red Team role
- [x] `red-team-list.tsx` + tests -- extract `useRedTeam`, keep the polling, retry and stall tests
- [x] `specialist-assessments.tsx` + tests -- header, alert, task grid with state bar, result cards with Show effort, findings table
- [x] `app/opportunities/[id]/assessments.tsx` + `pages.test.tsx` -- composition
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given a run with Assessments and a Red Team review, when the tab renders at 1440px, then it shows the header, alert (if any), Agent tasks, Results so far, Findings and Effort comparison, in the mockup's order and styling.
- Given a Red Team task that failed and `can_start`, when Retry is clicked, then the Red Team retry request fires as today.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- Selection uses one `useFindingSelection("assessments")` scope with composite keys (`red-team:<id>`, `<agent>:<id>`), so only one Finding is selected even outside a provider.
- The running state bar uses tw-animate-css (`animate-in slide-in-from-left-full repeat-infinite`), so no new keyframes or tokens. Under reduced motion, or once polling stalls, it shows a still, pale full-width bar.
- Evidence chips are deduplicated by Requirement label.
- `SpecialistAssessmentsHeader` is now the header card plus alert only. `AgentRunPanel` renders the task grid separately.
- If the Assessments read fails, the Red Team is not shown (only the failure sentences). It can no longer render on its own.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Red Team hidden when the Assessments read fails (blind, edge x2) | medium | patch | `assessments.tsx` renders only error text on that branch; the old `RedTeamSection` rendered independently. |
| Stalled queued Red Team shows "Waiting for the worker" (edge x3) | low | patch | Queued branch precedes `redStalled`; old `RedTeamHeader` showed STILL_REVIEWING for any reviewing status. |
| Red Team stall test deleted (blind) | low | patch | No test covers `redStalled` in `TaskCard`; added with the fix above. |
| Spinner beside "1 running" after polling stalls (blind) | low | patch | Icon renders regardless of `stalled`. |
| Show effort never reads "Hide effort" (blind) | low | patch | Text and aria-label are fixed. |
| Severity summary casing differs between Red Team card and Findings heading (blind) | low | patch | `countsLabel` vs `severitySummary`. |
| Evidence chip keys can collide (blind, edge) | low | patch | Dedupe by label, key by id. |
| Stale comments in `finding-selection.tsx`, long JSDoc line (blind) | low | patch | Comment names two sections that no longer exist. |
| No pane-close focus-return test (verification) | low | patch | Pre-verified: no test closes the pane on this tab. |
| No page test for Red Team read failing beside Assessments (verification, blind) | low | patch | Pre-verified: only the both-null case is tested. |
| Findings table rows have one gridcell, no column semantics (blind) | low | defer | Same structure as the pre-existing `AssessmentFindingList` and `RedTeamList`. |
| Header counters mix the Red Team run into the Assessment run (blind) | false | rejected | The frozen spec requires the counters to include the Red Team task. |
| Running state bar animates (blind) | false | rejected | The frozen spec asks for an indeterminate sweep, static under reduced motion. |
| No counters or alert when only a Red Team run exists (blind, edge x2) | low | rejected | The failed Red Team card shows the reason and Retry; adding a header path for it adds branches for a rare state. |
| Selected critical row loses its red tint; weak hover (blind) | low | rejected | The severity pill still marks it critical; selection taking precedence matches the other lists. |
| Module naming `red-team-list.tsx`, double-prefixed selection keys (blind) | false | rejected | No caller diverges; the keys are internal and unique. |
| Tests check concatenated text; `HeaderAndTasks` helper copies wiring (blind) | low | rejected | No demonstrated harm; the matrix tests render the real section. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare it with the mockup.
