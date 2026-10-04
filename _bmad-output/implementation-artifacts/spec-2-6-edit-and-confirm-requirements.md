---
title: 'Story 2.6: Edit and confirm Requirements (demo scope)'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: 'cf35cd107a95f5113757d49a3658f69975020b0b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-5a-extract-requirements.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Extracted Requirements are only the model's draft. The presales engineer must be able to correct them and say "this list is right". Nothing they touch may be overwritten by a later extraction (FR-6, AD-11).

**Approach:** Add three commands with `If-Match`: inline edit of text and classification, confirm one Requirement, and confirm all. Each change creates a new immutable Requirement version and locks the Requirement against re-extraction.

## Boundaries & Constraints

**Always:**
- **Depends on Story 2.5 Part A** (`intake_requirements` with `origin`, `locked_by_human`, `version`, `row_version`, and its list API) **and Part B** (the list keyboard model and the inspector).
- **Who:** the new action `intake.requirement.edit` is granted to the Opportunity's owner and collaborators, **except sales representatives** (FR-64). Readers get 403, non-readers get the Opportunity's 404. The UI hides the controls when the read model's `can_edit_requirements` is false.
- **History:** a new `intake_requirement_versions` table (`requirement_id`, `version`, `text`, `classification`, `created_by`, `created_at`) keeps every version immutably. Part A's v1 is backfilled when the migration runs and written when extraction inserts.
- **Edit:** `PATCH /opportunities/{id}/requirements/{rid}` with `If-Match: <row_version>` and `{text?, classification?}`.
  - The text is trimmed, 1 to 2,000 characters.
  - The classification is one of the six.
  - A no-op changes nothing and returns 200.
  - Otherwise it bumps `version` and `row_version`, writes a history row, and sets `origin: human` and `locked_by_human: true`.
  - Evidence links stay as they are.
  - Trace: `intake.requirement.edited` with the changed field names and the version (no text).
- **Confirm:** `POST /opportunities/{id}/requirements/{rid}/confirm` with `If-Match`.
  - Sets `confirmed_at` and `confirmed_by` (new nullable columns) and `locked_by_human: true`. The version is unchanged.
  - Idempotent: confirming an already-confirmed Requirement returns 200 with no new event.
  - Trace: `intake.requirement.confirmed`.
- **Confirm all:** `POST /opportunities/{id}/requirements/confirm-all` confirms every active, unconfirmed Requirement in one Unit of Work. No `If-Match`, because it touches only unconfirmed rows. It returns the count, with one trace event per Requirement.
- **Locking:** Part A's re-run already skips `locked_by_human` Requirements, so edited and confirmed ones survive a re-extraction.
- **Stale version:** a stale `If-Match` gives 412 `precondition_failed`. A missing `If-Match` on edit or confirm gives 428.
- **Web, in the Requirements list and the inspector:**
  - `e`, or a double-click on the row text, edits inline. Saves on blur or Enter; Esc reverts (reuse `inline-field.tsx`).
  - The classification is a select in the inspector.
  - A **Confirm** button on each row, and in the inspector.
  - **Confirm all (N)** in the tab header, hidden when N is 0.
  - A confirmed row shows a check icon and the label "Confirmed". An edited row shows origin `Edited`.
  - **On 412:** "Changed by {name} since you opened it." with **Reload**.
  - All of it is hidden for sales representatives.
- **Privacy:** trace and logs carry ids, versions and field names only.

**Never:** No split, merge, delete or manual create. These and the 412 **View diff** are `[post-demo]`. No pending changes for re-extraction (Story 2.7). No bulk edit. No undo.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Edit text | Owner PATCHes new text with the current `If-Match` | 200, v2, origin `human`, locked; history has v1 and v2; one trace event naming `text` | N/A |
| Edit class | Classification only | Same, with field `classification` | N/A |
| No-op | Same values | 200, nothing written | N/A |
| Invalid | Blank text, more than 2,000 characters, or an unknown classification | 422 | Nothing written |
| Stale | An old `If-Match` | 412 | Nothing written |
| No header | PATCH without `If-Match` | 428 | N/A |
| Sales rep | A sales representative collaborator edits or confirms | 403 | N/A |
| Reader / non-reader | HoD / outsider | 403 / 404 | N/A |
| Confirm | Unconfirmed, current `If-Match` | 200, `confirmed_at` set, locked, one event | N/A |
| Confirm again | Already confirmed | 200, no new event | N/A |
| Confirm all | 5 active, 2 already confirmed | 200, count 3, 3 events | N/A |
| Survives re-run | An edited Requirement, then a re-extraction | The edited one stays active and unchanged; unlocked extracted ones are superseded | N/A |
| UI 412 | Save while someone else changed it | The message with Reload; the input keeps the user's text | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/intake/` (from Story 2.5 Part A) -- the requirement tables and repository. Add `application/requirement_edits.py` (edit, confirm, confirm-all commands following the AD-3 path), routes next to the requirements routes, `domain/requirements.py` text rules, and the history insert in the extraction accept path.
- `backend/app/modules/opportunities/application/opportunities.py` and `api` -- the `If-Match` and 412 pattern from Story 1.8 Part B (inline edit). Reuse its header parsing and error types.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- `REQUIREMENT_EDIT`, granted to owner and member but filtered out for `sales_representative`. Check how policy expresses role exclusion; if it can't, add a role check in the command and test it.
- `backend/app/platform/trace/catalogue.py` -- `IntakeRequirementEdited` and `IntakeRequirementConfirmed`.
- migrations -- the next revision: `intake_requirement_versions` with a v1 backfill, plus `confirmed_at` and `confirmed_by` on `intake_requirements`.
- `web/src/components/opportunities/inline-field.tsx` -- reuse it for the inline text edit, with the same 412 handling and copy as Story 1.8 Part B.
- `web/src` Requirements list and inspector (Story 2.5 Parts A and B) -- `e`, Confirm, Confirm all, the classification select, and the labels.
- Tests -- command and API tests against Postgres for every row, plus web component tests with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/**`, identity policy, trace catalogue, migration -- commands, routes, history
- [x] `backend/tests/test_intake_requirement_edits.py` -- every matrix row
- [x] `web/src/lib/api/schema.d.ts` (from local uvicorn), actions, the Requirements list and inspector, and tests -- edit, Confirm, Confirm all, 412, hidden for sales reps, axe

**Acceptance Criteria:**
- Given extracted Requirements on the demo Opportunity, when the presales engineer fixes one Requirement's wording and presses Confirm all, then every row shows Confirmed, and a re-extraction leaves them all in place.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- **412 code:** the existing `RowVersionMismatchError` is reused, so a stale `If-Match` is 412 `row_version_mismatch` (the code every other `If-Match` route returns), not a new `precondition_failed` code. 428 is `if_match_required`.
- **Role exclusion:** `policy.py` gained `RELATION_EXCLUDED_ROLES`: `intake.requirement.edit`'s owner/member grant is withheld when *all* of the principal's roles are excluded (`sales_representative`). Roles add up, so a person who is also a presales engineer keeps it.
- **Confirm again:** an already-confirmed Requirement returns 200 with nothing written whatever row version `If-Match` names (a missing header is still 428). Confirming bumps `row_version` (not `version`), so other open views get 412 on their next write.
- **Edit after confirm:** keeps `confirmed_at` / `confirmed_by`.
- **History:** `intake_requirement_versions.created_by` is the actor id as text (`intake_agent@<semver>` or a user's UUID). The backfill takes it from the extraction's `intake.extraction.completed` trace event (falling back to `intake_agent`).
- **Read model:** `Requirement` gained `confirmed_at`, `confirmed_by` and `last_changed_by` (the person behind the later of the current version and the confirmation; drives "Changed by {name}" after a 412). `RequirementList` gained `can_edit_requirements`. `PATCH` and `confirm` responses carry `ETag`.
- **Web:** `inline-field.tsx` gained `InlineInput` (the editing half, parent-controlled) for the list row; the inspector reuses `InlineField` for the text. `e` follows the single-key-shortcuts setting like `j`/`k`. The row's **Confirm** is outside the list's Tab order (like the Evidence chips); keyboard users confirm from the inspector or with **Confirm all**. On 412 the row's input reopens with the user's text, unfocused, and focus moves to **Reload**; after Reload the input stays open to save again against the new version.

## Spec Change Log

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Editing a confirmed Requirement keeps it confirmed (blind) | low | The spec is silent; the person editing sees the text they save. Matters only when someone else edits after a confirmation. Raised with the human as a post-demo decision | reject |
| 2 | Confirm all confirms rows the user hasn't seen; no `If-Match` (blind, edge claim) | false | The intent says Confirm all takes no `If-Match` and touches only unconfirmed rows | reject |
| 3 | Confirm all returns only a count; a failed reload leaves stale row versions (blind) | low | Next write gets a 412 and Reload fixes it; nothing is lost | reject |
| 4 | A row superseded or confirmed concurrently between load and UPDATE gives 412, not 404/200 (blind, edge ×2) | low | Real but needs a re-extraction or a second confirm in the same instant; the fix adds a branch | reject |
| 5 | Single-line `<input>` drops newlines in the text (blind) | low | Extracted statements are single sentences; the agent noted the cramped input as a demo trade-off | reject |
| 6 | JS `trim()` vs Python `strip()` differ on exotic characters (blind, edge) | low | Only U+FEFF/U+001C–1F/U+0085; not met in normal typing | reject |
| 7 | Row Confirm is not keyboard-reachable (blind) | low | Confirm in the inspector and Confirm all are keyboard-reachable; same model as the chips in 2.5 Part B | reject |
| 8 | No unconfirm or undo (blind) | false | The intent says "No undo" | reject |
| 9 | Evidence isn't flagged as citing the extracted wording after an edit (blind) | false | The intent says Evidence links stay as they are | reject |
| 10 | 412 changer lookup reads the whole list; may name the user's own other tab (blind) | low | Correct name in the normal case; cost is one list read after a rare 412 | reject |
| 11 | Client accepts `rowVersion` 0 (blind) | low | The API rejects it as stale; never sent by the UI | reject |
| 12 | Concurrent-PATCH and `confirm_all` trace `subject_version` tests missing (blind) | low | Conditional UPDATE is the same proven pattern as Story 1.8; the count of events is tested | reject |
| 13 | `last_changed_by` never tested with two different people (verification-gap, blind) | medium | Gap pre-verified: every test uses one person | patch |
| 14 | Migration 0010 backfill never runs against existing Requirements (verification-gap, blind) | medium | Gap pre-verified: the only migration test downgrades to 0006, before Requirements exist | patch |
| 15 | `confirmAllRequirements` 403/404/500 mapping untested (verification-gap) | medium | Gap pre-verified | patch |
| 16 | Inspector text save never exercised (verification-gap) | medium | Gap pre-verified | patch |
| 17 | An inspector text save that fails (blank, 412, 422, error) reopens the editor in the list row, pulling focus out of the pane; the inspector field keeps no draft (verification-gap other, edge) | medium | `save` always calls `setEditing` on the list row; `InlineField` already supports `error` | patch |
| 18 | Missing `If-Match` plus an invalid body gives 422, not 428 (edge, blind) | low | Body validation runs before the handler in FastAPI anyway; the matrix row uses a valid body | reject |
| 19 | Re-committing the same invalid draft keeps the input's key, so `finished` stays true and a later blur is ignored (edge) | low | Real after Enter on blank text then clicking away; direct fix in the key | patch |
| 20 | Enter while locked gives no feedback (edge) | low | The stale notice and Reload are already shown; intended | reject |
| 21 | Confirm all while a draft is open (edge) | low | The blur commits first and marks the row busy; the button is then disabled | reject |
| 22 | Enter during IME composition commits (edge) | low | Not met with the demo's English input | reject |
| 23 | Confirmations write no version history row (edge claim) | false | The intent says confirm leaves the version unchanged; trace records it | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
