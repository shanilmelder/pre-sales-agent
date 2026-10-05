---
title: 'Story 1.8 (demo slice): Overview summary — where the Opportunity stands at a glance'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '42e1d02d542ae4de062f8dd07e26687abd3e21c8'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/mockups/opportunity-overview.html'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Overview tab shows only the Opportunity's fields and collaborators. After the pipeline has run, nothing on the first screen says where the deal stands: how much input was read, how many Requirements and open Gaps there are, what the Estimate totals, what the agents recommend, or what needs attention. Stakeholders have to click through six tabs to see it.

**Approach:** Add a read-only summary to the Overview, following the mockup's layout and density: a **Needs attention** list, a **Pipeline** strip of counts, an **Estimate** card, an **Assessments** card and **Recent activity**, each linking to its tab. Web-only, built from the APIs the other tabs already use.

## Boundaries & Constraints

**Always:**
- **Web-only (decided):** no backend change, no migration, no new endpoint. The Overview server component reads, in parallel, what the tabs already read (`listSources`, `listRequirements`, `listGaps`, `getEstimate`, `getAssessments`, `getRedTeam`, `listTrace`). One failed read shows that card's own "could not be loaded" line; the rest still render. The existing fields and Collaborators stay, below the summary.
- **Refresh (decided):** rendered on navigation like the other tabs; no polling (the pipeline tabs keep their own live progress).
- **Needs attention (decided, read-only, not a gate):** up to 8 rows, most severe first, each with an icon plus label (never colour alone) and a link to its tab: critical and high Findings from the Red Team and the three specialist Assessments ("Red Team: <title>", "Security Agent: <title>"), open Gaps of high impact ("Open Gap: <title>"), and proposed Assumptions not yet accepted ("Unaccepted Assumption: <title> — <hours> h" where it has hours). "+N more" links to the tab when cut. Empty: "Nothing needs attention." It is titled **Needs attention**, not "Submission Blockers": no Submit and no blocking (Story 8.6 stays `[post-demo]`).
- **Pipeline strip:** Sources (parsed of total), Requirements (active count, by type), open Gaps (count, high-impact count), each linking to its tab; "—" when the step hasn't run.
- **Estimate card:** current version ("Estimate v{n}", draft), effort, contingency and total hours, and Assumptions accepted / not accepted, from the Estimate read model's server totals (never recalculated in the browser). Empty: "No Estimate yet."
- **Assessments card:** one line per agent (Engineering, PM, Security) with its recommendation pill and confidence, plus the Red Team's critical/high counts; the latest run's status when queued or running. Empty: "No assessment yet."
- **Recent activity:** the 5 newest trace events with time, actor and the existing event labels (`lib/trace.ts`), linking to the Trace tab.
- Numbers in tabular figures; headings and lists accessible, keyboard reachable, axe-clean; same content for every role that can read the Opportunity (sales representatives included).
- **Privacy:** no Requirement, Gap or Finding text in logs.

**Never:** No Submit or blocking, no live updates/SSE, no activity rail, no inline editing of title or date, no new backend query or aggregation endpoint, no change to other tabs. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh | New Opportunity, no sources | Pipeline shows "—"; Estimate "No Estimate yet."; Assessments "No assessment yet."; Needs attention "Nothing needs attention." | N/A |
| Full | Sources parsed, Requirements, Gaps, Estimate v2, Assessments, Red Team | Every card filled with the right counts and totals; links go to the matching tabs | N/A |
| Attention order | 1 critical Red Team Finding, 2 high Gaps, 1 unaccepted Assumption, 1 high Security Finding | Critical first, then high, then Assumptions; each row names its source | N/A |
| Cut | 12 attention items | 8 rows and "+4 more" | N/A |
| Partial failure | `getEstimate` fails | Estimate card says it could not be loaded; other cards render | Logged with status only |
| Running | Assessment run running | Assessments card shows the run status alongside current results | N/A |
| Who | Sales representative | Same read-only summary | N/A |

</frozen-after-approval>

## Code Map

- `web/src/app/opportunities/[id]/overview.tsx` — the Overview server component (fields, `Collaborators`); add the summary above, reading with `Promise.all`.
- `web/src/app/opportunities/data.ts` — `listSources` :100, `listRequirements` :118, `listGaps` :137, `getEstimate` :155, `getRedTeam` :173, `getAssessments` :191, `listTrace` :210 (all return `{kind: "ok" | "error"}`).
- Existing helpers to reuse, not re-implement: `lib/assessments.ts` (`agentLabel`, `recommendationInfo`, `confidenceLabel`, `runStatusLabel`, `isAssessing`), `lib/estimates.ts` (`hours`, totals already in the read model), `lib/trace.ts` (`EVENT_LABELS`, `subjectLabel`), `lib/red-team.ts`, the Gaps and Requirements label helpers in `lib/`, `components/opportunities/severity-pill.tsx`, `status-pill.tsx`, and `RecommendationPill` (exported from `components/opportunities/specialist-assessments.tsx`).
- Tab routes: the workspace tab links used by `components/opportunities/workspace-tabs.tsx` / `lib/workspace.ts`.
- Mockup: `opportunity-overview.html` lines 246-303 (Submission Blockers → our Needs attention, Estimate summary, Recent activity); spines win where they disagree.
- Tests: `web/src/app/opportunities/pages.test.tsx` (the `/opportunities/[id]` workspace tests mock `apiGet` per path, e.g. `foundWithRedTeam`); put pure derivations (attention ranking, counts) in a new `web/src/lib/overview.ts` with unit tests.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/overview.ts` (+ `overview.test.ts`) -- attention ranking/cut, pipeline counts -- pure, unit-tested
- [x] `web/src/components/opportunities/overview-summary.tsx` -- the five cards
- [x] `web/src/app/opportunities/[id]/overview.tsx` -- parallel reads, per-card failure, summary above the fields
- [x] `web/src/app/opportunities/pages.test.tsx` -- matrix rows with axe

**Acceptance Criteria:**
- Given the demo Opportunity after the pipeline has run, when the presales engineer opens it, then the Overview shows what needs attention, the pipeline counts, the Estimate totals and the agents' recommendations without opening another tab.
- Given CI, when it runs, then the web checks pass and the backend is unchanged.

## Implementation Notes

- Attention rank: critical Findings, then high Findings, then high-impact open Gaps, then unaccepted Assumptions (`accepted_at === null`); within a rank Red Team first, then Engineering, PM, Security. "+N more" links to the tab of the first cut item.
- When any of the four attention reads fails, the card lists what it has plus "Some items could not be loaded, so this list may be incomplete." (instead of "Nothing needs attention.").
- Pipeline "—" means: no Sources; no extraction and no Requirements; no detection and no Gaps. A failed read shows "—" plus "<Step> could not be loaded".
- Assessments card also shows "Red Team reviewing" while the Red Team run is queued/running. Hours use `hours()` (one decimal, e.g. "1452.0 h").
- Test helper `found()` in `pages.test.tsx` now answers the summary reads by path suffix (empty bodies by default; `null` = 500).

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-05; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | Pipeline shows 0 Requirements/Gaps while the first extraction/detection is queued, running or failed (blind, edge ×2) | medium | `requirementCounts`/`gapCounts` return 0 whenever the step record exists; the spec promises "—" before the step has run | patch: "—" with the step's status until it succeeds |
| 2 | VG: Pipeline, Assessments and Recent activity failure branches untested | medium | Pre-verified; only `/estimate` failure is tested | patch: tests |
| 3 | VG: "may be incomplete" warning untested for Gaps/Findings reads and the empty-list case | medium | Pre-verified | patch: test |
| 4 | VG: "Red Team reviewing" never tested | low | Pre-verified | patch: test |
| 5 | "+N more" links to one tab when cut items span several (blind, edge) | low | `cutAttention` uses the first cut item's tab | patch: link only when all share a tab |
| 6 | Sources "2 of 3 parsed" hides failures (blind) | low | Only parsed vs not | patch: failed count |
| 7 | Estimate status shows raw "draft" (blind) | low | Existing label helper not reused | patch |
| 8 | Assumption rows red like critical Findings; label repeats the row text (blind) | low | `ATTENTION_DISPLAY` | patch: amber tone, no duplicate prefix |
| 9 | Truncated text unreadable; count badge is a bare number (blind) | low | `truncate` without `title`; no accessible name | patch |
| 10 | Cut, Partial failure and Running tests skip axe (edge claim) | low | Spec asks for axe on the matrix rows | patch |
| 11 | Overview waits for the slowest of seven reads; reads start after `getOpportunity` (blind, edge) | low | Same pattern as the other tabs; access is checked first | reject |
| 12 | Recent activity fetches a 50-event page to show 5 (blind) | low | `listTrace` has no page-size option; one extra read | reject |
| 13 | Failed parses and failed or cancelled runs don't appear in Needs attention (blind) | low | Items were defined in the intent; #1 and #6 now show failures in the Pipeline | reject |
| 14 | `tabLabel` non-null assertion (blind) | low | Slugs are internal constants | reject |
| 15 | `subjectLabel`, `SeverityPill`, `StatusPill` not reused (blind) | low | Equivalent icon + label rendering | reject |
| 16 | "Who" test asserts a button the Overview never has (VG other) | low | The real coverage is the row and total checks | reject |
| 17 | Failed Pipeline stat's link name repeats the label (blind) | low | Cosmetic for screen readers | reject |
| 18 | Spec out of date (blind) | false | Filled during review | reject |

## Verification

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
- `git diff --stat -- backend` -- expected: empty (backend unchanged)
