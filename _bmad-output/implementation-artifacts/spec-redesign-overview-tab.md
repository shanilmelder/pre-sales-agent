---
title: 'Redesign the Overview tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'c4cd95f8c65501fae00258a982ab48108f0b0193'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-8-overview-summary.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-assessments-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Overview tab (Story 1.8) does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Overview). It is a stack of thin bordered boxes (Needs attention, Pipeline, Estimate, Assessments, Recent activity) above a plain field list and Collaborators.

**Approach:** Rebuild the tab body to the mockup's layout: a row of 4 KPI cards, then two 1.4fr/1fr rows (Submission pipeline + Needs you, Submission blockers + Recent activity), then Latest agent decision and Agent run. Everything is derived from the reads the tab already makes; still server-rendered with no polling, and each card still stands alone when its read fails.

## Boundaries & Constraints

**Always:**
- **Cards** use `ui/card` styling (surface, border, 12px radius, shadow) with a 16px-semibold header row and a bottom border, as in the mockup. Gaps of 16px; the page keeps `PAGE_PADDING` and 24px between rows. Grids collapse to 1 column below `lg` (KPIs: 2 columns at `sm`, 4 at `xl`).
- **KPI row:** (1) *Requirements confirmed* — "{confirmed} of {active}", a green progress bar (`aria-hidden`), "{n} awaiting confirmation". (2) *Open Gaps* — count, then High (red, alert icon) and Medium (amber) pills shown only when above zero, then "{n} Low". (3) *Open Conflicts* — unresolved count, a red "Needs a decision" pill when above zero, and "{n} escalated" when any. (4) *Estimate · v{n}* — total hours with a small "h", "Engineer {e} h · PM {p} h" (plus QA when above zero) from `totals.role_hours`, and "From Assessments run {n}" when `source_run` is set. Each tile links to its tab. Before a step has run, the value is "—" with the existing step status text.
- **Submission pipeline:** a vertical stepper of 7 steps — Sources added, Requirements extracted, Requirements confirmed, Gaps answered, Assessments run, Conflicts resolved, Estimate accepted — each with a numbered (✓ when done) circle, a connecting line, title, sub-line, and a status pill: Complete (green), In progress (indigo), Blocked (red), Not started (neutral). Header right: "Proposal due in {n} days" (reuse the `DueCountdown` day math). Footer: "{done} of 7 steps complete", "{n} blocked" and a segmented green/indigo/red bar (`aria-hidden`).
- **Needs you:** the existing `attentionItems` (same ranking and 8-row cut, "+N more"), each row an icon, title, a coloured state line (Critical/High/Escalated/High impact/Not accepted) and an outline action link (Resolve / Review / Open) to its tab; critical rows get a red tint. Header pill: "{n} items". Footer: "In your queue {n}". Empty and incomplete texts stay.
- **Submission blockers** (decision: derived checklist): red-tinted rows for open Gaps (with impact breakdown), unresolved Conflicts, uncovered Requirements (`uncovered_count` of the current Estimate Version) and unaccepted Assumptions, each shown only when above zero, with an alert icon, title, meta text and a link to its tab. Header pill "{n} blockers" (red), or green "0 blockers" with the mockup's ready state ("0 blockers · ready to submit"). No Baseline group. A failed read adds "could not be loaded" instead of a ready state.
- **Recent activity:** the 5 newest trace events; each has an initials tile (rounded square for agents and system, circle for users; indigo tint, green for users), the event in words, and "{actor} · {relative time}". Header link "Open Trace".
- **Latest agent decision:** from the newest specialist Assessment. Header pill with the agent name. Left: an indigo callout with its most severe Finding's title, "Reasoning" with the Finding detail and the confidence basis as check-marked lines, and up to 3 Requirement evidence chips. Right: the `RecommendationPill`, a confidence pill and an "Open Assessments" link. Hidden when there is no Assessment.
- **Agent run:** shown when an Assessment run exists. Header: "Agent run", "Assessments · started {time} · {done} of {total} tasks complete", and "Open Assessments" (outline link, not Cancel). A 3-column grid of compact task cards: icon tile, agent name, `TaskStatusPill`, the skip/failure note.
- **Details** (decision: keep): one "Details" card at the bottom with Status, Customer, Products in scope, Industry and Created as a 2-column list, and the existing `Collaborators` component inside it (behaviour unchanged).
- Use existing tokens, `ui/*` primitives and pills; light and dark themes both work. Every colour cue has an icon or text too.

**Never:** Show data the API lacks: "Resolved today", "Proposed next steps", "Approve question", Baseline gate or review steps, run numbers, token counts. Add polling, SSE or any new API call or backend change. Touch other tabs, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New Opportunity | No Sources, nothing run | KPIs "—"; pipeline all Not started; "Nothing needs attention."; no decision or run card | N/A |
| Mid-way | 6 Sources parsed, 9 of 12 confirmed, 3 open Gaps (2 High), 2 open Conflicts, Estimate v3 draft | Matches the mockup numbers; steps 1–2 Complete, 3 In progress, 4 and 6 Blocked | N/A |
| Read fails | Gaps read is null | Open Gaps KPI and its step say "could not be loaded"; other cards render | Per-card message |
| Overdue | Proposal date in the past | Pipeline header says "Overdue by {n} days" in red | N/A |
| Run in progress | 1 of 3 tasks succeeded | Agent run "1 of 3 tasks complete"; task pills match | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `app/opportunities/[id]/overview.tsx` -- `OverviewTab` composes the page; `loadSummary` already reads Sources, Requirements, Gaps, Estimate, Assessments, Red Team, Trace (page 1) and Conflicts. Pass `opportunity` (for `target_proposal_date`) and `today` into the summary. `Detail`, `Collaborators` and `GapsLiveRefresh` stay.
- `components/opportunities/overview-summary.tsx` -- rewrite: `KpiRow`, `SubmissionPipeline`, `NeedsYou` (replaces `NeedsAttention`, keeps `ATTENTION_DISPLAY`), `SubmissionBlockers`, `RecentActivity`, `LatestDecision`, `AgentRun`. Drop `Pipeline`, `EstimateCard`, `AssessmentsCard`, `Stat`.
- `lib/overview.ts` (+ `lib/overview.test.ts`) -- keep `attentionItems`, `cutAttention`, `sourceCounts`, `requirementCounts`, `gapCounts`, `couldNotLoad`, `NOT_RUN`. Add pure helpers: confirmed counts (use `unconfirmed` from `lib/requirements.ts`), gap counts by impact, unresolved/escalated conflict counts (`isUnresolved` in `lib/conflicts.ts`), `pipelineSteps(data)` returning `{title, sub, state}[]`, `blockers(data)`, role-hours label, `latestDecision(assessments)`, actor initials. Remove helpers left unused.
- `components/opportunities/header-parts.tsx` -- reuse `DueCountdown`'s day math (export a `daysUntil` helper if needed; no visual change to the header).
- `components/opportunities/specialist-assessments.tsx` -- export `TaskStatusPill` for the Agent run card; reuse `RecommendationPill`. No behaviour change.
- Reuse: `lib/assessments.ts` (`agentLabel`, `confidenceLabel`, `skipNote`, `evidenceLabels`, `runStatusLabel`), `lib/estimates.ts` (`hours`, `versionStatusLabel`), `lib/trace.ts` (`eventLabel`, `relativeTime`, `absoluteTime`), `lib/workspace.ts` (`tabHref`), `ui/card`, `ui/pill`, `ui/chip`, `ui/button`.
- Tests: `lib/overview.test.ts`, `app/opportunities/pages.test.tsx` ("Overview summary" block, line ~587).

## Tasks & Acceptance

**Execution:**
- [x] `lib/overview.ts` + `lib/overview.test.ts` -- new derivations; prune dead helpers
- [x] `components/opportunities/specialist-assessments.tsx`, `header-parts.tsx` -- export `TaskStatusPill` / day helper
- [x] `components/opportunities/overview-summary.tsx` -- the seven cards
- [x] `app/opportunities/[id]/overview.tsx` -- composition, Details card
- [x] `app/opportunities/pages.test.tsx` -- update the Overview block; add a test per matrix row

**Acceptance Criteria:**
- Given the mid-way data, when the tab renders at 1440px, then the cards appear in the mockup's order and grid, in light and dark.
- Given any Needs you row or KPI tile, when activated, then it navigates to its tab.
- Given lint, typecheck, tests and build, when run in `web/`, then all pass.

## Implementation Notes

- `daysUntil` was already exported from `lib/opportunities.ts`, so `header-parts.tsx` is unchanged. The pipeline header uses a new `dueLabel(days)` in `lib/overview.ts`.
- `OverviewData` is now `OverviewReads` in `lib/overview.ts`; the component re-exports it under the old name.
- Pipeline states, from the reads alone. Sources: Blocked if any parse failed, In progress while any is pending. Extraction and Detection: In progress while running, Blocked if they failed with nothing found. Confirmed: Not started at 0 confirmed. Gaps: Blocked while any is open. Assessments: Blocked when the run failed, partly failed or was cancelled; the sub-line is `runStatusLabel`. Conflicts: Not started until an Assessment exists. Estimate: Blocked while any Assumption is not accepted.
- A step whose read failed gets a neutral "Unknown" pill and the "could not be loaded" sub-line. The spec lists only four pill states, and "Not started" would be wrong here.
- Submission blockers: the green ready state appears only when an Estimate Version exists. With nothing blocking and no Estimate, the card shows a neutral "0 blockers" pill and "Nothing blocks yet. Blockers appear as the pipeline runs."
- Needs you actions: Findings → Review, escalated Conflicts and high-impact Gaps → Resolve, Assumptions → Open. Each link's accessible name is "<action> <row title>".
- Agent run counts the specialist tasks only (no Red Team task), and the start time uses `formatDateTime`.
- Removed helpers that are no longer used: `byTypeLabel`, `highImpactLabel`, `sentQuestionsLabel`, `estimateTitle`, `noAssessmentYet`, `criticalHighLabel`, `NO_ASSESSMENT_YET`. Also removed the `sent`/`awaiting` Gap counts and the per-type Requirement counts.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| "Estimate accepted" Complete while `uncovered_count` > 0 (blind, edge) | medium | patch | `estimateStep` checks only `counts.not_accepted`; the Blockers card lists the uncovered Requirements for the same version. |
| Blockers pill says "0 blockers" when a read failed (blind) | low | patch | `total` is 0 and the pill renders neutral "0 blockers" beside the could-not-load line. |
| "Conflicts resolved" Complete while the first run is still assessing (edge) | low | patch | `conflictsStep` returns Complete once `assessmentsStarted` and there are no Conflicts, even while the run is queued/running. Met on every first run. |
| No test for a failed Conflicts/Estimate read blocking "ready" (verification) | low | patch | Pre-verified: only `gaps: null` is covered. |
| No test for `attentionIncomplete` with Red Team / Assessments null (verification) | low | patch | Pre-verified: the old tests that pinned it were deleted. |
| No test for failed Sources/Requirements reads in the KPI and steps (verification) | low | patch | Pre-verified: the "Partial failure: Sources" test was deleted with no replacement. |
| Import order, trailing blank line, `SEVERITY_RANK` typed as `string`, `actorInitials` doc example (blind) | low | patch | Direct corrections in `overview-summary.tsx` and `lib/overview.ts`. |
| "Ready" while unconfirmed Requirements, Critical Findings or a draft Estimate remain (blind) | false | rejected | The frozen decision defines the blockers as open Gaps, unresolved Conflicts, uncovered Requirements and unaccepted Assumptions; `VersionStatus` is only draft or superseded, so "draft" is no signal. |
| Questions-sent line, by-type counts, Effort/Contingency, Red Team row removed (blind, edge, verification) | low | rejected | The intent rebuilds the tab to the mockup, whose KPI and card content the frozen block lists; the Red Team still feeds Needs you. Called out to the user. |
| A running or failed Red Team review is invisible (blind, edge) | low | rejected | The frozen Agent run covers the Assessment run; adding a Red Team path adds branches. Called out to the user. |
| Sources tab not linked from the summary (blind, edge) | low | rejected | The workspace tab bar always links Sources; linking the steps adds a surface the spec does not ask for. |
| "Needs you" / "In your queue" wording for viewers who cannot act; due date shown twice (blind) | false | rejected | Both are required by the frozen block. |
| Agent run "started" uses `created_at`; card stays after the run ends (blind) | false | rejected | `AssessmentRun` has no started time; the Assessments tab uses `created_at` the same way; the frozen block shows the card whenever a run exists. |
| `conflicts` optional, undefined treated two ways (blind) | low | rejected | The one caller (`loadSummary`) always sets it; no user-facing path. |
| Ready claimed when Gap detection failed or is running, or a run is assessing (edge x2) | low | rejected | Rare (needs an Estimate Version without detected Gaps); the fix adds branches. |
| Cancelled run shown as Blocked (edge) | low | rejected | A cancelled run left Assessments incomplete; the Assessments tab also shows an alert for it. |
| Finished run with skipped tasks reads "2 of 3 complete" (edge) | false | rejected | Same counting as the Assessments tab header (`taskCounters` counts succeeded only). |
| Conflicts KPI "—" when the Assessments read fails; card isolation claim (edge x2) | low | rejected | Rare double condition; "—" is the step's not-started state, no wrong number shown. |
| Unparseable `created_at` picks a stale decision (edge) | false | rejected | API timestamps are ISO datetimes from the server. |
| No `header-parts.tsx` hunk (edge) | false | rejected | Implementation Notes record that `daysUntil` already existed in `lib/opportunities.ts`. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare it with the mockup.
