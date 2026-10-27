---
title: 'Story 9.9: Trace any number to its Evidence and compare versions'
type: 'feature'
created: '2026-10-27'
status: 'done'
baseline_commit: '126d06989d3a89c6cbb59db19ac11f9b94f8741a'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-7-set-the-baseline.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-8-decision-trace.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Trace tab (9.8) lists events, but nobody can start from a figure. There is no way to go from an Estimate line or Assumption to the Findings, Evidence and human decisions behind it, and no way to compare two Estimate Versions other than the review panel's "vs previous" diff (FR-42).

**Approach:** Add read-only lineage queries in `estimates`, built from other modules' `public.py` and the trace, and show them as a **Lineage** section in the line and Assumption inspectors, with **Open in Trace**. Add a two-version compare endpoint and the mockup's **Diff** toggle, which compares against any chosen version, plus a "Why it changed" list. Prove both with a Postgres lineage test on a Baseline fixture. Scope: both halves of 9.9 in one PR (user, 2026-10-27). Follow the new mockup where it draws something; where it doesn't (lineage, picker, "Why it changed"), use the existing Inspector and diff patterns.

## Boundaries & Constraints

**Always:**
- **Access:** every new endpoint calls `opportunities.readable_resource`. Non-readers get 404. Sales representatives get the endpoints read-only, and gap questions follow the existing rule (`question` is null unless it was approved or sent). A line, version or Assumption from another Opportunity → 404.
- **`GET /opportunities/{id}/estimate-lines/{line_id}/lineage`** → `estimates.get_line_lineage`. The response has these sections; each item carries `superseded: bool` and the cited `version`:
  - `requirements`: each covered Requirement at its cited version, with Evidence chips (`intake.evidence_labels`). It is superseded when the cited version is older than the active one or the Requirement is no longer active.
  - `findings`: the Findings and effort entries from the line's version's `source_run_id` Assessments (`assessments.public.assessment_at`) that cite those Requirements, each with its agent, Assessment id and version, and Evidence. A rerun Assessment is superseded.
  - `decisions`: Conflict resolutions whose trace `line_id` is this line, plus Finding overrides on those Findings, each with reason, actor and time.
  - `assumptions`: Contingency Assumptions with `line_id` = this line.
  - `edits`: every `estimates.estimate_line.edited` event for this line and its carried predecessors (same section and title on earlier versions, as `carry_edits` matches them): before/after hours, reason, actor, time.
  - `reviews`: Challenges that target this version or a listed Finding or Assessment, and review decisions on this version (reason, actor, time).
- **`GET …/assumptions/{assumption_id}/lineage`** → `estimates.get_assumption_lineage`. A chain of origin (Gap or Unknown via `is_unknown`, or Finding), then the Clarification Question, then the recorded answer with its Source passage (`intake.passage_refs`), then conversion (`gaps.gap.converted`), then acceptance (`accepted_by` name and `accepted_at`). A missing step is omitted, not invented.
- **`GET …/estimate-versions/compare?from={n}&to={m}`** → `estimates.compare_any`. `from` and `to` must be different. It returns:
  - line diffs via the existing `diff_lines` (added, removed, changed, with `delta_hours`);
  - total before, after and delta;
  - Assumptions and Risks added, removed or changed, matched by `origin_ref`/text;
  - `why`: trace events with `occurred_at` from the older version's `created_at` until the newer version was superseded by a later version, or until now if it hasn't been (decision 2026-10-27, after review: edits to a draft after its creation must appear), limited to these types: line edits, version created, Conflict resolved or escalated, Challenge raised, confirmed or declined, review decision recorded, Assessment completed (rerun), Finding overridden or resolved, Assumption and Risk changes, Gap converted. Each row has a label, actor, time, reason and subject.
  - Leave the review panel's `compare_versions`/`VersionDiff` unchanged.
- **Trace filter:** `GET /trace` gains an exact-match `subject_id`. The web Trace tab gets a `subject_id` URL param with a visible removable "Line {title}" filter chip.
- **New public queries** where the investigation found gaps:
  - `assessments`: Critic and Red Team Findings, with their override or resolution, for a run or Requirements, with no actor.
  - `gaps`: the lineage of a Gap by id (question, answer passage, answered by and when), honouring the sales-rep rule.
  - `reviews`: Challenges by version or target id.
- Estimates imports these lazily inside functions (import-linter).
- **Web: Lineage** (Inspector pattern, eyebrow `PaneLabel` headings in the section order above):
  - Shown in `EstimateInspector`. A **Trace** outline button in the inspector, or `t` on a focused grid row (single-key shortcuts only), opens the inspector and scrolls to and focuses Lineage. Enter keeps opening the inspector as today.
  - The same section appears in `AssumptionInspector` as a vertical chain.
  - Evidence chips use the mockup chip (`--primary-tint`/`--primary-x`, radius 6px, 2px 8px padding, 11px quote icon).
  - Superseded items show `<s>` plus a "superseded" label (`OriginText` pattern) and still open the cited version: a Requirement chip shows that version's text in a `PassageView`; an Assessment opens a summary of that version.
  - **Open in Trace** → `/trace?subject=estimates.estimate_line&subject_id={line}`.
  - Loading uses a skeleton (≥150 ms). An empty section reads "Nothing recorded."
- **Web: compare** (mockup @538441, @546588):
  - A toolbar toggle **"Diff vs v{n}"** sits before Export: `aria-pressed`, 14px diff icon, 13px/500, 6px 12px padding, radius 8. On: `--primary-tint`/`--primary-x`/`--primary` border. Off: surface/text/`--border2`. `d` toggles it, with the `v`-key guards.
  - It defaults to the previous version, or to the Baseline when viewing a later version and a Baseline exists. A chevron menu beside it lists every other version, Baseline first with its anchor pill, so any two can be compared. The choice is kept in `?diff={n}`.
  - **Diff on:**
    - Each line's Total cell gets a second line at 11px/500: "+x.x h" or "−x.x h" in `text-gap`, or "no change" in `text2`. Changed rows get `bg-diff-tint` and an sr-only "changed"/"added". Removed lines appear struck through with "removed".
    - Totals show the same delta.
    - The right pane shows "Compared with v{n}" (Assumptions and Risks with `−`/`+` markers on `bg-diff-tint`, as `agent-config-diff`) and **Why it changed** (a dated list: event label from `lib/trace.ts`, actor, reason, subject link).
  - A polite announcement: "Comparing v{m} with v{n}".
- Regenerate `schema.d.ts` from a fresh local uvicorn. axe-check every new view.

**Never:**
- No migration. No new stored links (lineage is derived).
- No writes or new trace events.
- No reads of another module's tables.
- No changes to `diff_lines` semantics or the `VersionDiff` shape.
- No Prettier on `web/`.
- No tests on the dev `psa` DB.
- No 9.10 end-to-end fixture or completeness test.
- No Scenario diff.
- No export of the comparison.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Assessed line | line from Assessment run, 2 Requirements | requirements + findings with Evidence chips and agent/version | N/A |
| Edited line | line edited on v2 then carried to v3 | v3 lineage lists both edits with reasons | N/A |
| Conflict applied | Conflict resolved onto the line | decision with reason, actor | N/A |
| Superseded | Requirement edited after v2 cited v1 | item `superseded: true`, cites v1 | N/A |
| Model-drafted | `source='model'` version | no findings; requirements + edits only | N/A |
| Assumption | converted from answered Gap | origin → question → answer + passage → conversion → accepted by/at | N/A |
| Sales rep | read access | 200, unapproved gap question null | N/A |
| Other / non-member | line of other Opportunity / no access | — | 404 |
| Compare any | Baseline v2 vs v5 | line, total, Assumption, Risk diffs + why events in window | N/A |
| Bad compare | `from=to` or unknown version | — | 422 / 404 |
| Trace link | `subject_id={line}` | only that line's events | unknown id → empty page |
| Lineage test | Baseline fixture, fake gateway, Postgres | every Baseline line has ≥1 finding/effort entry with Evidence or an edit with reason; every Assumption has origin and accepting person | N/A |

</frozen-after-approval>

## Code Map

All paths under `backend/app/modules/` and `web/src/` in the worktree `D:\pre-sales-agent-9-9`.

- **estimates/adapters/models.py:**
  - `EstimateVersionRow` :58 (`source`, `source_run_id`, `created_at`).
  - `EstimateLineRow` :124 (latest edit only).
  - `estimates_line_requirements` :174.
  - `AssumptionRow` :192 (`origin_ref`, `accepted_by/at`, `line_id`).
  - Risks :253.
  - Baselines :297.
- **estimates/adapters/repository.py:**
  - :22 already imports `TraceEvent`; `version_reasons` :1256 is the precedent for trace reads. Add `line_edit_events` and `events_between`, served by the `(opportunity_id, occurred_at)` index.
  - `version_by_number`.
- **estimates/application/compare.py:**
  - `diff_lines` :44: reuse it.
  - `compare_versions` :91: leave as is.
  - Add `compare_any` here. Put the lineage code in new `application/lineage.py`.
  - Export both from `public.py`. Models go in `application/models.py` (keep `LineDiff`/`VersionDiff` :491,505).
- **estimates/application/line_edits.py:**
  - Edit events are written at :190 and :314.
  - `carry_edits` holds the predecessor matching rule.
- **estimates/api/routes.py:** route pattern :63-95; versions :698; estimate :73.
- **Auth:** `opportunities.readable_resource`. `NotFoundError` as in `baseline.py:56,109`.
- **Lazy imports:** `baseline.py:130`, `blockers.py:112,149`.
- **Public queries to reuse:**
  - `assessments.public`: `run_assessment_snapshots`, `assessment_at`, `finding_titles`. `FindingOverride`/`FindingResolution` at `assessments/application/models.py:77,88` are reachable only through actor-checked `get_red_team`/`get_critic`; add the actor-less query.
  - `conflicts`: `ConflictView` has no `line_id`; it lives in the `conflicts.conflict.resolved` payload (catalogue :1327).
  - `intake`: `active_requirement_snapshots`, `requirement_version_texts`, `evidence_labels`, `passage_refs`.
  - `gaps`: `gap_summaries` has no answer; sales-rep rule at `gaps/application/models.py:348,388`; `is_unknown` at `gaps/domain/gaps.py:53`.
  - `reviews`: `version_approvals`, `list_review_requests`; there is no challenges-by-version query.
- **Trace:**
  - `opportunities/adapters/repository.py:418` `trace_page`: add `subject_id`. Route in `opportunities/api/routes.py`.
  - Labels via `opportunities/application/trace.py` `ordered_payload`.
- **Web:**
  - `components/opportunities/estimate-grid.tsx`: `EstimateGrid` :255 (keys :280-307, `tfoot` :444); `EstimateHeader` :480; `EstimateSection` :672 (`Selection` ~:655, `open*` :793-859, panes :1249-1330).
  - `estimate-inspector.tsx:78`, `assumption-inspector.tsx:322`, `version-switcher.tsx:80-93` (key-listener pattern), `lib/estimates.ts:603-640`.
  - Reuse: `agent-config-diff.tsx:10-20` (marker rows), `review-panel.tsx:130-162` (`DiffView`), `lib/reviews.ts:308` `deltaLabel` (but use "no change"), `estimate-item-parts.tsx:28,38-55` (`PaneLabel`, `OriginText`), `requirement-inspector.tsx:67-105` (`EvidenceChip`, `PassageView`), `trace-list.tsx:192`.
  - Trace: `lib/trace.ts` (`EVENT_LABELS` :26, filters :295-353), `app/opportunities/data.ts:229,248,415`, `actions.ts:789,801`.
  - Tokens: `app/globals.css:99,225` (`bg-diff-tint`), `text-gap`.
  - axe: `@/test/axe`; fixtures `test/review-fixtures.ts`.
- **Tests:**
  - `tests/test_estimates_from_assessments.py` (`prepared` :97, `run` :107, `HAPPY` :86, `edit` :152).
  - `tests/test_estimates_baseline.py` (`_approved` :94, `_submit`, `_approve_alone`).
  - `tests/test_estimates_assumptions.py` (`_accept`, `contingency`).
  - `_events` at `tests/test_reviews_requests.py:178`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/{assessments,gaps,reviews}/application/public.py` (+ repos) -- add the three missing actor-less public queries -- so lineage composes `public.py` only.
- [x] `backend/app/modules/estimates/application/lineage.py`, `compare.py`, `models.py`, `public.py`, `adapters/repository.py`, `api/routes.py` -- add the line and Assumption lineage and `compare_any`, plus their endpoints -- the core of the story.
- [x] `backend/app/modules/opportunities/{adapters/repository.py,api/routes.py}` -- add the `subject_id` filter -- for Open in Trace.
- [x] `backend/tests/test_estimates_lineage.py`, `test_estimates_compare_any.py`, `test_opportunity_trace.py` -- every matrix row against Postgres with a fake gateway, including the Baseline lineage test.
- [x] `web/src/lib/api/schema.d.ts`, `lib/estimates.ts`, `lib/trace.ts`, `app/opportunities/{data,actions}.ts` -- add the types, loaders and the `subject_id` param.
- [x] `web/src/components/opportunities/lineage-section.tsx` (new), `estimate-inspector.tsx`, `assumption-inspector.tsx`, `estimate-grid.tsx`, `diff-toggle.tsx` (new), `trace` filter chip -- build the UI described above -- with tests and axe.

**Acceptance Criteria:**
- Given a Baseline line in the demo flow, when I press `t` or choose Trace, then Lineage lists its Requirements, Findings with Evidence, decisions and edits, and Open in Trace shows only that line's events.
- Given v3 selected with Baseline v2, when I press `d`, then the toggle reads "Diff vs v2", the Total cells show deltas, and the pane lists "Why it changed"; picking v1 in the menu re-diffs against v1.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Reads beyond the listed public queries.** Conflict resolutions (`line_id`), review decisions (`target_id`), Gap raise/convert events and the "why" window come from `platform_trace_events` through estimates' own repository (`subject_events`, `payload_events`, `line_edit_events`, `events_between`), as `version_reasons` already did; no other module's table is read.
- **New public queries:** `assessments.linked_review_findings` (Critic Reviews of the run and Red Team Reviews of the version, Findings citing the line's Requirements or the line, with resolution/override; `finding_states` now reuses its actor-less `finding_decisions`), `gaps.gap_lineage` (reuses `gap_views`, so the sales-rep question rule is the same), `reviews.challenges_for`. `opportunities.agent_name` is exported for actor names.
- **Line `findings`** also lists the run's Critic and the version's Red Team Findings (entries `critic`/`red_team`), whose overrides and resolutions are the `decisions` "Finding overrides on those Findings" (specialist Findings can't be overridden). Effort entries are keyed `{assessment_id}:{requirement_id}`.
- **`superseded`:** a requirement when the cited version is older than the active one or it is inactive; a finding/effort entry when its Assessment (or Review) is no longer current; an edit when a later edit replaced it; a decision when its Review was superseded; a Conflict decision and an Assumption are never superseded.
- **Trace filter:** a `subject_id` that isn't a UUID gives an empty page (not 422), like an unknown one. The Trace tab names the chip from the line's lineage (`title`).
- **Web:** the diff turns on with the pane opened on "Compared with v{n}" (the selection is cleared); the announcement is made in the handler before the pane opens so the throttled live region reads it first. `?diff=n` is written with `history.replaceState` (no navigation). Removed lines are listed in a trailing "Removed lines" row group; section subtotals show the sum of their lines' deltas. The sr-only "changed"/"added" sits beside the line button, not inside it (it would change the button's name).
- **Review fixes:** the "why" window ends at the next version's `created_at`, else now; a declined Challenge carries `decline_reason`; the line lineage reloads on the line's `row_version`/total; the `t` focus request is monotonic and acted on once (`lineageFocusHandled`); `?diff=n` opens the Compare pane; "Why it changed" shows the server's `label`. A Red Team Finding must cite a Requirement, so the line-only test cites one the line doesn't cover.
- `schema.d.ts` was regenerated from a local uvicorn (port 8799) against a throwaway Postgres.

## Spec Change Log

- **Loop 1 (2026-10-27), triage row 7 (intent_gap):** "Why it changed" ended at the newer version's creation, so edits to a draft after its creation showed in the diff but not in "why". The user amended the frozen `why` window: it now runs until the newer version is superseded, or until now. The user chose to patch in place instead of reverting. Known-bad state avoided: a diff whose changes have no listed cause. KEEP: everything else in the build, which passed review apart from triage rows 1–5, 12, 20–22 and 27, patched in the same pass.

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | verify | Critic Findings and line-only Red Team Findings in line lineage untested | medium | patch | Pre-verified: no test asserts `entry == "critic"` or a `lines=[…]`-only Red Team finding. |
| 2 | verify | Challenges in line lineage never exercised | medium | patch | Pre-verified: no lineage test raises a Challenge; `challenges_for` untested. |
| 3 | verify | Line-linked Contingencies only asserted empty | medium | patch | Pre-verified: only `assumptions == []` asserted; web fixture empty. |
| 4 | verify | `finding_resolved` decisions untested | low | patch | Pre-verified: only overrides and Conflict decisions asserted. |
| 5 | verify | Compare "changed" for Contingency hours and Risk rating unpinned | low | patch | Pre-verified: only a reworded Condition and an added/removed Risk tested. |
| 6 | verify | `estimate_version_ids` never passed to `challenges_for` | false | reject | `target_ids` already includes the version id; passing the version would wrongly pull Challenges on other lines' Findings. |
| 7 | blind | "Why it changed" stops at the newer version's creation, so edits to a draft after creation are missing while the diff shows them | medium | intent_gap | `compare.py:263` `end = max(newer.created_at, …)`, as the frozen block specifies ("between … created_at"); the test asserts `assumption.edited` absent. Common case: Diff vs Baseline on a draft being edited. |
| 8 | blind | "Why" events not tied to the two versions; unbounded | low | reject | The window is the intent's definition; branching from an older version is rare; demo volumes. |
| 9 | blind+edge | `_items_diff` keyed by origin collapses duplicates; wording fallback unreachable | low | reject | A Gap converts once (`gaps/application/conversion.py:46`), so one Assumption/Risk per Gap per version. |
| 10 | blind | Predecessors matched by title can cross branched versions | low | reject | The intent fixes the `carry_edits` rule; branching is rare. |
| 11 | blind+edge | `ChallengeRef.created_at` falls back to now | false | reject | `created_at` is non-null with a server default (`reviews/adapters/models.py:209`); the fallback never runs. |
| 12 | blind | A declined Challenge's decline reason is dropped | low | patch | `decline_reason` is loaded on `ChallengeRef` but not shown; direct fix. |
| 13 | blind | Decisions on Critic/Red Team Reviews not looked up | maybe-false | reject | Would need to confirm that Review Requests can target those Reviews; at most low. |
| 14 | blind | A role-mix-only edit reads "30 h → 30 h" | low | reject | Needs new fields; rare. |
| 15 | blind | Missing `before_hours` becomes 0.0 | false | reject | The catalogue payload model requires both fields. |
| 16 | blind | `superseded` always false on Conflict decisions and Gap steps | low | reject | Recorded choice in Implementation Notes; the intent names Requirement versions and reruns. |
| 17 | blind | Assumption lineage omits proposal and later edits | low | reject | The intent fixes the chain's steps. |
| 18 | blind | Open in Trace shows fewer events than the lineage | false | reject | The intent defines the link as the line's own events. |
| 19 | blind+edge | Trace tab loads a whole lineage to name the chip; chip reads "Line" for other subjects | low | reject | Demo volumes; the chip is only reached from the line link. |
| 20 | blind+edge | Line lineage stays stale after editing the line in the same inspector | medium | patch | `lineage-section.tsx` effect depends only on `opportunityId`/`lineId`; draft edits keep the ids. |
| 21 | blind+edge | Summed focus requests can move focus to Lineage on `e` or on remount | low | patch | `estimate-inspector.tsx:251` sums them and `estimate-grid.tsx:931` resets to 0, so the sum can change while > 0. |
| 22 | blind | Compare pane ignores the server's `WhyEvent.label` and keeps a second label map | low | patch | Direct fix: render `event.label`. |
| 23 | blind | Unindexed payload lookups, serial `assessment_at`, `KeyError` on actors | low | reject | Demo volumes; `trace_actors` resolves every actor in the list. |
| 24 | blind | Conflict test uses a hand-written trace row; unapplied resolutions excluded; not-found text | low | reject | The other coverage gaps are rows 1–5; unapplied resolutions don't touch the line. |
| 25 | edge | Web diff map overwrites lines with duplicate titles | low | reject | Same section and title twice on one version is unlikely. |
| 26 | edge | No announcement for `?diff=n` before versions load | maybe-false | reject | The versions list comes from the server render; at most low. |
| 27 | edge | `?diff=n` from the URL never opens the Compare pane | medium | patch | `estimate-grid.tsx:1283` `onDiffFromUrl` doesn't clear the selection or open the pane, unlike `onToggle`. |
| 28 | edge | The pane stays open after the diff is turned off | low | reject | It shows the inspector's empty-state prompt. |
| 29 | edge | `t` not guarded against key repeat or IME | low | reject | Adds a guard; rare. |
| 30 | edge | A negative `version` in an edit payload gives a 500 | false | reject | The catalogue payload model validates it. |

## Design Notes

- **Lines store no Finding ids.** Lineage is derived as line → `estimates_line_requirements` → the version's `source_run_id` Assessments → the Findings and effort entries that cite those Requirements. A specialist Finding carries no Evidence of its own, so its Evidence is the cited Requirement version's Evidence. The lineage test counts an effort entry the same way, because `from_assessments` sizes a line from effort rows that may have no Finding.
- **The diff default target is the Baseline when one exists, otherwise the previous version.** This matches "the Baseline is listed first" and the mockup's toggle label.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
