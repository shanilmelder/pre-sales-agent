---
title: 'Story 5.3 (demo slice): effort comparison — the agents'' hours per Requirement next to the Estimate'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '93b5666fdbd3831a5550dc87e71b2a7b2ba4f4b0'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Each specialist agent shows only its own effort table, and the Estimate has its own hours, so nobody can see on screen that the Engineering, PM and Security hours add up (they size different work) or where the agents' view of a Requirement differs from what the Estimate allows for it.

**Approach:** An **Effort comparison** table shows, per active Requirement, the Engineering, PM and Security hours, their sum, and the Estimate's hours for that Requirement, with totals. Read-only, web-only, built from the data the Assessments and Estimate tabs already load.

## Boundaries & Constraints

**Always:**
- **Web-only (decided):** no backend change, no migration, no new endpoint. Reads `getAssessments`, `getEstimate` and `listRequirements` (already used by the tabs). The comparison is display arithmetic only; it never changes the Estimate, whose own totals stay server-calculated.
- **Estimate attribution (decided):** even split. Each Estimate line's effort hours are divided equally among the Requirements it covers (only those still active); a Requirement's Estimate hours are the sum of its shares. The column is headed **Estimate (allocated)**, with the note "A line covering several Requirements is shared equally between them." Lines covering no active Requirement count only in the totals row's "Not linked to a Requirement" figure.
- **Placement (decided):** Assessments tab, a section between Specialist Assessments and the Red Team (shares the tab's existing loads).
- **Rows:** one per active Requirement in Requirement order (`R1…Rn`, label and excerpt), columns Engineering / PM / Security (each agent's current Assessment effort for that Requirement, "—" when it has none), **Agents total** (sum of the three), **Estimate (allocated)**, and **Difference** (Estimate − Agents total, signed, only when both exist). A totals row sums each column. Hours to 0.1 in tabular figures.
- Rows for Requirements no longer active (effort cited a superseded version) are left out; a note says how many agent effort rows were left out.
- Header note: "Engineering, PM and Security size different work, so their hours add up."
- Empty: "No effort to compare yet." when no agent has effort and there is no Estimate.
- Accessible table (caption, column headers, row headers), keyboard reachable, axe-clean; same for every role that can read the Opportunity.

**Never:** No editing hours, no writing agent hours into the Estimate (Story 8.3 stays `[post-demo]`), no reconciliation or "winner", no per-role split, no charts, no backend aggregation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Full | R1: Eng 20, PM 10, Sec 4; Estimate attributes 30 h to R1 | Agents total 34; Estimate 30; Difference −4 | N/A |
| Shared line | A 40 h line covers R1 and R2; a 10 h line covers R2 only | R1 Estimate 20; R2 Estimate 30 | N/A |
| Unlinked line | A 12 h line covers no active Requirement | Not in any row; totals row shows "Not linked to a Requirement: 12 h" | N/A |
| Missing agent | Security has no effort for R2 | Security "—"; Agents total of the other two | N/A |
| No Estimate | Agents' effort, no Estimate yet | Estimate and Difference "—"; agents' totals shown | N/A |
| No Assessments | Estimate only | Agent columns "—"; Estimate column filled | N/A |
| Superseded | An agent's effort cites a superseded Requirement | Row left out; note "1 effort row for Requirements no longer active is not shown" | N/A |
| Empty | Neither | "No effort to compare yet." | N/A |
| Partial failure | `getEstimate` fails | Table renders without the Estimate columns and says the Estimate could not be loaded | Logged with status only |

</frozen-after-approval>

## Code Map

- `web/src/app/opportunities/data.ts`: `getAssessments` :191 (per agent `effort: [{requirement: {id, version, label, excerpt}, hours, basis}]`, `total_hours`), `getEstimate` :155 (sections → `lines[]` with `effort_hours` and `requirements: [{id, version, label, excerpt}]`), `listRequirements` :118 (active Requirements and their order).
- `web/src/app/opportunities/[id]/assessments.tsx` (server component: `FindingSelectionProvider` with Specialist Assessments above Red Team); add `getEstimate` and `listRequirements` to its `Promise.all` and place the section between the two.
- Reuse `lib/estimates.ts` `hours` (formatting), `lib/assessments.ts` `agentLabel`/`AGENTS`. Put the arithmetic (attribution, sums, differences, superseded count) in a new pure `web/src/lib/effort-comparison.ts` with unit tests; the component only renders.
- Tests: `web/src/app/opportunities/pages.test.tsx` (workspace tab tests mock `apiGet` per path) for placement and partial failure; component tests with axe.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/effort-comparison.ts` (+ tests) -- attribution, sums, difference, superseded count
- [x] `web/src/components/opportunities/effort-comparison.tsx` (+ tests with axe) -- the table, notes, empty and error states
- [x] the tab server component(s) -- load and place the section
- [x] `web/src/app/opportunities/pages.test.tsx` -- placement and partial failure

**Acceptance Criteria:**
- Given the demo Opportunity after the agents and the Estimate have run, when the presales engineer opens the comparison, then each Requirement shows the three agents' hours, their total and the Estimate's hours side by side, with totals.
- Given CI, when it runs, then the web checks pass and the backend is unchanged.

## Implementation Notes

- "Active" is matched by Requirement id against `listRequirements` (as the server labels chips "Superseded"); an edited Requirement keeps its id and stays in its row.
- When an Estimate exists, a Requirement no line covers is allocated 0.0 h (so its Difference shows); "—" only when there is no Estimate.
- The totals row sums each hours column (unrounded, then shown to 0.1); every Difference, including the totals', is the shown Estimate minus the shown Agents total. A note under the table gives the Estimate's full effort ("Estimate effort: X h in total (Y h not linked to a Requirement)") and the column note names the version compared ("Estimate v{n}.").
- Requirement list items carry no server label or number, so rows are labelled `R{index+1}` in list order (the server numbers chips from the same ordered query).
- "No effort to compare yet." shows only when the Estimate was read (a failed read may hide one), and never together with the left-out note.
- Excerpts are cut from the Requirement text in the web, mirroring the server's 140-code-point `excerpt`.
- A failed Requirements or Assessments read shows "The Effort comparison could not be loaded."; a failed Estimate read drops the Estimate (allocated) and Difference columns with a note.
- The section renders from the tab's server reads; when a run the Specialist Assessments section was polling finishes, that section calls `router.refresh()` once so the comparison re-renders with the results.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | Totals Difference is the sum of row differences, so the Total row doesn't add up on screen (blind) | medium | Lib test: Agents 6.0, Estimate 10.0, Difference −6.0 | patch: Estimate total − Agents total |
| 2 | Comparison doesn't refresh when a run finishes while the tab is open (blind) | medium | Built from page-load reads; 5.1 makes a run in progress likely at demo time | patch: `router.refresh()` when the polled run finishes |
| 3 | VG: tab never tests a failed Requirements or Assessments read | medium | Pre-verified | patch: tests |
| 4 | "No effort to compare yet." when the Estimate failed to load (blind, edge) | low | `estimate: null` makes `empty` true | patch |
| 5 | Empty state and left-out note contradict each other (blind) | low | Note rendered outside the empty branch | patch |
| 6 | Allocated Estimate total differs from the Estimate tab's effort total; version not named (blind) | low | Unlinked hours only in a sub-line | patch: total note and version |
| 7 | Row Difference from unrounded values can be 0.1 off the shown cells (edge) | low | `.x5` ties | patch: from shown values |
| 8 | Row labels recomputed in the browser can drift from the server's chip labels (blind, edge) | low | `R${index + 1}` | patch: use the server label if the list has one |
| 9 | Rows don't sum to the total after rounding (blind) | low | Noted in the spec; 0.1 h | reject |
| 10 | Untested: duplicate effort rows, duplicate line ids, multi-section Estimates (blind) | low | Agents' validation drops duplicate effort rows; dedupe and sections are simple loops | reject |
| 11 | "—" read as "em dash" by screen readers (blind) | low | Axe-clean; cosmetic | reject |
| 12 | Fixed DOM ids could collide if the section is rendered twice (blind) | low | Rendered once | reject |
| 13 | Requirements may change between the four reads (edge) | low | Narrow window; the next load corrects it | reject |
| 14 | Spec status lags (blind) | false | Filled during review | reject |

## Verification

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
- `git diff --stat -- backend` -- expected: empty (backend unchanged)
