---
title: 'Story 10.4: Drill down from variance to the failed Assumption'
type: 'feature'
created: '2026-10-27'
status: 'done'
baseline_commit: '56a196953714557f3eed36aadfbd10030389281e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-3-variance-reporting-views-and-the-reports-table.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-9-trace-and-compare.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Reports (10.3) shows that a group overran and how many Assumptions failed, but it is a dead end. Opportunity rows open the Overview. The Actuals tab ignores the URL. The Actual Inspector lists failed Assumptions as bare wording. Trace can't be filtered to an Assumption, and its events never show the Actual that recorded the failure. So the Head of Delivery can't find out why a project overran without asking someone (FR-50, UJ-5).

**Approach:** Build the three-navigation path Reports row → Actuals tab (sorted by variance, Integration Type kept) → select line → Inspector "Failed Assumptions" → **Open in Trace**. Add a failed-Assumption list per Reports group. Extend Assumption lineage and the trace filter so the chain ends with the Actual. Follow the new mockup's patterns: the Inspector section eyebrow, the Assumption row "Accepted by {name} · {date}", the Evidence chip, the Reports table and the Trace filter chip. The mockup draws no dedicated drill-down screen.

## Boundaries & Constraints

**Always:**
- **Reports → Actuals:** an Opportunity row's title opens `/opportunities/{id}/actuals?sort=variance_desc`. When the report is grouped by Integration Type, the link also carries `&integration_type={group key}`; the "No Integration Type" group carries `none`. The expanded row's main-cause link uses the same href.
- **Reports filter:** `GET /reports/estimate-vs-actual` also accepts `integration_type_id` (kept in the URL params, like the other filters).
- **Actuals tab:**
  - It reads `sort=variance_desc|variance_asc` to seed the existing sort state.
  - It reads `integration_type` and filters lines client-side on `ActualsLine.integration_types`. Totals stay server values.
  - The filter shows as a removable dashed chip "Integration Type: {name}", following the mockup's Trace filter chip.
  - Highest variance comes first; unrecorded lines stay last.
- **Inspector "Failed Assumptions"** (read-only, for every role; the DM checkbox form stays):
  - one row per failed Assumption:
    - the kind icon (`ClipboardCheckIcon` for a Condition, `ShieldPlusIcon` for a Contingency, `aria-hidden`) and a "Condition · A{n}" label;
    - the wording, or for a Contingency "{h} h · wording";
    - "Accepted by {name} · {date}", or "Not accepted";
    - Evidence chips (the lineage chip style);
    - **Open in Trace** → `/opportunities/{id}/trace?subject=estimates.assumption&subject_id={assumption_id}`.
  - These fields come from the server: `FailedAssumption` gains `position`, `amount_hours`, `accepted_by`, `accepted_at` and `evidence` through `estimates.public`.
- **Lineage:** `AssumptionLineage` gains steps of kind `actual`, one per current-or-past Actual version whose `failed_assumptions` cite the Assumption: line label, kind, effort, cause, actor and time. They are read from `actuals.actual.recorded`/`.corrected` trace payloads (jsonb containment) and placed after acceptance.
- **Trace filter:** `subject_id` also matches events whose payload `failed_assumptions` contains `{"assumption_id": id}`. The chip reads "Assumption A{n} · {wording}" (truncated), named from the Assumption lineage.
- **Group list:** a new `GET /reports/failed-assumptions` takes the same filters, plus `group_by` and `group_key`. It returns each failed Assumption in that group: Opportunity id/title, line label, kind, `A{n}`, wording, Assumption version and actual_id.
  - Its data comes from `reporting_failed_assumptions`, recreated with wording, position and amount columns (migration 0056, reversible).
  - It is authorized like 10.3: `reporting.report.read`, filtered by visibility before aggregating, and 403 otherwise.
  - In the group subline, "N failed Assumptions" becomes a button when N > 0 and opens that list. Each item links to its Opportunity's Trace, filtered to the Assumption.
- **Read-only drill-down:** a non-collaborator Head of Delivery can read the Actuals, Estimate and Trace tabs (already true through `opportunities.opportunity.read`; prove it with a test). No edit action renders.
- **End-to-end test:** a backend Postgres test builds an answered Gap → Condition → Baseline → final Actual citing the Condition, as a reusable fixture for Story 9.10. It walks the three API calls (report Opportunity row, Actuals view line with failed Assumption, trace filtered to the Assumption plus its lineage). The chain must contain the Gap, question, answer, conversion and Actual.
- axe-check every new view. Run `npm run gen:api` against a fresh local uvicorn.

**Never:**
- No writes, no new trace events, no new tables.
- No reading another module's tables outside the existing `table()`/trace-read precedents.
- No browser arithmetic on variance.
- No reporting → estimates import.
- No Pipeline (10.7) or outcome (10.5) work.
- No change to 10.3's variance colour rules.
- No Playwright suite.
- No Prettier on `web/`.
- No tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Drill from IT group | group SAP EWM, opp row title | Actuals sorted variance desc, chip "Integration Type: SAP EWM", only tagged lines | N/A |
| No-IT group | `integration_type=none` | lines with no Integration Type | N/A |
| Unknown IT | id not on any line | empty table + chip removable | N/A |
| Failed Condition | line Actual cites A2 | Inspector row: Condition icon, wording, accepted by/at, chips, Open in Trace | N/A |
| Contingency | 12 h Contingency | "12.0 h · wording" | N/A |
| Trace by Assumption | subject_id=A2 id | accepted/edited events + Actual recorded/corrected | unknown → empty |
| Group list | click "2 failed Assumptions" | 2 items, each → Trace filtered | N/A |
| Forbidden list | delivery manager GET | — | 403 problem+json |
| Non-collaborator HoD | opens Actuals/Estimate/Trace | read-only, no actions | N/A |

**Decisions (2026-10-27):**
- **Group list:** it opens in a Dialog titled "Failed Assumptions · {group label}", with one item per failed Assumption: kind icon, A{n}, wording, Opportunity title and line label, and a link to Trace.
- **Trace chain:** when the Trace tab is filtered to an Assumption, a "Chain" card sits above the event list. It reuses the Assumption lineage chain: origin → question → answer → conversion → acceptance → Actual. The list shows the Assumption's own events plus the Actual events. The filter is not widened to the Gap's events.
- **Scope:** the full scope stays in this story (no split), at about 2,600 tokens.

</frozen-after-approval>

## Code Map

All paths in the worktree `D:\pre-sales-agent-10-4`.

- **Reporting:**
  - `backend/app/modules/reporting/application/estimate_vs_actual.py`: CTEs `r_all`→`r`→`g`→`f` at :188-199, filters, `NO_GROUP_KEY` :316, visibility through `opportunities.readable_opportunities` :400. Add the `integration_type_id` filter, and put the new `failed_assumptions.py` beside it (reuse the same filter and group expansion).
  - `api/routes.py:46` (route and params pattern), `models.py`.
  - The migration `backend/migrations/versions/20261027_0056_reporting_failed_wording.py` has revision `0056_reporting_failed_wording` and revises `0055_reporting_views`. The view definition is at `0055_reporting_views.py:93`. Use `DROP VIEW` + `CREATE VIEW` and repeat the grants and revokes. The downgrade restores the 0055 view.
- **Actuals:**
  - `application/models.py:40` (`FailedAssumption`), `view.py:_failed` :141.
  - Enrich it through a new `estimates.public.assumption_details(uow, version_id, ids)`, which returns amount, `accepted_by` UserRef, `accepted_at`, position and evidence. Build it from `repository.AssumptionRecord` :701 plus the lineage evidence helpers in `estimates/application/lineage.py`, and extend `line_refs.py:57,73` as needed.
- **Lineage:**
  - `estimates/application/lineage.py:665` `get_assumption_lineage`, `models.py:777,796` (add `actual` to `LineageStepKind`).
  - Read the Actual events through the estimates repo's trace reads (precedent `payload_events` repository.py:1365, which matches top-level keys only). Add `failed_assumption_events(opportunity_id, assumption_id)` using `payload @> '{"failed_assumptions":[{"assumption_id":…}]}'`.
  - The payload models are at `platform/trace/catalogue.py:864,891`. Labels for the line come from `estimates.public` `version_lines`.
- **Trace:** `opportunities/adapters/repository.py:451`. Make the `subject_id` match `OR payload @> …`.
- **Tests:**
  - `tests/test_estimates_lineage.py`: `answered` :165, `assessed` :181, `baselined` :198.
  - `tests/test_actuals_api.py`: `_save` :153 (`failed_assumption_ids`), `HOD` :32.
  - `tests/test_reporting_views.py:33-80` (`seed_opportunity`, `SeedLine(failed=…)`).
  - `tests/test_reporting_api.py:46-86` (`_world`, `_hod`).
  - Put the new fixture in `tests/fixtures/drilldown.py`.
- **Web:**
  - Reports:
    - `components/reports/variance-table.tsx`: the Opportunity title link :206 and the main cause :224 → a new `actualsDrillHref` in `lib/reports.ts`.
    - `groupSubline` `lib/reports.ts:151` becomes the subline button.
    - URL params `ReportParams`/`parseReportParams`/`reportQuery`/`reportHref` :62-120. Data comes from `app/reports/data.ts`.
  - Actuals:
    - `app/opportunities/[id]/[tab]/page.tsx:36`: pass `searchParams` → `actuals.tsx:12` → `actuals-table.tsx` (`sort` :114, `sortLines` `lib/actuals.ts:92`, `select` :170).
    - Read-only failed list: `actual-inspector.tsx:528-533`. Add a `failed-assumption-list.tsx`.
  - Reuse:
    - `lineage-section.tsx`: `LineageChip` :69, `EvidenceChips` :115 (export it), assumption row :255-275, `AssumptionLineageSection` :542 (render the `actual` step).
    - `lib/estimates.ts`: `acceptedLabel` :441, `assumptionId` :474, `OPEN_IN_TRACE` :726, `lineTraceHref` :750 (add `assumptionTraceHref`).
    - Icons: `assumptions-register.tsx:442,448`.
    - `PaneLabel` `estimate-item-parts.tsx:28`, `ui/dialog`, `ui/chip.tsx`.
  - Trace:
    - `app/opportunities/[id]/trace.tsx:41-47`: add an `estimates.assumption` branch through `loadAssumptionLineage`.
    - `lib/trace.ts:378-385`: subject-aware `subjectChipLabel`.
    - `trace-list.tsx:385-399`.
  - Tokens: `bg-primary-tint` and `text-primary-text` (the mockup's `--primary-t`/`--primary-x`).

## Tasks & Acceptance

**Execution:**
- [x] Migration 0056, plus `test_reporting_views.py` updates for the new columns, grants and the write-denied check.
- [x] `reporting`: the `integration_type_id` filter and `failed_assumptions.py` with its route and models, plus `test_reporting_failed_assumptions.py`: matrix rows, 403 per role, visibility, each `group_by`.
- [x] `estimates`: `assumption_details`, the `actual` lineage step and the repo trace read; `actuals` view enrichment; the opportunities trace `subject_id` containment. Tests in `test_estimates_lineage.py`, `test_actuals_api.py` and `test_opportunity_trace.py`.
- [x] `tests/fixtures/drilldown.py` + `tests/test_drilldown_e2e.py`: the three navigations, the full chain, and a non-collaborator HoD getting read-only access with `can_record` false.
- [x] Web Reports links, subline button and group list: tests and axe.
- [x] Web Actuals URL params, IT chip and the Inspector failed list: tests and axe.
- [x] Web Trace Assumption chip, chain and `actual` step: tests and axe. Then `gen:api`.

**Acceptance Criteria:**
- Given the Head of Delivery on Reports grouped by Integration Type, when they open an Opportunity row, select its top line and choose Open in Trace on a failed Condition, then they reach the Trace filtered to that Condition in three navigations, and its chain shows the Gap, the question, the answer, the conversion, the acceptance and the Actual.
- Given a reviewer, when they open a line's Inspector, then failed Assumptions render read-only with no edit controls.

## Implementation Notes

- **Trace filter and `subject_type`.** The Open in Trace link carries `subject=estimates.assumption`, but the Actual events it must show are about `actuals.actual`. With a `subject_id`, `trace_page` now matches `(subject_id = id AND subject_type = …) OR payload @> {"failed_assumptions":[{"assumption_id": id}]}`: the subject type narrows only the subject's own events. Without a `subject_id`, `subject_type` filters as before.
- **Group list, one item per Assumption.** The subline counts distinct Assumptions, so `GET /reports/failed-assumptions` lists each Assumption once. When several of the group's Actuals name it, the item carries the first one's line (grid order) and Actual. Items are ordered by Opportunity title, then `A{n}`. An unknown `group_key` gives an empty list; a missing one is 422.
- **Shared filters.** The report's filter parameters moved into one FastAPI dependency (`_filters`), used by both Reports routes. The CTEs moved into `filtered_rows()`, which both statements reuse, so visibility, filters and the group expansion are identical. `f` now selects every column of the failed view.
- **Integration Type filter on Reports.** The report also returns `options.integration_types`, and the toolbar has an Integration Type select (kept in `integration_type_id`).
- **`assumption_details`** takes `actor` (keyword) and an optional `store`, beyond the Code Map's `(uow, version_id, ids)`. The Evidence is the Source passage of the Gap's recorded answer, read through `gaps.gap_lineage`, which needs an actor. `GET …/actuals` passes its `store` for the passage excerpts; the write paths (save, correct, close, import apply) leave it out, and `intake` then reads from the configured storage directory. `FailedAssumption.position` comes from the register; acceptance, hours and Evidence come from `assumption_details`. The new fields have defaults, so every `ActualVersionView` (history too) carries them.
- **`actual` lineage steps** come from `actuals.actual.recorded`/`.corrected` events, read through the estimates repository (`failed_assumption_events`, jsonb containment). A step is superseded once a correction replaced that Actual version (looked up by the correction's `previous_actual_id`), including a correction that dropped the Assumption. Line labels are "L{n}" in grid order from `version_lines`. Estimates may not import actuals, so the cause words are duplicated in `lineage.ACTUAL_CAUSE_LABELS`, and a test keeps them equal to `actuals.domain.actuals.CAUSE_LABELS`. Each step carries a structured `actual` (line, kind, effort, cause) beside the usual title and detail.
- **`AssumptionLineage`** gains `position` and `amount_hours`. The Trace chip reads "Assumption A{n} · {wording}" with the wording cut at 48 characters.
- **Actuals tab.** `sort` and `integration_type` seed the state. Removing the chip drops `integration_type` from the URL with `history.replaceState` (no navigation). Unplanned work isn't filtered. A filter that matches no line shows "No Baseline lines carry this Integration Type." An unknown id reads "Integration Type: Unknown".
- **Inspector.** The read-only list renders for every role below the form or summary. The summary's "Failed Assumptions" row now shows only the count, so the wording isn't repeated.
- **Fixture.** `tests/fixtures/drilldown.py` (`drilled`) builds on `test_estimates_lineage.baselined`. It tags the "Connect to SAP." Requirement with a new Integration Type and records a 48 h final Actual citing the Condition. `tests/fixtures/` gained an `__init__.py` so it imports as a package.
- `schema.d.ts` was regenerated from a local uvicorn (port 8804) against a throwaway Postgres (`psa-test-10-4`, port 55444).

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-28). B = blind-hunter, E = edge-case-hunter, V = verification-gap.

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | B+E+V | Stray `backend/%SystemDrive%/…/Caches/*.db` binaries in the diff | medium | patch | Intent-to-add during diff staging put them in the index; removed from index and disk, `%SystemDrive%/` added to `.gitignore`. |
| 2 | V | No page-level test sends `sort`/`integration_type` to the Actuals tab | gap | patch | Pre-verified: `pages.test.tsx` actuals cases pass no search params; component tests inject `drill`. |
| 3 | V | Trace tab's Assumption branch (lineage fetch, chip, Chain card) untested at page level | gap | patch | Pre-verified: `pages.test.tsx` `/trace` cases never serve a lineage endpoint. |
| 4 | V | `loadFailedAssumptions` server action only mocked | gap | patch | Pre-verified: no `app/reports/actions.test.ts`. |
| 5 | V | `build_view` docstring says excerpts are empty without `store` | low | patch | `intake` falls back to `BlobStore(get_settings().storage_dir)`; wording-only fix. |
| 6 | B | e2e docstring says "every write is 403" but checks two | low | patch | Wording-only fix. |
| 7 | B | `schema.d.ts` not regenerated | false | reject | It was excluded from the review diff on purpose; it is regenerated and `npm run typecheck` passes. |
| 8 | B+E | N+1 `gap_lineage` per failed Assumption on the Actuals GET | low | reject | A handful of failed Assumptions per Opportunity; batching adds a new public query. |
| 9 | B | No GIN index for the payload containment | low | reject | Both queries are first narrowed by the `(opportunity_id, occurred_at)` index; per-Opportunity event counts are small. |
| 10 | B | Containment branch also runs for line `subject_id`s | low | reject | Harmless (a line id never appears in `failed_assumptions`); a guard adds a branch. |
| 11 | B | Reports and Actuals may show different wording | false | reject | Both read the same `estimates_assumptions` row by id; Assumption rows belong to one version, so there is no version mismatch. |
| 12 | B+E | `_actual_steps` fallbacks (hours 0.0, version 1, kind final, bad `line_id`) | false | reject | The catalogue payload models validate these fields before the event is written. |
| 13 | B+E | Null/empty kind shows as "Condition"; dialog ignores `label`; missing detail reads "Not accepted" | low | reject | Refs are validated against the register at record time and Assumption rows are never deleted outside purge. |
| 14 | B | Inspector repeats "Failed Assumptions" (count row + section; DM form + list) | low | reject | The frozen spec keeps the DM form and asks for the read-only list for every role. |
| 15 | B | Filtered lines sit above unfiltered totals | low | reject | Frozen spec: "Totals stay server values". |
| 16 | B+E | Changing the sort after a drill leaves `sort=` stale in the URL | low | reject | Only seeds the initial sort; syncing adds a URL write on every sort. |
| 17 | B | `FilteredRows` frozen but `params` mutated; `_Filters` wrapper | low | reject | Works as written; refactor with no named harm. |
| 18 | B | e2e skips the group list; weak Evidence assertion | low | reject | The AC's three navigations don't include the list; `test_reporting_failed_assumptions.py` covers it. |
| 19 | B | Finding-origin Assumptions show no Evidence | low | reject | Same as the 9.9 lineage, whose Finding origin step carries no Evidence. |
| 20 | B | Untested: sales-rep Evidence, Unplanned `actual` step, `store=None` | low | reject | `gap_lineage` already enforces and tests the sales-rep rule; the others are rendering variants. |
| 21 | B | `assumption_details` public with no authorization | low | reject | Same contract as the existing `version_assumptions` / `version_lines` helpers; callers authorize. |
| 22 | B | "L{n}" computed in three places | low | reject | Existing 10.3 design; all three use section-then-position order. |
| 23 | E | Write paths call `build_view` without `store`, so excerpts are missing | false | reject | `intake` falls back to the configured store (row 5). |
| 24 | E | Drill filter uses line tags, not the Actual's stored Integration Types | low | reject | They differ only if Requirement tags change after recording; rare. |
| 25 | E | "No Integration Type" drill hides Unplanned work | false | reject | Unplanned work isn't filtered by the chip (Implementation Notes). |
| 26 | E | A product named "none" collides with `NO_GROUP_KEY` | low | reject | Pre-existing 10.3 sentinel; unrealistic product name. |
| 27 | E | NULL `assumption_version` gives 500 | false | reject | Every stored ref carries `version` (10.1 validation). |

## Design Notes

- An Actual's trace subject is the Actual itself, so the Assumption filter uses jsonb containment on the payload instead of new stored links (lineage stays derived, as in 9.9).
- The Integration Type filter lives on the client, because the Actuals view already carries `integration_types` per line. Sorting stays where 10.1 put it.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && uv run pytest tests/test_reporting_* tests/test_actuals_* tests/test_estimates_lineage.py tests/test_opportunity_trace.py tests/test_drilldown_e2e.py tests/test_architecture.py -q` -- expected: pass, none skipped
- `cd web && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build` -- expected: pass

**Manual checks:**
- Screenshot Reports → Actuals (drilled) → Inspector → Trace as the Head of Delivery, and compare each against the mockup's Reports, Actuals and Trace screens.
