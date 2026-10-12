---
title: 'Story 6.3 (demo slice): Resolve or escalate a Conflict with a reason'
type: 'feature'
created: '2026-10-07'
status: 'done'
baseline_commit: '31b2132c21e79d371c9d53393d4ecf016664b7e4'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-1-conflicts-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Conflicts tab shows disagreements between the agents (and the Estimate), but nobody can settle one, so the decision and the dissenting view are never recorded (FR-31).

**Approach:** From the Conflict inspector, a presales engineer resolves a Conflict, either by choosing one of its positions or by entering a different one, with a required reason. Alternatively, they escalate it with a reason to a named reviewer on the Opportunity, who then resolves it. Every original position is kept and traced.

## Boundaries & Constraints

**Always:**
- **Depends on:** 6.1 (Conflicts, detection passes), 8.3 (Estimate markers read open and escalated Conflicts), 1.8 (Overview).
- **Commands (each takes the Conflict's `row_version` via If-Match, as 8.2's `edit_line` does: 428 without it, 412 "Changed by {name} since you opened it." on a stale one; each writes and traces in one Unit of Work):**
  - `conflicts.resolve_conflict(actor, conflict_id, choice, reason)` works on an `open` or `escalated` Conflict. `choice` is either a position number of the Conflict or `{entered: text}` (1–200 characters).
    - It sets `resolved`, `resolved_at`, `resolution_reason` (the reason, 1–1,000 characters), `resolved_by` and the choice: `chosen_position` or `entered_position`.
    - It traces `conflicts.conflict.resolved` with `reason_kind` `decided`, the actor, the reason, the choice and every original position's summary.
  - `conflicts.escalate_conflict(actor, conflict_id, reviewer_id, reason)` works on an `open` Conflict.
    - `reviewer_id` must be the Opportunity's owner or a collaborator, other than the actor; otherwise 422.
    - It sets `escalated`, `escalated_to`, `escalation_reason`, `escalated_by` and `escalated_at`.
    - It traces `conflicts.conflict.escalated` (actor, reviewer, reason).
  - A missing or blank reason gets 422 problem+json; the web blocks it inline first.
  - A Conflict already `resolved` gets 409 `conflict_already_resolved`.
- **Who:** new actions `conflicts.conflict.resolve` and `conflicts.conflict.escalate`, granted to owner and collaborators except sales representatives, like the estimate writes (no Auth0 permission). An escalated Conflict can also be resolved by its `escalated_to` reviewer. Everyone else gets 403 and doesn't see the actions.
- **Schema (migration `0023_conflicts_resolution`):**
  - New nullable columns `resolved_by`, `chosen_position`, `entered_position`, `applied_hours`, `escalated_to`, `escalated_by`, `escalated_at`, `escalation_reason`.
  - Column UPDATE grants on the new columns (still no DELETE).
  - Checks: an escalation's columns are all set or all null; at most one of chosen and entered.
  - The trace payloads take an optional `run_id`.
- **Reruns, resolved by a person (decided 2026-10-07: the decision stands):**
  - When a pass raises a fingerprint whose latest Conflict was resolved by a person (`decided`), nothing new is raised while every Assessment position reads the same as it did then. Estimate positions are not compared, since the decision may itself have changed the Estimate.
  - If any Assessment position reads differently, a new `open` Conflict is raised. It links the resolved one through `previous_conflict_id`, and the resolved one stays listed. The new one shows "Resolved earlier by Alex; positions have changed."
- **Reruns, escalated (amended 2026-10-07):**
  - **Gone:** if the next pass no longer raises its fingerprint, the system resolves it as in 6.1 ("No longer present in …").
  - **Same figures:** if it raises it again and every Assessment position reads the same, the escalation stays as it is, with no duplicate.
  - **Changed figures:** if any Assessment position reads differently, a new Conflict is raised with the fresh positions.
    - It is linked to the escalated one through `previous_conflict_id`.
    - It is already `escalated` to the same reviewer, with the same reason, `escalated_by` and `escalated_at`.
    - The old one is closed as carried forward and is no longer listed.
  - The carry-forward lookup and the "gone" set include `escalated`.
- **Applying an effort decision to the Estimate (decided: apply to the line):** this happens only when resolving an `effort` Conflict, in the same Unit of Work.
  - **What the line gets:**
    - Choosing the Estimate's position: the line is unchanged.
    - Choosing any agent's position: the line gets the agents' total for that Requirement (the Conflict's compared figure).
    - Entering a position: for an effort Conflict it must be hours, 0–2,000 at 0.1 (otherwise 422), and the line gets those hours.
  - **How:** an 8.2 line edit of the current draft's line covering that Requirement. The effort hours are set and the role mix is unchanged. The edit reason is the resolution reason and the editor is the actor. The line shows Edited and is carried to later versions as 8.2 does.
  - **When it applies:** only if exactly one line of the current draft covers the Requirement and that line covers only it. Otherwise the decision is recorded and `applied` is false, and the inspector says "Not applied: the Estimate line covers several Requirements." (or "…no Estimate line covers it.").
  - The resolution stores `applied_hours` (null when not applied) and the trace names the line.
  - Scope and recommendation decisions never change the Estimate.
- **Read API:** `ConflictView` adds:
  - `row_version`;
  - `resolved_by_name`, `chosen_position`, `entered_position`, `applied_hours`, and the `previous_decision` (who, when) for a re-raised Conflict;
  - `escalated_to` / `escalated_by` (`{id, name}`), `escalation_reason`, `escalated_at`;
  - `can_resolve` and `can_escalate`;
  - the reviewer options: owner and collaborators, without the viewer.
- **Web:**
  - **Resolve / Escalate:** the inspector of an open or escalated Conflict gets a choice of positions (radio cards on the existing equal-width cards, plus "A different position" with a text field) and a required reason textarea, then **Resolve**. An open Conflict also has **Escalate** (reviewer select plus reason).
  - **Errors:** the 412 message with **Reload** (`router.refresh()`), and inline 422 and 403 messages.
  - **After a write:** `router.refresh()`, so the badge, the Open and Resolved sections and the Estimate markers update.
  - **Resolved:** a resolved Conflict shows the decision ("Resolved by Alex: Engineering's position, 64 h", or the entered text), its reason, and every position.
  - **Escalated:** the row and inspector show "Escalated to Sam".
  - **Overview:** "Needs attention" lists escalated Conflicts naming the reviewer, linking to the Conflicts tab. Recent activity labels `conflicts.conflict.escalated` ("Conflict escalated").
  - Keyboard and axe as in 6.1.
- **Privacy:** no reason, position or Requirement text in logs. The trace carries them as the epic requires (FR-31); position summaries are hours, labels or "Not sized".

**Never:**
- No Inbox item (9.2), no notifications, no SSE (refresh only), and no Negotiation status.
- No change to the Estimate from scope or recommendation decisions.
- No reopening a resolved Conflict by hand.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Choose | Open effort Conflict; choose position 1, reason | `resolved`, `chosen_position` 1, `resolved_by` me; trace with all positions; leaves Open; badge −1 | N/A |
| Apply agents | Effort Conflict on R1: agents 96 h, Estimate 40 h; choose Engineering's position | Line R1 set to 96 h as an Edited line with the reason; `applied_hours` 96; marker gone | N/A |
| Apply entered | Effort Conflict; enter "48" | Line set to 48 h | N/A |
| Bad hours | Effort Conflict; enter "about two days" | Nothing changes | 422 |
| Keep Estimate | Choose the Estimate's position | Resolved; the line is unchanged | N/A |
| Shared line | The Requirement's line covers two Requirements | Resolved, not applied, with the note | N/A |
| Enter (scope) | Scope Conflict; enter "In scope: PM to size in v2" | `entered_position` stored and shown; Estimate unchanged | N/A |
| Decision stands | Resolved; the next run gives the same agent figures | No new Conflict | N/A |
| Figures changed | Resolved; the next run, Engineering now says 80 h | New open Conflict linking the resolved one, with "Resolved earlier…" | N/A |
| No reason | Blank reason | Blocked inline | 422 problem+json |
| Stale | Another user resolved it first | Nothing overwritten | 412 + Reload |
| Escalate | Escalate to a collaborator, reason | `escalated`, reviewer shown on row and Overview; trace | N/A |
| Bad reviewer | Reviewer not on the Opportunity, or myself | Nothing changes | 422 |
| Reviewer resolves | The assigned reviewer, who is a collaborator, resolves | Resolved with the reviewer as actor | N/A |
| Who | Sales rep resolves or escalates | Actions hidden | 403 |
| Escalated rerun | Escalated; still raised with the same agent figures / gone | Stays escalated, no duplicate / resolved by the system | N/A |
| Escalated, figures changed | Escalated to Sam; the next run, Engineering now says 80 h | New Conflict with the fresh positions, escalated to Sam with the same reason, linking the old one; the old one is no longer listed | N/A |
| Already resolved | Resolve a resolved Conflict | Nothing changes | 409 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/conflicts/adapters/models.py:32-77`:
  - The checks (:51-54) tie `resolution_reason` to `resolved_at`. Escalation gets its own columns.
  - `row_version` is a plain int.
- Migration `0021_conflicts.py:156-163` holds the grants. Add `0023_conflicts_resolution` (down `0022_estimates_from_assessments`).
- `conflicts/adapters/repository.py`:
  - `resolve` (:206) only covers `open`, with no version check. Add guarded `decide` / `escalate` updates that check `row_version`.
  - `open_conflicts` (:185) defaults to `("open",)`.
  - `listed_conflicts` (:223).
- `conflicts/application/conflicts.py`:
  - `raise_conflict` (:90-164) looks for the previous Conflict among `open` only (:106-112).
  - `detect_for_run`'s "gone" set (:228-232).
  - `get_conflicts` adds the new view fields; `open_by_requirement` (:279) stays BLOCKING.
- `domain/conflicts.py:52-54`: `UNRESOLVED` / `BLOCKING`.
- `conflicts/api/routes.py:34`: GET only today. Add:
  - `POST /opportunities/{id}/conflicts/{conflict_id}/resolution`
  - `POST …/escalation`
  - both with If-Match and an ETag on the response, like `estimates/api/routes.py:162-220`.
- Applying to the Estimate: add a principal-free `estimates.application.public.apply_decision(uow, actor, opportunity_id, requirement_id, hours, reason)` built on `line_edits.py`'s edit path (the same columns, trace and carry rules). It returns the line id, or None when no single line covers only that Requirement. Conflicts → estimates is a new import; estimates already imports conflicts' public module (8.3 `open_by_requirement`), so call it through a function-level import or invert it by passing a callback from the route layer. Pick whichever keeps lint-imports green.
- Pattern to copy: `estimates/application/line_edits.py:103-200` (`_authorized`, `parse_if_match`, `_stale`, guarded update, `trace.append(subject_version=)`). Helpers in `platform/concurrency.py:39-44`.
- Trace: `platform/trace/catalogue.py:517-525`. `ConflictsConflictResolved` gets `reason_kind` `decided`, `run_id` optional, plus the decision fields. Add `ConflictsConflictEscalated`.
- Identity:
  - `identity/actions.py:15-33`;
  - `domain/policy.py` `OWNER_GRANTS` / `MEMBER_GRANTS` (:81-116), `RELATION_EXCLUDED_ROLES` (:66-79);
  - `tests/test_authorize.py` pins the grant sets.
  - The reviewer check uses `readable_resource`'s `owner_id` / `member_ids`.
- Web:
  - `components/opportunities/conflict-inspector.tsx:88-133`: positions, then the form.
  - `conflicts-list.tsx` (row "Escalated to").
  - `app/opportunities/[id]/conflicts.tsx` (passes `getOpportunity` people).
  - `app/opportunities/actions.ts`: `resolveConflict` and `escalateConflict`, modelled on `editEstimateLine` :1517-1570.
  - Reload UI: `assumptions-register.tsx` / `collaborators.tsx:125`.
  - Overview: `lib/overview.ts:26-111` (new `escalated-conflict` attention kind) and `app/opportunities/[id]/overview.tsx:30` (fetch Conflicts).
  - `lib/trace.ts:19-55` (escalated label).
  - Regenerate `schema.d.ts` from a dumped `app.openapi()`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/conflicts/**`, migration 0023, identity actions and policy, catalogue -- the commands, rerun handling, routes and view fields
- [x] `backend/tests/test_conflicts_resolution*.py` (+ `test_authorize.py`) -- every matrix row, the grants (no DELETE)
- [x] Web: schema, actions, inspector form, row and Overview escalation, trace label, and tests with axe

**Acceptance Criteria:**
- Given an open effort Conflict on the demo Opportunity, when the presales engineer chooses the agents' position with a reason, then it moves to Resolved showing the decision, the reason and every position, the badge drops, and the Estimate line shows the agents' hours as Edited with no Open Conflict marker.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Estimate link:** `conflicts` still never imports `estimates` outside its routes. `conflicts.api.routes` passes `EstimateLink(lock=estimates.lock_for_decision, apply=estimates.apply_decision)` into `resolve_conflict`; import-linter has one `ignore_imports` edge for it. The Estimate draft lock is taken before the Conflicts lock, the same order as `finish_run` (8.3 build, then detection), so the two can't deadlock.
- **`apply_decision`** (in `line_edits.py`) returns `AppliedDecision(line_id, not_applied)` (a `conflicts.public` DTO) instead of a bare line id, so the inspector can tell "covers several Requirements" (`shared_line`) from "no Estimate line covers it" (`no_line`); a third kind, `several_lines`, covers two lines each covering only the Requirement. The agents' total is applied rounded to 0.1 h even above the 2,000 h a typed edit allows.
- **Line edit reason:** a decision reason over 300 characters is cut to 300 with "…" on the line edit (8.2's limit); the Conflict keeps the full reason.
- **Escalated, figures changed (Loop 1):** `insert_conflict` takes the escalated Conflict and copies its reviewer, reason, by and at onto the new one; the old one is resolved as carried forward.
- **FR-64 on the Estimate:** a resolver without `estimates.estimate_line.edit` (a sales-representative reviewer) resolves an `effort` Conflict with `not_applied` `not_permitted` ("Not applied: you can't edit the Estimate.").
- **`previous_decision`** is set only on unresolved Conflicts.
- **`not_applied` has no column:** the view reads it back from the decision's `conflicts.conflict.resolved` trace payload.
- **Decided Conflicts stay listed:** the "carried forward" filter skips a linked Conflict only when nobody decided it. `previous_decision` follows the links through carried-forward Conflicts to the decided one.
- **Order of checks:** 404 (Opportunity, Conflict) → 403 → 428/412 (If-Match) → 409 (resolved; escalating a non-open one) → 422 (reason, choice, reviewer). A stale `If-Match` on a Conflict someone already resolved is 412, a current one is 409 `conflict_already_resolved`; escalating an escalated Conflict is 409 `conflict_not_open`.
- **Trace payloads:** `ConflictsConflictResolved` keeps one shape, so system events now carry the decision fields as null.
- **Web:** the reviewers come from the Conflicts read (`ConflictsView.reviewers`), not `getOpportunity`. Escalate sits in a `<details>` under the Resolve form; Overview ranks escalated Conflicts with high Findings.

## Spec Change Log

- **Loop 1 (review: escalated Conflict keeps stale figures, intent gap):** an escalated Conflict re-raised with changed agent figures kept its old positions, so the reviewer decided on them and an effort decision applied an out-of-date agents' total. The human chose "re-raise, keep the reviewer" and to amend in place (no revert). Amended (frozen, with approval): the "Reruns, escalated" rule and the escalated matrix rows. This avoids decisions on stale figures. KEEP: everything else in the implementation.

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+vgap | Escalated Conflict re-raised with changed figures keeps stale positions; an effort decision applies an out-of-date agents' total | medium | intent_gap → resolved | Frozen rule said "the escalation stays as it is"; human chose re-raise keeping the reviewer (frozen amended, Change Log loop 1). |
| 2 | blind+edge | 422 body checks run before 428/412/409 | medium | patch | `resolve_conflict`/`escalate_conflict` validate reason/choice/reviewer before `_checked_version`; stale saves show a validation error instead of Reload. |
| 3 | edge | Decision reason up to 1,000 chars written as the line's 8.2 `edit_reason` (limit 300) | low | patch | `estimates/domain/estimates.py` REASON_MAX 300 is app-only; direct cut fixes it. |
| 4 | blind | Choosing one agent's card applies the agents' total, unexplained before submit | medium | patch | Frozen rule; the form shows only that agent's hours, so the applied 100 h looks contradictory. |
| 5 | vgap | Cross-Opportunity / unknown Conflict ids untested on the write endpoints | medium | patch | Pre-verified: `_load`'s opportunity check has no test. |
| 6 | vgap+blind | `no_line` / `several_lines` outcomes never exercised | medium | patch | Pre-verified. |
| 7 | vgap | No test that the tab passes `opportunityId` to the forms | medium | patch | Pre-verified: default `""` hides the forms. |
| 8 | vgap | `resolveConflict`/`escalateConflict` actions untested | medium | patch | Pre-verified: both are mocked everywhere. |
| 9 | vgap | Overview escalated items and the failed Conflicts read untested on the page | medium | patch | Pre-verified. |
| 10 | blind+edge | Missing agent values give a partial total | false | reject | Effort Conflict positions are only agents that sized it (plus the Estimate); "Not sized" appears only in scope Conflicts, which never apply. |
| 11 | edge | Effort decision with no Requirement on any position records nothing | false | reject | Effort positions always carry the Requirement (6.1 rule (c)). |
| 12 | blind+edge | `_view`'s `next()` can raise StopIteration → 500 | false | reject | A Conflict just decided can't be linked as previous by a newer one in the same Unit of Work. |
| 13 | edge | `negotiating` status paths (409 text, duplicates, pragma branch) | false | reject | Nothing sets `negotiating` (Negotiation is Epic 14). |
| 14 | blind | A decision is lost if the newest Conflict of that fingerprint was system-resolved | low | reject | Needs decide → change → gone → back to the old figures; rare. |
| 15 | blind | Locks taken before the permission check | low | reject | Held only until the 403 rolls back. |
| 16 | blind | `not_applied` read back from the trace, not a column | low | reject | The frozen schema lists the columns exactly; documented in Implementation Notes. |
| 17 | blind | Missing DB checks (escalated ⇒ reviewer, decision ⇒ resolved_by) and index | low | reject | Only the commands write these columns, guarded and tested. |
| 18 | blind | Escalation can't be reassigned or withdrawn | false | reject | Not in the intent. |
| 19 | blind | `no_line` also covers "no draft" | low | reject | After 8.3 a draft exists once a run sized anything. |
| 20 | blind | Missing tests: 412/428 on escalation, reader 403, carry_edits, Estimate-only change | low | reject | Same code paths as tested resolve paths; 8.2 carry already tested. |
| 21 | blind | Web nits: `rowVersion >= 0`, `not_applied` as string, focus to the entered field | low | reject | No reachable wrong behaviour. |
| 22 | blind | Overview loads the whole Conflicts read | low | reject | One extra read per Overview load. |
| 23 | edge | 412 message names the escalator after a system resolve | low | reject | Rare; message still says it changed. |
| 24 | edge+vgap | A sales-rep reviewer retrying a resolved Conflict gets 403, not 409 | low | reject | Rare; still refused. |
| 25 | r2 blind | An escalated sales-rep reviewer's effort decision edits the Estimate line without `ESTIMATE_LINE_EDIT` (FR-64 bypass) | medium | patch | `may_resolve` admits the reviewer; `apply_decision` has no line-edit check; the existing test picks the Estimate's own position. |
| 26 | r2 edge | A resolved Conflict that links an earlier decision still shows "Resolved earlier…" | low | patch | Direct: only unresolved Conflicts get `previous_decision`. |
| 27 | r2 blind+edge | Docstring claims version/status are checked before the body; FastAPI validates the schema first | low | patch | Wording correction. |
| 28 | r2 vgap | `previous_decision` across a carried-forward Conflict untested | medium | patch | Pre-verified: only one hop tested. |
| 29 | r2 vgap | Estimate-only change between runs untested | medium | patch | Pre-verified. |
| 30 | r2 vgap | `can_escalate` True/False by reviewer availability never asserted | medium | patch | Pre-verified. |
| 31 | r2 vgap | Agents' total above 2,000 h untested | low | reject | Rare; documented in Implementation Notes. |
| 32 | r2 blind | An effort decision with no Requirement on any position reports nothing | false | reject | carried #11. |
| 33 | r2 blind+edge | 412 names the escalator after a system resolve | low | reject | carried #23. |
| 34 | r2 blind | Resolve route documents `conflict_not_open` | low | reject | OpenAPI wording only. |
| 35 | r2 blind | `not_applied` only in the trace | low | reject | carried #16. |
| 36 | r2 blind | Missing status-tied DB checks | low | reject | carried #17. |
| 37 | r2 blind | Escalation can't be withdrawn; reviewer may leave | false | reject | carried #18. |
| 38 | r2 blind | An Estimate change after a decision is never noticed | false | reject | Frozen: Estimate positions are not compared. |
| 39 | r2 blind | Reload after a 412 loses the typed reason | low | reject | The 412 is rare; the reason is short to retype. |
| 40 | r2 blind | Focus not moved to the first invalid field in all cases | low | reject | carried #21 (inline errors are shown and described). |
| 41 | r2 blind | Choosing one agent's card applies the total; the label after resolving shows that agent's hours | low | reject | Fixed before submit by #4's hint; the resolved view also shows the applied hours. |
| 42 | r2 blind | `rowVersion >= 0`; concurrency test; recommendation decision test; `overview.tsx` indentation | low | reject | No reachable wrong behaviour; lint clean. |
| 43 | r2 edge | Non-ASCII digits accepted as hours | low | reject | Unlikely input; stored as typed. |
| 44 | r2 edge | A NUL character in the reason gives 500 | low | reject | Not typeable in the form. |
| 45 | r2 edge | A sales-rep reviewer on a just-resolved Conflict gets 403 | low | reject | carried #24. |
| 46 | r2 edge | A line also linking an inactive Requirement reads as shared | low | reject | Rare. |
| 47 | r2 edge | `negotiating` duplicates | false | reject | carried #13. |
| 48 | r2 edge | No If-Match + invalid schema body → 422 | low | reject | FastAPI order; docstring now says so (#27). |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
