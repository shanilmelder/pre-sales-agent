---
title: 'Story 17.3c: Assessments run header, counters and per-agent cards'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: 'e3faa5abc668596fe1c5c68920c6f8a84c788e41'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3b-conflicts-estimate-trace-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Assessments tab shows the run as a bare status line and unboxed progress rows, hand-rolls its `rounded-md border` assessment boxes and action buttons, and has no run header, counters or agent role descriptions (Story 17.3, UX-DR8, UX-DR10, UX-DR20).

**Approach:** Add a run header and task counters, turn the progress rows and assessment boxes into cards, show each agent's role description, and use the shared `Button`. Use only data the API already returns. Behaviour, polling, permissions and the cancel dialog do not change.

## Boundaries & Constraints

**Always:**
- **Run header** (a `Card`): title "Assessments", the run status as a `Pill`, and "Started" with the run's `queued_at` date and time (fall back to `created_at`). No run number, starter, input versions or model chip: the API lacks them (logged as a backend ticket).
- **Counters**, derived from `run.tasks`: "{done}/{total} Complete", then Running, Queued, Failed and Skipped, each shown only when above zero. No "Waiting for you".
- **Agent cards:** each task row becomes a `Card` with the agent name, a one-line role description from new constants in `lib/assessments.ts` (Engineering: "Feasibility, architecture and per-integration effort"; PM: "Delivery approach, phases and customer dependencies"; Security: "Mandatory controls and the effort they need"), the status pill, elapsed time and note, and Retry as today. The `ul[aria-label="Agent progress"]` and `li[data-task-status]` stay. Progress is the status pill plus elapsed time; no percentage.
- Each Assessment box becomes a `Card` that keeps `role="article"` and its `aria-labelledby`.
- **Buttons:** the start button and **Cancel run** use `ui/button`. The start button reads **Run assessment** with no run and **Start new run** once a run exists. Keep the cancel dialog, permission gating (`can_start`), disabled states and focus handling.

**Never:** Add an empty-tab card or a 412 alert (the tab has neither). Touch Estimate, Conflicts, Trace, Overview, Red Team, the shell, tokens or `ui/*`. Change any API call, SSE, polling, stall or retry logic. Fetch the agent registry.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No run | `run === null` | No header card; **Run assessment** (if `can_start`); existing "no Assessment" text | N/A |
| Running | 3 tasks: 1 done, 1 running, 1 queued | Header "Assessments", status pill, "1/3 Complete", "1 Running", "1 Queued"; one card per agent | N/A |
| Partly failed | 1 failed task, run over, `can_start` | Failed card shows Retry; "1 Failed" counter; **Start new run** shown | Retry as today |
| Cancelled | Run cancelled | Status pill reads cancelled; no Retry | N/A |
| Viewer cannot start | `can_start` false | Header and counters shown; no start, cancel or Retry buttons | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/specialist-assessments.tsx` -- `SpecialistAssessmentsHeader` (~537-610) gets the header card, status pill and counters; `AgentRunPanel` (~414-488) rows become cards; `AssessmentCard` (~301-360, box at ~319) becomes `Card`; `actionClass` (~95) and the cancel trigger (~505) move to `ui/button`. `AgentRunPanel` is used only here.
- `lib/assessments.ts` -- add `AGENT_ROLES` (or equivalent beside `AGENTS`), counter helper, `START_NEW_RUN`; reuse `runStatusLabel`, `isAssessing`, `taskElapsed`.
- Reuse `ui/card`, `ui/button`, `ui/pill` (`pillToneFor`), `TaskStatusPill`.
- Tests: `specialist-assessments.test.tsx` (`Agent progress` list ~212, article roles ~302-348, `min-h-row` ~327, "Run assessment" buttons ~295-1291, header tests ~895-1030), `app/opportunities/pages.test.tsx:981,1227,1445`.

## Tasks & Acceptance

**Execution:**
- [x] `lib/assessments.ts` + tests -- role descriptions, counters, start label
- [x] `specialist-assessments.tsx` + tests -- header card, counters, agent cards, assessment `Card`, shared buttons
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given a run with tasks, when the tab renders, then it shows the header, the counters and one card per agent with its role description and status pill.
- Given a viewer without `can_start`, when the tab renders, then no start, cancel or Retry button shows.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `runStatusTone` has no test | low | patch | Added a table-driven test over every run status. |
| Counters show "0/0 Complete" for a run with no tasks | low | patch | Counters list now renders only when the run has tasks. |
| Fixed `w-64` name block can overflow a narrow pane | low | patch | Added `max-w-full`. |
| `taskCounters` misses unlisted task statuses | false | rejected | The API's task status enum is exactly the five counted. |
| Disabled "Start new run" while a run is active | low | rejected | The spec fixes the label once a run exists; the button was already disabled while assessing. |
| Started time falls back with no test, or shows an invalid date if both are empty | low | rejected | `created_at` is always set; the fix is a fixture tweak with no demonstrated harm. |
| `Card` and `Pill` might not forward `role`, `aria-labelledby`, `data-status` | false | rejected | Existing article-role and `data-status` tests pass. |
| Empty role span for an unknown agent | false | rejected | `AGENT_ROLES` covers every agent in the API enum. |
| Counter live region, heading levels, `formatDateTime` in `lib/sources`, import order, hardcoded counter words | low | rejected | Cosmetic or pre-existing; no demonstrated harm. |
| `pages.test.tsx` may query the old label | false | rejected | Those tests pass unchanged. |
