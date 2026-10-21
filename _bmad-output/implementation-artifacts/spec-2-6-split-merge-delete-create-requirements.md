---
title: 'Story 2.6 (remainder): Split, merge, delete and create Requirements'
type: 'feature'
created: '2026-10-21'
status: 'done'
baseline_commit: '135fc762a6031d864d9a125a7bfe5dc48883d313'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-6-edit-and-confirm-requirements.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-7-incremental-intake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The presales engineer can edit and confirm Requirements but cannot shape the list: they cannot split a compound Requirement, merge duplicates, remove a wrong one, or add one the extraction missed. After a 412 they also cannot see what changed (FR-6, AD-11, UX-DR20).

**Approach:** Add create, delete-with-reason, split and merge commands on the Story 2.6 path (authorize → validate → write → trace in one Unit of Work, `If-Match` per Requirement touched), `x` multi-select and `c` in the Requirements list, and **View diff** on the 412 notice. Removed Requirements leave the active list but stay in history and the trace.

## Boundaries & Constraints

**Always:**
- **Who:** every command needs `intake.requirement.edit` (owner and members, not sales representatives: 403). Non-readers get the Opportunity's 404. The UI hides the controls when `can_edit_requirements` is false.
- **Create:** `POST /opportunities/{id}/requirements` with `{text, classification}` (the Story 2.6 text and classification rules). Result: v1, `origin: human`, `locked_by_human: true`, no Evidence, unconfirmed, a history row. Trace `intake.requirement.created`.
- **Delete:** `POST /opportunities/{id}/requirements/{rid}/delete` with `If-Match` and `{reason}` (1 to 500 characters, the `reject_reason` rule). Sets status `deleted` and stores the reason on the row. Trace `intake.requirement.deleted` (version only, never the reason).
- **Split:** `POST /opportunities/{id}/requirements/{rid}/split` with `If-Match` and `{parts: [{text, classification}, {text, classification}]}`, exactly two. Two new Requirements (origin `human`, locked, unconfirmed, each with all of the original's Evidence links); the original becomes `superseded`. Trace `intake.requirement.split` on the original: `{version, into: [id, id]}`.
- **Merge:** `POST /opportunities/{id}/requirements/merge` with `{requirements: [{id, row_version}] (2 to 20, distinct), text, classification}`. No `If-Match` header; each `row_version` is checked and any stale one gives 412 for the whole merge. One new Requirement with the union of the originals' Evidence; every original becomes `superseded`. Trace `intake.requirement.merged` on the new one: `{from: [{id, version}]}`.
- **Removed Requirements** (deleted, split or merged away) leave the active list. Other modules already show linked ones as "Superseded". Their open pending change becomes `superseded` in the same Unit of Work.
- **Re-extraction never revives a removed Requirement:** a proposal whose best match (the Story 2.7 rules) is a `deleted` Requirement is dropped. Split and merge results carry the originals' passages, so proposals match them as usual and, being locked, become pending changes.
- **Decision (human, review):** Requirements a person split or merged away count as removed too: a proposal whose best match is one of them is dropped, like a deleted one (active Requirements still win ties). Superseded rows from extractions before Story 2.7 are not candidates.
- **Decision (human):** a content edit (`PATCH` that changes text or classification) clears `confirmed_at` and `confirmed_by`.
- **Decision (human, review):** accepting a pending change also clears the confirmation; any change to text or classification does.
- **Decision (human): stable `R<n>` numbers.** A stored `number` per Opportunity (unique with `opportunity_id`), backfilled from today's positions (active Requirements by `created_at, id`; then the inactive ones after them). Every new Requirement (extracted, created, split or merged) takes the Opportunity's max+1 (allocate under a lock on the Opportunity so concurrent inserts can't collide); removed numbers are never reused. `active_requirement_snapshots` returns the stored number, so Gaps, Estimates, Assessments, Conflicts, Reviews and exports keep their labels after a delete, split or merge. The `Requirement` read model gains `number`, and the list row and inspector show `R<n>`.
- **Errors:** stale is 412 `row_version_mismatch`, missing `If-Match` 428, an unknown or inactive id 404, invalid input 422, and duplicate or too few/many merge ids 422.
- **Web:**
  - `c` (and a **Add Requirement** button in the tab header) opens an inline form at the top of the list: text and classification, saved with Enter or **Add**, Esc cancels.
  - `x` toggles the focused row's selection (Esc clears), following the Gaps list pattern. With 2 or more selected, a bar shows **Merge (N)**, which opens a form prefilled with the selected texts joined by a space and the first one's classification.
  - Inspector: **Split** opens two text fields prefilled with the original text, each with a classification select; **Delete** opens a reason field (the shared `ReasonInput`).
  - Manual Requirements show origin `Manual` and "No Evidence" in the inspector.
  - **View diff** on the 412 notice for an edit: the current saved text as a `−` line and the user's draft as a `+` line on `bg-diff-tint`, plus a classification change if any. Reload as before.
  - All of it is hidden for sales representatives, and every new control passes axe.
- **Privacy:** trace and logs carry ids, versions and field names only.

**Never:** No undo or restore of removed Requirements and no view of them in the tab. No bulk delete or bulk edit. No split into more than two in one step. No automatic rerun of Gaps, Assessments or Estimates. No `intake_agent` prompt or schema change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create | Owner posts valid text | 201, v1, human, locked, no Evidence, one event | 422 blank / >2,000 / bad class |
| Delete | Current `If-Match`, reason | 200, leaves the list, reason stored, event has no reason | 412 / 428 / 422 blank reason |
| Split | R1 with 2 passages | 2 new rows each linking both passages; R1 `superseded`; one event | 412 stale |
| Merge | R1, R2 with current row versions | 1 new row with the union of Evidence; both `superseded` | 412 if any stale; 422 one id or duplicates |
| Pending change | R2 has an open change, then delete/split/merge | Change `superseded` | N/A |
| Re-extract after delete | Model proposes R3's passages again | Nothing written for it | N/A |
| Re-extract after split | New Source refines a split part | Pending change on that part | N/A |
| Edit confirmed | Confirmed R1 text edited | v2, `confirmed_at` cleared | N/A |
| Stable numbers | R1–R5 active; delete R2, split R3 | R1, R4, R5 keep their numbers; the split parts are R6, R7; a Gap linked to R4 still says R4 | N/A |
| Backfill | Existing Opportunity with active and superseded rows | Active ones numbered 1..N in today's order, inactive after; labels unchanged | N/A |
| Sales rep / outsider | Any command | 403 / 404 | N/A |
| UI 412 diff | Save after someone else edited | View diff shows −theirs / +yours; draft kept | N/A |

</frozen-after-approval>

## Code Map

- Numbering: `backend/app/modules/intake/application/requirement_refs.py:34-48` -- `number=` from the row instead of `enumerate`; update the module docstring. Consumers (`gaps.py:302-319`, `conflicts/domain/semantic.py:90-124`, `estimates/application/from_assessments.py:54`, assessments, reviews) read `snapshot.number` and need no change beyond tests; keep their "Superseded" label for inactive links. `requirements_repository.py:insert_requirement:315` allocates the number. Order the active list by `number`.

- `backend/app/modules/intake/application/requirement_edits.py` -- add `create_requirement`, `delete_requirement`, `split_requirement`, `merge_requirements` beside `edit_requirement:119`; reuse `_authorized:89`, `_load:99`, `_expected:106`, `_stale:83`, `repo.insert_version`, and the pending-change supersede at `:172-174`. Clear the confirmation in `edit_requirement` when content changes.
- `backend/app/modules/intake/adapters/requirements_repository.py` -- `insert_requirement:315`, `link_evidence`, `active_requirement`; add a status change with `expected_row_version` (returns `None` when stale), evidence copy, and the deleted Requirements with passages for reconcile.
- `backend/app/modules/intake/adapters/models.py:160-193` -- `RequirementRow`: `removal_reason` (nullable). `domain/requirements.py:40` `RequirementStatus` gains `deleted`; `reconcile:316` takes the deleted ones and drops proposals whose best match is deleted.
- `backend/app/modules/intake/application/extraction.py` -- pass deleted Requirements to `reconcile`.
- `backend/app/modules/intake/application/models.py:108-163` -- request models (create, delete, split, merge) and the `manual` origin label if needed; `api/routes.py:320-560` -- four routes, reusing `_IF_MATCH`, `_edit_responses`, `_with_etag`.
- `backend/app/platform/trace/catalogue.py:206-260` -- `IntakeRequirementCreated`, `Deleted`, `Split`, `Merged`, after `IntakeRequirementEdited`.
- `backend/migrations/versions/20261021_0034_requirement_lifecycle.py` -- down `0033_conflict_agent`: `removal_reason`, `number` (backfill, then NOT NULL and unique `(opportunity_id, number)`), and the status check if one exists.
- Removed Requirements already render as "Superseded" in `gaps.py:82`, `estimates.py:84`, `assessments.py:56`, `reviews.py:58`, `conflicts.py:91`. Do not change them; `answers.py:33` labels a superseded change "Superseded", which is correct.
- `web/src/components/opportunities/requirements-list.tsx` -- keys at `:145-162` (`singleKeyShortcuts`), stale notice `:887-901`, `reload:818`; copy the `x`/Esc/`checkedIds`/bulk-bar pattern from `gaps-list.tsx:187-241,887-895,1230-1259`.
- `web/src/components/opportunities/requirement-inspector.tsx` -- Split and Delete; reuse the `PendingChangeView` diff markup (`:169-182`) for View diff by extracting a small shared diff component; `reason-input.tsx` for the reason.
- `web/src/app/opportunities/actions.ts:1055-1200` -- create, delete, split, merge actions next to `editRequirement`; `lib/requirements.ts` labels and copy. `npm run gen:api` against a fresh local backend.
- Tests: `backend/tests/test_intake_requirement_edits.py` helpers (`_extracted:41`, `_list:51`, `_history:100`, `_events:114`), `test_intake_incremental.py` for the reconcile rows; web `requirement-edits.test.tsx`, `requirements-list.test.tsx` inside `ShellProviders singleKeyShortcuts`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/**`, trace catalogue, migration 0034 -- commands, routes, status `deleted`, reconcile rule, confirmation cleared on edit
- [x] `backend/tests/test_intake_requirement_lifecycle.py` (new) and `test_intake_incremental.py` -- every matrix row, plus a migration upgrade/downgrade check
- [x] `web/src/lib/api/schema.d.ts`, actions, Requirements list, inspector, shared diff, tests -- `c`, `x`, Merge, Split, Delete, View diff, hidden for sales reps, axe

**Acceptance Criteria:**
- Given extracted Requirements, when the engineer splits one, merges two duplicates, deletes a wrong one with a reason and adds a missing one, then the list shows exactly the expected active Requirements, each new one with the right Evidence, and a re-extraction neither restores the deleted one nor overwrites the others.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- **Responses:** create, split and merge are 201; delete is 200 with `{id, status: "deleted", version}`. Split returns `{items: [Requirement, Requirement]}`; create and merge return the new `Requirement` with `ETag`. Merge with more than 20 or fewer than 2 ids is the request model's 422; the same id twice is 422 "Each Requirement can be merged only once."; any stale `row_version` (checked for all before anything is written) is 412.
- **Order of checks:** authorize (403/404), load (404 for an unknown or inactive id), body rules (422), then `If-Match` (428, 412) — the Story 2.7 reject order.
- **Numbers:** `insert_requirement` takes a transaction advisory lock `intake.requirement_number:<opportunity>` and gives max+1. The active list (and `active_requirement_snapshots`) is ordered by `number`. Migration 0034 backfills active ones first by `created_at, id`, then the inactive ones; its downgrade turns `deleted` rows into `superseded`.
- **Reconcile:** `reconcile(proposals, active, removed)` matches over the active and removed Requirements together (removed after active, so an active one wins a tie); a match with a removed one is the outcome `removed` (nothing written; logged as `removed_count`). Removed = `deleted` rows plus `superseded` rows with `locked_by_human` (split and merge lock the originals as they supersede them; `repo.removed_requirements`).
- **Clearing the confirmation:** a `PATCH` that changes text or classification and accepting a pending change both clear it; a no-op edit keeps it.
- **Trace:** `intake.requirement.merged` serialises its field as `from` (`from_` in Python, by alias). `split` was added to the catalogue's irregular past tenses.
- **Read model:** `Requirement.number`. The web derives origin "Manual" from `origin: human` with no Evidence (extracted Requirements always cite at least one passage).
- **Web:** `c` is left to the Requirements tab by the shell (like Admin → Catalogue), and opens the Add form only for those who may edit. The merge takes the selected Requirements in number order (the first one's classification). After a 412 on an edit, the server action re-reads the list and returns the saved Requirement (`current`), so **View diff** shows it against the draft; merges and creates have no single changer (`changedBy: null`, no diff). New trace labels: "Requirement added", "Requirement deleted", "Requirement split", "Requirements merged".

## Spec Change Log

- **Review loop 1 (2026-10-21), triage rows 1–2 (intent_gap):** a merged-away duplicate came back on re-extraction (superseded originals weren't reconcile candidates and matching is one-to-one), and accepting a pending change kept the confirmation. The human decided both (frozen block) and chose to keep the implementation and apply a targeted fix instead of reverting. Amended: the two decisions above. Mechanism: split and merge set the original's `locked_by_human` when superseding it; reconcile's removed candidates are `deleted` rows plus `superseded` rows that are locked (extraction before Story 2.7 never superseded a locked row, so old extraction-superseded rows stay out). Known-bad state avoided: duplicates reappearing after a merge; a confirmation vouching for accepted agent wording. KEEP: everything else as implemented (commands, routes, numbers, migration 0034, web forms, View diff, tests).

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Re-extraction revives a merged-away duplicate: superseded originals aren't candidates, matching is one-to-one, so the second duplicate proposal is ADDed (blind, edge ×2) | high | `extraction.py` passes only active + deleted to `reconcile`; the frozen rule's mechanism ("results carry the originals' passages, so proposals match them") fails one-to-one; the acceptance test feeds one combined proposal | intent_gap |
| 2 | Accepting a pending change keeps the confirmation while a PATCH clears it (blind) | low | `accept_requirement_change` calls `repo.edit_requirement` without `clear_confirmation`; the frozen decision names `PATCH` only | intent_gap |
| 3 | `answers.py` labels Story 4.7 change refs by list position, not the stored number (blind, verification-gap) | medium | `answers.py:151-161` `enumerate(active_requirements)`; after a delete, a chip says R2 for R3 | patch |
| 4 | Effort comparison labels rows `R${index+1}` (verification-gap) | medium | `web/src/lib/effort-comparison.ts:209`; the test locks in index labels | patch |
| 5 | The four new server actions have no `actions.test.ts` cases (verification-gap) | medium | Gap pre-verified: component tests mock them; dropping `If-Match` or `row_version` would pass | patch |
| 6 | `isMergeRef` accepts `rowVersion` 0; the API needs ≥ 1 (blind, edge, verification-gap) | low | Direct correction to `>= 1` | patch |
| 7 | Overlapping concurrent merges sent in different orders can deadlock (500) (blind) | low | Rows updated in caller order; sorting the refs by id is a direct fix | patch |
| 8 | A proposal sharing more passages with a deleted Requirement than with an active one is dropped (edge) | low | Behaves as the frozen "best match" rule says; needs a delete plus an active Requirement re-citing the same passages | reject |
| 9 | Downstream modules label deleted Requirements "Superseded"; no successor pointer (blind, edge) | false | The frozen block says other modules show removed ones as "Superseded" and lineage lives in the trace | reject |
| 10 | Delete has no way back (blind) | false | The frozen block says no undo or restore | reject |
| 11 | Split accepts two identical parts (blind) | low | The prefill is per spec; a guard adds a new rule | reject |
| 12 | Split/merge results read "Edited" though never edited (blind) | low | Derived label; fixing needs stored creation kind (new surface) | reject |
| 13 | Merge bar allows >20; generic 422 message; prefill can exceed 2,000 (blind, edge) | low | Rare; the form shows the length problem; guards add branches | reject |
| 14 | `c` on the Requirements tab does nothing for non-editors; cheat sheet lacks `c`/`x` (blind) | low | Non-editors on that tab can still use the + button to create an Opportunity; rare | reject |
| 15 | Stale merge names no changer and keeps the old prefill (blind) | low | Recorded in Implementation Notes; Reload refreshes row versions | reject |
| 16 | Create appends locally; double submit (blind) | low | The next poll or reload corrects order; a double click before re-render is rare | reject |
| 17 | Merge form reopens with the previous prefill after the selection drops below 2 (edge) | low | Cosmetic; the user can edit or cancel | reject |
| 18 | `c` while locked or with the form open (edge) | low | Saving is disabled while locked; rare | reject |
| 19 | Delete checks the reason (422) before `If-Match` (428) (edge) | false | The Story 2.7 reject order, recorded in Implementation Notes | reject |
| 20 | `test_intake_incremental.py` unchanged though the task names it (edge, claim) | low | The reconcile rows are covered in the lifecycle file; only the spec wording differs | reject |
| 21 | Merge takes no `If-Match` header (edge, claim) | false | The frozen block says no header, row versions in the body | reject |
| 22 | No concurrency test of number allocation; one lock and max query per insert (blind) | low | Advisory lock plus the unique constraint; cost is small | reject |
| 23 | Review 2: a delete/split/merge committing while an extraction reconciles the same unlocked Requirement makes `version_extracted` return None, then `propose_requirement_change` raises 404 and the job run fails (blind, edge) | low | `extraction.py:402-421`; the job retries and the retry sees it as removed; catching the not-found and counting it `removed` is a direct fix | patch |
| 24 | Review 2: split/merge take row locks then the number lock, while an extraction holds the number lock and then updates rows: possible deadlock (edge) | low | Taking `repo.lock_numbers` before the first `_remove` is a one-line fix | patch |
| 25 | Review 2: the text-only match against a removed Requirement has no test (verification-gap) | medium | Gap pre-verified: reverting the fallback to `existing` passes every test | patch |
| 26 | Review 2: Esc with rows checked and the inspector open is untested (verification-gap) | low | Gap pre-verified; a short test | patch |
| 27 | Review 2: the Merge form submits the selection at submit time, which can differ from the one its draft was built from (blind, edge ×2; includes row 17) | low | `requirements-list.tsx` keeps `merging` while rows are toggled or drop out; closing the form when the selection changes is a direct fix | patch |
| 28 | Review 2: with single-key shortcuts off, keyboard users cannot multi-select (checkbox `tabIndex -1`, `x` off) (edge) | medium | Same pattern as the Gaps list (`gaps-list.tsx:194,269`), which predates this story | defer |
| 29 | carried — Review 2: no concurrent number-allocation test; lock held until the extraction commits (blind, verification-gap) | low | carried row 22 | reject |
| 30 | carried — Review 2: deleted Requirements labelled "Superseded" downstream (blind, edge, verification-gap) | false | carried row 9 | reject |
| 31 | carried — Review 2: no undo/restore, reasons unreadable (blind) | false | carried row 10 | reject |
| 32 | carried — Review 2: stale merge names no Requirement (blind) | low | carried row 15 | reject |
| 33 | carried — Review 2: `c` for non-editors, cheat sheet, `c` while locked or open (blind, edge) | low | carried rows 14, 18 | reject |
| 34 | carried — Review 2: split accepts identical parts (blind) | low | carried row 11 | reject |
| 35 | carried — Review 2: `test_intake_incremental.py` unchanged (edge, claim) | low | carried row 20 | reject |
| 36 | Review 2: split parts and merged originals get no trace event of their own (blind) | false | The frozen block puts the split event on the original and the merge event on the new one, with the ids in the payload | reject |
| 37 | Review 2: View diff only after an edit's 412 (edge, claim) | false | The frozen block says View diff "on the 412 notice for an edit" | reject |
| 38 | Review 2: `active_cited_passages(status=…)` name, extra loads of old superseded rows, `RequirementRecord.number` defaults to 0 (blind) | low | Naming and a small cost; no wrong output; the default is never used by a real row | reject |
| 39 | Review 2: tests import private helpers across modules (blind) | low | The existing suite's pattern (`test_intake_incremental.py` does the same) | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
