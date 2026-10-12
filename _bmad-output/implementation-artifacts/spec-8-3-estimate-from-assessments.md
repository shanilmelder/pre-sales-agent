---
title: 'Story 8.3 (demo slice): Create an Estimate version from the specialist Assessments'
type: 'feature'
created: '2026-10-07'
status: 'done'
baseline_commit: 'ee2136d51de5032458c104f67809fd2f96c0e3cb'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-2-edit-estimate-hours.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-1-conflicts-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Estimate is drafted by its own model call. The Engineering, PM and Security Agents' hours per Requirement only appear in the Effort comparison and the effort Conflicts, so the person has to retype them into the Estimate (FR-26, FR-33).

**Approach:** The Estimate is now built deterministically from the agents' current Assessments each time an assessment run finishes, with no model call. It replaces the model-drafted Estimate. Each new version supersedes the current draft the way a re-draft does: accepted Assumptions and line edits carry over. Lines whose Requirement has an open Conflict show an **Open Conflict** marker that links to the Conflicts tab.

## Boundaries & Constraints

**Always:**
- **Depends on:** 5.8/5.9 (Assessments and effort), 6.1 (Conflicts and the `finish_run` hook), 8.1 (versions and lines), 8.2 (edits carried), 8.7 (Assumptions carried), 8.4 (proposals).
- **Trigger (decided 2026-10-07: replace the model draft):**
  - Gap detection no longer queues the model Estimate draft (`estimates.enqueue_draft`); it still queues the assessment run.
  - When a run finishes with at least one task `succeeded`, `finish_run` builds the version in its Unit of Work. This is just before the 6.1 Conflict detection, which therefore compares against the new Estimate.
  - A run with no succeeded task (failed or cancelled) builds nothing.
  - A run finished again after a task retry builds a new version again.
- **Lines (decided: one line per Requirement):** for each active Requirement that at least one agent's current Assessment sizes:
  - **Hours:** the sum of the Engineering, PM and Security hours (the 5.3 "Agents total").
  - **Section:** the Requirement's classification. It maps one to one onto the `demo-1` sections.
  - **Title:** the Requirement text, cut to 160 characters at a word boundary with "…".
  - **Role mix:** Engineering and Security hours as `engineer`, PM hours as `project_manager`, `qa` 0, as integer percentages summing to 100 by largest remainder.
  - **Basis:** "Engineering: … · PM: … · Security: …" from each agent's basis, cut to 500 characters.
  - **Covers:** that Requirement at its current version.
  - **Order:** lines follow section order, then Requirement order.
  - Requirements no agent sized get no line. They count in `uncovered_count`, as on a model draft.
- **Version:**
  - `template_version` `demo-1`, plus new columns `source` (`model | assessments`) and `source_run_id`.
  - It supersedes the current draft, then reuses what `accept_draft` does after storing a version: `carry_accepted` (8.7), `carry_edits` (8.2), the `estimates.estimate_version.created` trace (with `source`), `enqueue_proposals` (8.4) and the Red Team review (6.5). The actor is the system.
  - Extract a model-free `store_version(uow, opportunity_id, lines, ...)` from `accept_draft`, used by both paths.
  - If no agent sized any active Requirement, no version is built and the current one stays.
- **Model path kept but not triggered:** the Estimate tab no longer offers draft Retry. A model draft finishing after an Assessment-based version exists (a job left over from before this change) stores nothing.
- **Conflict markers:**
  - When a line is shown, the read model marks it with each open or escalated `effort` or `scope` Conflict whose positions cite one of the line's covered Requirements, with the Conflict's id and type.
  - The marker says "Open Conflict"; the inspector names the Conflict type and links to the Conflicts tab (no deep link).
  - Needs a principal-free `conflicts.open_by_requirement(uow, opportunity_id)`.
- **Web (Estimate tab):**
  - The header version pill reads "Estimate v4 · from Assessments (run 3)" when `source` is `assessments`.
  - **No version yet:**
    - While a run is queued or running, the tab shows "The Estimate is built when the Engineering, PM and Security Agents finish." with a running dot, polling as today.
    - Otherwise it shows "No Estimate yet. Run assessment on the Assessments tab to build it."
  - The **Open Conflict** marker sits next to the 8.2 Edited marker, as an icon plus label in blocker colour.
  - Keyboard and axe as in the existing grid.
- **Privacy:** no Requirement or line text in logs or trace.

**Never:**
- No model call for this path, and no new Estimate model prompt.
- No Assumptions taken from Assessments, since they don't type any. No `estimates_risks` table.
- No resolving Conflicts or using a chosen position (6.3).
- No Workflow Run node or `node:` idempotency key (no LangGraph).
- No per-integration or Work Package catalogue, and no durations.
- No manual "Create version from run" action.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Gap detection | Gaps accepted | Assessment run queued; no model Estimate draft queued | N/A |
| Happy | Run finishes; Eng 20/PM 10/Sec 4 h on R1 (integration), Eng 8 h on R2 (functional) | v1 `source=assessments`: R2 line (functional, 8 h, mix 100/0/0) then R1 line (integration, 34 h, mix 71/29/0); totals server-calculated; trace | N/A |
| Supersede + carry | v2 (model) has an accepted Assumption and an edited line whose section and title match | v3 from Assessments; v2 superseded; Assumption "Carried from v2"; edit carried | N/A |
| Effort re-check | An effort Conflict on R1 from the previous run; the new version allocates the agents' hours to R1 | Detection in the same finish resolves it | N/A |
| Markers | An open scope Conflict on R2 | R2's line shows **Open Conflict** linking to the Conflicts tab | N/A |
| Failed run | Every task failed | No version; the current Estimate unchanged | N/A |
| No effort | Assessments exist, none sizes an active Requirement | No version | N/A |
| Late model draft | A model draft job finishes after an Assessment-based version | Nothing stored | N/A |
| Waiting | Run running, no version | Tab shows the waiting sentence | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/application/draft.py`:
  - `accept_draft` (:186): storing the version is at :236-263, the post-store steps at :264-302.
  - Extract `store_version`, which both paths use. `_succeed` stays on the model path.
  - `assessments.enqueue_review` is imported lazily (cycle); do the same for any assessments import.
- `estimates/adapters/repository.py`: `insert_version` (:250), `NewLine` (:73), `supersede_drafts`, `latest_version_number`, `current_version`.
- `estimates/adapters/models.py`: `EstimateVersionRow` (:55). Add `source` + `source_run_id` (migration `0022_estimates_from_assessments`, down `0021_conflicts`; existing rows `model`).
- `estimates/domain/estimates.py`:
  - Sections (:25-37) equal Requirement classifications.
  - `ROLES` (:40), `valid_mix` (:177), `valid_effort` (:169), title ≤160 and basis ≤500 (:102-103), `validate_line` (:191).
  - Put the line rule in a new pure `domain/from_assessments.py`, unit-tested.
- `estimates/application/estimates.py`: `_role_hours` (:118); `get_estimate` adds `source`, `source_run`, line `conflicts`, and whether an assessment run is in progress (for the waiting state).
- `gaps/application/detection.py:306-314`: remove the `estimates.enqueue_draft` call (keep `assessments.enqueue_run`). Update tests that expect a draft there.
- Hook: `assessments/application/assessment.py` `finish_run` (:297). Before `detect_conflicts` (:335), when at least one task succeeded, call `estimates.application.public.build_from_assessments(uow, opportunity_id, run_id, snapshots)`.
  - Assessments already imports estimates' public module, so no cycle.
  - Pass agent, Assessment version and effort rows with basis. Extend `current_assessment_snapshots` (:339) or add a sibling that includes basis.
- `conflicts/application/public.py`: add `open_by_requirement` (read by the estimates read model). Estimates → conflicts is a new import; conflicts imports neither, so there's no cycle. Update the import-linter contracts.
- Trace catalogue: `EstimatesEstimateVersionCreated` gets `source` (and `source_run_id`). No new identity action.
- **Web:**
  - `components/opportunities/estimate-grid.tsx`: `EditedMarker` (:137, used :469) is where the Conflict marker goes; `EstimateHeader` (:607) gets the pill text, the waiting state, and no draft Retry; the polling (2 s, paused while hidden, 15-minute stop) stays for the waiting state.
  - `estimate-inspector.tsx` gets the Conflict section with a `tabHref(id, "conflicts")` link.
  - Regenerate `schema.d.ts` from a dumped `app.openapi()`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**`, migration 0022, catalogue -- `store_version` extraction, `domain/from_assessments.py`, `build_from_assessments`, the late-model-draft guard, read-model `source`, waiting state and markers
- [x] `backend/app/modules/assessments/application/assessment.py`, `gaps/application/detection.py`, `conflicts/application/public.py`, import-linter -- the `finish_run` hook, no model draft from Gap detection, `open_by_requirement`
- [x] `backend/tests/test_estimates_from_assessments*.py` -- pure line-rule tests and Postgres tests for every matrix row
- [x] Web: schema, header pill, waiting and empty states (no draft Retry), marker, inspector link, and tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity after an assessment run, when it finishes, then the Estimate tab shows a version from the Assessments with lines with the agents' hours, totals recalculated, earlier edits and accepted Assumptions carried, and Open Conflict markers where the agents disagree.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Domain:** `estimates/domain/from_assessments.py` (`build_lines`, `role_mix`, `cut`; DTOs `AgentSizing`, `SizingRow`, re-exported from `estimates.application.public`). Agent hours are matched to a Requirement by id, whatever version the agent sized (as 5.3 and the 6.1 rules). The summed hours are not capped at the model path's 2,000 h. A blank Requirement text falls back to `R<n>` as the title.
- **Store:** `draft.store_version` holds everything after validation (supersede, insert, carry Assumptions and edits, trace, proposals, Red Team); `accept_draft` and `application/from_assessments.build_from_assessments` both call it. The build takes the same draft lock (`repo.lock_opportunity`). Actor `system` / `estimates.build_from_assessments`.
- **Hook:** `assessments.finish_run` calls it with `current_sizings` (each agent's current Assessment and effort rows with basis) when `succeeded_count > 0`, before `detect_conflicts`. This also applies to `fail_stale` (a lost run with some succeeded tasks).
- **Late model draft:** `accept_draft` marks the draft `succeeded` and stores nothing once any version of the Opportunity has `source = 'assessments'` (`repo.has_version_from`).
- **Read model:** `EstimateVersion.source` / `source_run` (run number = position among the Opportunity's runs, oldest first, via `assessments.public.run_number`), `EstimateLine.conflicts` (`conflicts.public.open_by_requirement`: open and escalated `effort`/`scope` Conflicts by the Requirement their positions cite), `EstimateView.assessment_running` (`assessments.public.run_in_progress`). The assessments reads are lazy imports (cycle). Import-linter contracts already allowed `estimates → conflicts.application.public`; none changed.
- **Web:** the tab polls while `assessment_running`, a legacy model draft or proposals are in progress. The Open Conflict marker is a link with `tabIndex=-1` so the grid stays one Tab stop; the inspector's "View on the Conflicts tab" link is the keyboard path. The Assumptions Register's proposals "Retry" (which re-drafted the Estimate) is removed with the header Retry.
- **Tests:** existing model-draft tests now queue the draft explicitly (`test_estimates_draft.detected` / `requeue`); the 6.1 agents-vs-Estimate tests get their disagreement from an edit carried onto the next version from the Assessments.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | edge | A cancelled run with succeeded tasks builds no version (and runs no detection) | medium | patch | `cancel` (assessment.py:241) sets the run `cancelled` without `finish_run`; the succeeded agents' Assessments stay current but never reach the Estimate. |
| 2 | blind+edge | No sign of a rebuild while a run is in progress and a version exists | medium | patch | `EstimateHeader` shows the waiting state only without a version; the grid is swapped silently when the run finishes. |
| 3 | blind | Stale docstrings (`EstimatesEstimateVersionCreated`, `enqueue_review`, `enqueue_run`, polling comment) | low | patch | Direct wording corrections. |
| 4 | vgap+blind | `source_run` asserted only as 1 | medium | patch | Pre-verified: no test reads it after a second run. |
| 5 | vgap | No backend test of an `effort` Conflict marker on a line | medium | patch | Pre-verified: only a scope marker is asserted. |
| 6 | blind | A late model draft still calls the model; `start_draft` API still exposed | low | reject | Only leftover jobs or a direct API call; the result is discarded as the frozen intent says. |
| 7 | blind | A retry re-finish builds a new version even when nothing changed | false | reject | A retry only re-finishes after a failed task succeeded, so an Assessment did change; the frozen intent builds again. |
| 8 | blind+edge | "run n" label may include a failed agent's earlier Assessment | low | reject | Frozen: built from each agent's current Assessment; the label names the run that triggered it. |
| 9 | blind | Sizing of an older Requirement version applied to the current one | low | reject | Same matching as the 5.3 comparison and the 6.1 rules. |
| 10 | blind | `Section(classification)` unguarded | false | reject | `intake_requirements` CHECK limits classification to the six values equal to the sections. |
| 11 | blind+edge | Run that sizes nothing keeps the old version, with no notice | low | reject | Frozen behaviour; needs every agent to size nothing. |
| 12 | blind | Integer role-mix rounding shifts role hours by ~0.1 | low | reject | Inherent to the `demo-1` integer mix (`valid_mix`). |
| 13 | blind | Markers read "now" for non-current versions | low | reject | Only the current draft is shown; export has no markers. |
| 14 | blind | Marker links to the tab, not the Conflict | false | reject | Frozen: no deep link. |
| 15 | blind | Missing tests: escalated, dedupe, older version + nothing sized | low | reject | Escalated is unreachable (6.3 deferred); the others are rare. |
| 16 | edge | Summed line may exceed the 2,000 h edit limit | low | reject | Needs agents sizing one Requirement near 2,000 h together; rare. |
| 17 | edge | Exception in the build rolls back `finish_run` | false | reject | No reachable trigger shown; pure line rule with tested template rules. |
| 18 | edge | Screen reader announces the unchanged version after a run that built nothing | low | reject | Rare (every agent must size nothing). |
| 19 | edge | Grid marker link not in the Tab order | false | reject | Deliberate single Tab stop; the inspector link is the keyboard path. |
| 20 | edge | A leftover model draft in progress or failed, with no version, shows "No Estimate yet" | low | reject | Only jobs left from before this change. |
| 21 | edge | Only effort and scope Conflicts are marked | false | reject | Frozen: effort or scope. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
