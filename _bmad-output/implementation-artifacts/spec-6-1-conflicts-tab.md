---
title: 'Story 6.1 (demo slice): Detect Conflicts between specialist Assessments and list them on the Conflicts tab'
type: 'feature'
created: '2026-10-07'
status: 'done'
baseline_commit: '78675bd9e2a0d360e33db74b1e4ec47e2175402f'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Engineering, PM and Security Agents each assess the Opportunity on their own, and nothing points out where they disagree, so contradictions reach the Estimate unnoticed. The Conflicts tab (6) only says "Not available yet." (FR-30).

**Approach:** A new `conflicts` module runs deterministic rules over the current specialist Assessments each time an assessment run finishes, and stores each disagreement as a Conflict with one position per Assessment. The Conflicts tab lists them read-only, Open first and then Resolved.

## Boundaries & Constraints

**Always:**
- **Depends on:** 5.8/5.9 (Assessments with Findings and per-Requirement effort), 1.8 Part A (workspace tabs).
- **Trigger (decided):** detection runs inside `assessments.finish_run`'s Unit of Work, after its trace append, whenever the run reaches a final status. It runs on retries too, so it must be idempotent. There's no separate `conflict_detection` task or job; the rules are pure and cheap.
- **Rules (decided: three; pure functions in `conflicts/domain/rules/`, unit-tested without DB or LLM)** over each agent's current Assessment plus the current Estimate draft:
  - **(a) Scope, `medium`:** Engineering or PM sizes a Requirement and the other has no effort row for it, though it has a current Assessment. One Conflict per Requirement; positions "24 h" and "Not sized".
  - **(b) Recommendation clash, type `assumption`, `high`:** at least one agent recommends `proceed` and another `do_not_proceed`. One Opportunity-level Conflict (no Requirement) with a position per agent, each showing its recommendation.
  - **(c) Agents vs Estimate, type `effort`, `medium`:**
    - Per active Requirement, compare A, the sum of the agents' hours (as in 5.3), with E, the Estimate (allocated) hours: each line's effort hours split equally among the active Requirements it covers, exactly as 5.3 does.
    - It is a Conflict when both are above 0 and |E − A| > 30% of A. Exactly 30% is not a Conflict; test the boundary.
    - Positions: one per agent with hours, plus an Estimate position ("Estimate v3", allocated hours).
  - The Estimate is read only when detection runs. Editing the Estimate doesn't re-detect; the next assessment run does.
- **Model:**
  - `conflicts_conflicts`: `id`, `opportunity_id`, `run_id`, `type` (the 8 epic types), `severity` (`low | medium | high | critical`), `status` (`open | negotiating | resolved | escalated`), `detected_by` (`rule | semantic | critic | red_team`), `fingerprint`, `summary`, `previous_conflict_id`, `resolution_reason`, `resolved_at`, `detection_pass`, `row_version`, `created_at`. Unique on (`run_id`, `detection_pass`, `fingerprint`).
  - `conflicts_positions`: `conflict_id`, `position`, `source` (`assessment | estimate`), `assessment_id` + `assessment_version` (null for the Estimate), `estimate_version_id` + `estimate_version` (null for an Assessment), `agent` (null for the Estimate), `summary`, `value` (hours `numeric(10,1)` or null), `requirement_id`, `requirement_version`.
  - Grants as in 5.8: SELECT/INSERT, UPDATE only on the status and resolution columns, no DELETE.
- **`raise_conflict(uow, …)`** is the single public write. It is idempotent per (`run_id`, `detection_pass`, `fingerprint`).
- **Retry (decided 2026-10-07: each finish is a new pass):** every time a run reaches a final status, including again after a task retry, is a new detection pass of that run (pass 1, 2, …). It is handled exactly like a new run: Conflicts still present are carried forward with fresh positions, gone ones are resolved, and one that comes back is raised again. Calling detection twice for the same pass adds nothing. The fingerprint is the rule id plus the Requirement id (none for (b)) plus, for (a), the sorted agents.
- **Rerun (AD-27):** after the rules run for a run, each `open` Conflict from an earlier run whose fingerprint is no longer raised becomes `resolved` by the system with the reason "No longer present in <Agent> Assessment v<n>". One whose fingerprint is raised again is closed as carried forward (not listed), and the new Conflict links it through `previous_conflict_id`.
- **Reads:**
  - `conflicts.list_open(uow, opportunity_id)` returns open and escalated Conflicts.
  - `GET /opportunities/{id}/conflicts` (readers, through `opportunities.readable_resource`) returns `{conflicts: [...], open_count}`. Each Conflict carries its positions, with Requirement chips (`R<n>` and excerpt, or `Superseded`) and Assessment versions. The list is ordered with open before resolved, then critical → low, then newest first.
- **Trace:** `conflicts.conflict.detected` (type, severity, `detected_by`, position count) and `conflicts.conflict.resolved` (reason kind `no_longer_present`). Actor `system`. No Requirement or Finding text.
- **Web:**
  - `[id]/conflicts.tsx` has **Open** and **Resolved** sections of 32px rows: type, severity pill, status pill (icon plus label: Open in blocker colour, Resolved, Escalated with arrow-up), and the positions summary ("Engineering: 24 h · PM: not sized").
  - Selecting a row opens an inspector with equal-width position cards. Each card shows the agent by role, the value in tabular figures, a Requirement chip and "Engineering Assessment v2".
  - Keyboard (`j`/`k`, arrows, Enter) and axe as in the Red Team list.
  - Empty: "No Conflicts between the specialist Assessments."
  - The Conflicts tab label shows the open-plus-escalated count, loaded with the workspace layout. It refreshes on navigation and `router.refresh()`; there is no SSE.
  - Read-only for everyone.
- **Privacy:** no Requirement or Finding text in logs or trace.

**Never:**
- No resolving or escalating (6.3, deferred) and no new identity action.
- No LLM or semantic detection (6.2), no Critic or Red Team input, no Negotiation.
- No submission blocking (`estimates.get_submission_blockers` stays as it is).
- No mandatory-constraint rule: no Checklist exists yet.
- No timeline, resource or range rules, and no Assessment schema change.
- No SSE, no plan template v2, no eval fixtures.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | Run finishes; Eng sizes R4 at 24 h, PM omits R4 | One open `scope` Conflict, two positions, one trace event | N/A |
| Agree | Assessments raise no rule | No Conflict; tab shows the empty state | N/A |
| Idempotent | Detection runs twice for the same pass | No duplicate Conflict or trace event | N/A |
| Retry pass | Security retried to `do_not_proceed` after a clash between Eng and PM | Pass 2 carries the clash forward with Security's position; the pass 1 Conflict is not listed | N/A |
| Gone on rerun | New run; PM now sizes R4 | The earlier Conflict is `resolved`, reason "No longer present in PM Assessment v2" | N/A |
| Still there | New run; same disagreement | New open Conflict linking the previous one; the previous one is not listed | N/A |
| Clash | Eng `proceed`, Security `do_not_proceed` | One `assumption` `high` Conflict, no Requirement, a position per agent | N/A |
| Effort boundary | R2: A 100 h, E 130 h / 131 h | No Conflict / one `effort` Conflict with agent positions and an Estimate position | N/A |
| No Estimate | No draft yet | Rule (c) raises nothing; (a) and (b) still run | N/A |
| Partial run | Security task failed | Rules use each agent's current Assessment (Security's earlier one, or none) | N/A |
| Who | Sales rep / non-member reads | 200 / 404 as other tabs | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/application/assessment.py`:
  - `finish_run` (:292) is the hook site, after `trace.append` (about :313–320). It is called from `_run`'s no-Requirements path (about :785) and its final Unit of Work (about :812).
  - A task retry (`requeue_task` :197) calls it again for the same run.
- `assessments/application/public.py`: add a principal-free `current_assessment_snapshots(uow, opportunity_id)`, giving each agent's current Assessment id, version, recommendation and effort `{requirement_id, requirement_version, hours}`.
- `estimates/application/line_refs.py`: `LineRef` has no Requirement coverage. Add the line's covered Requirement ids, from the line→Requirement link table the `LineRequirement` view already reads, so `current_version_lines` can feed rule (c).
  - `finish_run` reads it through `estimates.application.public`, as the Red Team does, and passes an Estimate snapshot (version id, version number, lines with hours and Requirement ids) into the detector.
  - `finish_run` passes these as DTOs defined in `conflicts.application.public` into `conflicts.detect_for_run(uow, opportunity_id, run_id, snapshots, estimate)`, so `conflicts` imports neither `assessments` nor `estimates`. That keeps 8.6's later `estimates → conflicts` blocker read free of cycles.
  - Use a function-level import in `finish_run` if lint-imports needs it.
- Mirror `backend/app/modules/assessments/` layers (`domain/`, `adapters/models.py` + repository, `application/`, `api/routes.py`, `public.py`).
- **Wiring:**
  - `modules/__init__.py:12–17`
  - `main_api.py` (:14 import, :124 router)
  - `migrations/env.py:14`
  - `platform/trace/catalogue.py` (`@register` as at :466)
  - `pyproject.toml` import-linter: a new `conflicts` contract, with `conflicts` added to the other modules' contracts (assessments is at :168–190)
  - Not `main_worker` (no job).
- Migration `0021_conflicts`, `down_revision = "0020_opportunities_imports"`.
- `intake.application.public.requirement_version_texts` for the chip excerpts, as the red-team read does.
- **Web:**
  - `[tab]/page.tsx`: add the `conflicts` branch.
  - New `[id]/conflicts.tsx`, `components/opportunities/conflicts-list.tsx`, `conflict-inspector.tsx`, `lib/conflicts.ts`.
  - Reuse `severity-pill.tsx`, the `red-team-list.tsx` keyboard model and `assessment-finding-inspector.tsx` layout.
  - Badge: `[id]/layout.tsx` fetches the count and passes it to `workspace-tabs.tsx`.
  - Regenerate `schema.d.ts` from a local uvicorn (not Docker).
- Don't touch: `estimates.get_submission_blockers`, identity actions, `seed_auth0.py`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/conflicts/**`, migration 0021, wiring, catalogue, import-linter -- module, rules, `raise_conflict`, `detect_for_run`, `list_open`, GET route
- [x] `backend/app/modules/assessments/application/{assessment,public}.py` -- snapshots read and the `finish_run` hook
- [x] `backend/tests/test_conflicts_rules.py` (pure) and `test_conflicts*.py` (Postgres, fake gateway) -- every matrix row, the grants (no DELETE)
- [x] Web: schema, the tab route, list, inspector, badge, and tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity after an assessment run where agents disagree, when the Conflicts tab opens, then it lists each Conflict with its type, severity, status and both positions, and the tab label shows the open count.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- The severity enum is `ConflictSeverity` in the OpenAPI schema (same values as `Severity`): a second enum named `Severity` would make FastAPI rename both schemas with module prefixes and break the web types.
- Carried forward: the earlier Conflict is set `resolved` with the reason "Still present: carried forward to a later run." and hidden from the list because a newer Conflict links it. Its `conflicts.conflict.resolved` event uses `reason_kind` `carried_forward`, so every status change has a trace event; `no_longer_present` is as specified.
- "No longer present in <Agent> Assessment v<n>" names the sources whose position reads differently now (for example the PM that now sizes R4), then falls back to sources at a newer version, then to every source's current version.
- Rule (a) and (c) only consider active Requirements. Rule (b) positions cover every agent with a current Assessment.
- Each detection pass of a run is 1 + the highest `detection_pass` stored for that run. An earlier pass of the same run is carried forward or resolved exactly like an earlier run.
- Conflicts from one detection share `created_at`, so the list breaks ties by Requirement order (Opportunity-level Conflicts first), then id.
- The tab's status pill is its own component, `conflict-status-pill.tsx`, which the list and the inspector share.

## Spec Change Log

- **Loop 1 (review #1–#2, intent gap):** same-run re-detection after a task retry kept the first pass's Conflict and positions. The human chose "each finish is a new pass" and "amend in place" (no revert). Amended (frozen, with approval): `detection_pass` column, uniqueness (`run_id`, `detection_pass`, `fingerprint`), the Retry rule, and the Idempotent / Retry pass matrix rows. Avoids: stale positions and summaries after Retry, and a returning Conflict stuck as resolved. KEEP: everything else in the implementation (rules, resolution reasons, carry-forward, read API, web tab, inspector, badge, tests).

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | edge | Same-run re-detection after a task retry returns the existing (run, fingerprint) Conflict untouched, so its positions/summary keep the pre-retry Assessment (e.g. a clash missing Security's new `do_not_proceed`, an effort sum without Security's hours) | medium | intent_gap → resolved | Human decided 2026-10-07: each finish is a new detection pass (frozen block amended). `raise_conflict` early-returns on `get_by_fingerprint(run_id, fp)`; `requeue_task` re-finishes the same run, so `detect_for_run` reruns with the same `run_id`; frozen block fixes uniqueness on (`run_id`, `fingerprint`), so changed positions cannot be stored. |
| 2 | blind+edge | Conflict raised, resolved as gone on a retry, raised again on a later retry of the same run stays resolved | low | intent_gap | Same root cause as #1 (same-run key returns the resolved row); grouped; fixed by the same decision. |
| 3 | blind | Detection on failed/cancelled/stale runs re-inserts every open Conflict as carried forward, with two trace events each | low | reject | Real trace noise, but the frozen block says detection runs "whenever the run reaches a final status"; skipping failed runs contradicts it, and carried-forward rows are hidden. |
| 4 | blind | A detection exception rolls back the run's completion | false | reject | No reachable failure shown: rules are pure and tested; loud failure on an undemonstrated state is correct behaviour. |
| 5 | blind+vgap | Ties within section+severity of one run fall to `str(id)`, so same-run Conflicts list in random order, not Requirement order; and "newest first" is untested | low | patch | `created_at` is the transaction start, equal for one detection; seen every time a run raises two scope Conflicts. Pre-verified gap: no test has two same-section, same-severity Conflicts. |
| 6 | blind | Previous-Conflict lookup is O(candidates × open) | low | reject | Tens of Requirements in practice; the fix restructures `raise_conflict`. |
| 7 | blind | Allocation duplicated in Python and TypeScript with no contract test | low | reject | Spec asks for "exactly as 5.3"; both are tested to the same cases; a cross-suite fixture adds machinery. |
| 8 | blind | Effort rule ignores a Requirement the Estimate leaves out | false | reject | Frozen rule (c) requires both above 0. |
| 9 | blind | Inspector detects inactive Requirements by the "Superseded" label | low | reject | Same convention as the other inspectors; no wrong output. |
| 10 | blind | Scope rule finds the "Not sized" position by its label | low | reject | Correct today; developer-only, no named break. |
| 11 | blind+edge | `negotiating`/`escalated` not handled by carry-forward, resolve-as-gone, badge wording | false | reject | No 6.1 path sets those statuses (6.3 is deferred); unreachable now. Note for 6.3. |
| 12 | blind | Clash fingerprint constant; summary does not name the agents | low | reject | Positions name each agent; fresh positions per run. |
| 13 | blind | Row chip may use an older Requirement version than the Estimate position | low | reject | Needs a Requirement edit between the Assessment and the Estimate; rare. |
| 14 | blind | `_trace_resolved(kind: str)` maps unknown kinds to `no_longer_present` | false | reject | Only two literal call sites; no wrong event is written. |
| 15 | blind | Inspector columns don't wrap in a narrow pane | low | reject | The workspace inspector is desktop-width; 4 cards still render. |
| 16 | vgap | No test for a failed `GET …/conflicts` (tab message, layout badge) | medium | patch | Pre-verified: every sibling tab has one; Conflicts has none. |
| 17 | vgap | `Superseded` chip label untested in conflicts | medium | patch | Pre-verified: sibling modules test it; conflicts does not. |
| 18 | vgap | The "every source" fallback of the no-longer-present reason is untested | low | patch | Pre-verified: only the changed/newer steps are tested. |
| 19 | vgap | `assessments.public.current_assessment_snapshots` exported but unused | low | patch | Grep: only the definition and `__all__`; delete it. |
| 20 | edge | Scope rule treats a 0 h row as sized | false | reject | `assessments_effort` CHECK `hours >= 0.5`. |
| 21 | edge | `hours_for` picks an arbitrary row among several versions | false | reject | Unique (`assessment_id`, `requirement_id`). |
| 22 | edge | Layout hides the badge on a load error, same as zero | low | reject | The tab itself shows the error message. |
| 23 | r2 blind+edge | Detection exception rolls back the run's completion | false | reject | carried #4. |
| 24 | r2 blind+edge | `negotiating`/`escalated` not handled by carry-forward or gone | false | reject | carried #11. |
| 25 | r2 blind | Effort rule silent when the Estimate has 0 h for a sized Requirement | false | reject | carried #8. |
| 26 | r2 blind | Every run re-inserts carried-forward rows and trace pairs | low | reject | carried #3 (by the frozen carry-forward and pass rules). |
| 27 | r2 blind | Per-candidate `open_conflicts` query | low | reject | carried #6. |
| 28 | r2 blind | `_trace_resolved(kind: str)` untyped | false | reject | carried #14. |
| 29 | r2 blind | "Superseded" magic label in the inspector | low | reject | carried #9. |
| 30 | r2 blind | A pass that could not evaluate a rule (no Estimate, a missing Assessment) resolves that rule's Conflicts | false | reject | Once drafted, a current Estimate version always exists; a failed task keeps the agent's previous Assessment current, and Assessments are never deleted, so a rule's inputs never vanish after it raised a Conflict. |
| 31 | r2 blind | `hours_for` matches any Requirement version, comparing old-version hours with the current Estimate | low | reject | Same as the 5.3 comparison (matches by Requirement id); frozen says "as in 5.3"; unique per Assessment and Requirement (#21). |
| 32 | r2 blind | Trace tab labels a carry-forward as "Conflict resolved"; `previous_conflict_id` unused in the UI | low | reject | The status really changes; payload carries `reason_kind`; first-raised date is not in the intent. |
| 33 | r2 blind | Unknown agent makes `AGENTS.index` raise in `finish_run` | false | reject | `assessments_assessments.agent` has a CHECK limiting it to the three known agents. |
| 34 | r2 blind | Badge stale when a run finishes while on the Assessments tab | false | reject | The Assessments section calls `router.refresh()` on run completion, which re-renders the layout and its count. |
| 35 | r2 blind | Agents' sum adds overlapping work | false | reject | Frozen rule (c) and 5.3: the agents size different work and add up. |
| 36 | r2 blind | Grants test doesn't prove column-level UPDATE limits | low | reject | Grants are set in the migration as specified; extra probes are unlikely to catch an everyday regression. |
| 37 | r2 edge | Selected Conflict carried forward leaves an empty right pane | false | reject | The list never refreshes in place (no polling); new data arrives only on navigation, which remounts the list and clears the selection. |
| 38 | r2 edge | Spec task names `assessments/application/public.py` but it's unchanged | low | reject | The fix edits this build's spec; the export was removed on purpose (#19). |
| 39 | r2 vgap | No test that closing the pane after a keyboard open returns focus to the row | medium | patch | Pre-verified: siblings test it; conflicts tests never close the pane. |
| 40 | r2 vgap | No integration test for a Conflict that comes back after being resolved | medium | patch | Pre-verified: no test re-raises after a resolve; the path triage #2 concerned. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
