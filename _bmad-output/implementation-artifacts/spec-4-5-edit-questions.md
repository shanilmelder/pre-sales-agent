---
title: 'Story 4.5 (demo slice): edit and approve Clarification Questions'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: 'f015ea471199439ba2df02e5d853e27e10a567c4'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-3-detect-gaps.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Clarification Agent drafts one question per Gap, but they are read-only. A presales engineer can't fix the wording or say "these are the questions I stand behind", so the drafts can't go to the customer as they are (FR-12).

**Approach:** In the Gap inspector, the presales engineer edits a question's text and topic inline and approves it (singly, or **Approve all**). Approval is recorded with who and when; editing an approved question returns it to draft. Questions a person has touched survive later Gap detection runs.

## Boundaries & Constraints

**Always:**
- **Depends on:** 4.3 (Gaps, questions, detection, Gaps tab), 2.6 (inline edit, If-Match, 412 pattern).
- **Scope of actions (decided: edit and approve):** inline edit of a question's text and topic, Approve, and Approve all. No Drop and no Merge.
- **Lifecycle:** question status gains `approved` (`drafted | approved | superseded`). Columns added: `approved_by`, `approved_at` (both null unless `approved`), `edited_by_human` (bool, default false). Editing text or topic of an `approved` question returns it to `drafted` and clears the approval. `status_changed_at` moves on every status change.
- **Edit:** `PATCH /opportunities/{id}/clarification-questions/{qid}` with `If-Match`, body `{text?, topic?}`; text 1–1,000 and topic 1–80 characters after trimming; an unchanged value is a 200 no-op. Sets `edited_by_human`. Trace `gaps.clarification_question.edited` (ids and which fields changed, never text).
- **Approve:** `POST …/clarification-questions/{qid}/approve` with `If-Match`; approving an approved question is a 200 no-op. `POST …/clarification-questions/approve-all` takes the drafted questions the client shows (`[{id, row_version}]`) and approves exactly those, all or nothing, returning `{count}`. If any listed question changed (row version), is no longer drafted, or another drafted question of an open Gap exists that wasn't listed, it returns 412 and approves nothing (decided 2026-10-05: approve only what I saw). Trace `gaps.clarification_question.approved` per question (id, approver).
- **Who:** new action `gaps.clarification_question.edit` (covers edit and approve) for the owner and collaborators except sales representatives (`RELATION_EXCLUDED_ROLES`), 403 otherwise; no access is the 404-equivalent. A sales representative's `list_gaps` shows only `approved` questions (the Gap still shows, with no question block). `GapList` gains `can_edit_questions`.
- **Concurrency:** stale `If-Match` → 412; missing → 428; the web shows "Changed by {name} since you opened it." with Reload, as for Requirements. Only questions of `open` Gaps can be changed (409 `gap_not_open` otherwise).
- **Re-detection (decided: keep touched Gaps):** a later detection run does not supersede an open Gap whose question has `edited_by_human` set or is `approved`; that Gap and its question stay as they are, and the run's new Gaps are added alongside. Untouched open Gaps are superseded as today. `gaps.detection.completed` gains `kept_count`.
- **Web (Gap inspector and list):**
  - The question block becomes editable (text as a multi-line inline field, topic as a single-line field) using the 2.6 `InlineField` pattern: Enter or blur saves, Esc reverts, `e` focuses the text.
  - An **Approve** button on a drafted question; an "Approved by {name}, {date}" line on an approved one.
  - The pill shows "Draft" or "Approved" (icon plus label) in the list row and inspector, with the date of the last status change in the inspector.
  - The Gaps tab header gets **Approve all (N)**, hidden when N is 0 or the user can't edit.
  - Sales representatives see questions read-only and only approved ones.
  - Axe checks and keyboard as in the Gaps tab.
- **Export (Story 8.8):** the export lists `drafted` and `approved` questions with their status ("Draft" / "Approved").
- **Trace tab (Story 9.8):** the two new events get plain-word labels ("Clarification Question edited", "Clarification Question approved").

**Never:** No merge, no topic-grouped questions view, no Sent / Answered / No answer states, no export of questions as their own file, no View diff on 412. These stay `[post-demo]` (4.5 full, 4.6, 4.7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Edit | Owner edits a drafted question's text with the current If-Match | 200, new text, `edited_by_human`, row_version +1, one `edited` event | N/A |
| Edit approved | Edit an approved question | Back to `drafted`, approval cleared | N/A |
| Invalid | Empty text, 1,001 characters, or a 81-character topic | 422 | Nothing changed |
| Approve | Approve a drafted question | `approved`, `approved_by`/`approved_at` set, one `approved` event | N/A |
| Approve all | 3 drafted, 1 approved; client sends the 3 it shows | 200 `{count: 3}`, 3 events | N/A |
| Approve all, changed | A listed question was edited since the client loaded, or a drafted one is missing from the list | 412 with "Changed by …" and Reload | Nothing approved |
| Stale | Old If-Match / none | 412 / 428 | Nothing changed |
| Gap not open | Question of a converted Gap | 409 `gap_not_open` | Nothing changed |
| Who | Sales rep edits / reads | 403 / sees only approved questions | N/A |
| Re-detect | 4 open Gaps: 1 edited, 1 approved, 2 untouched; detection runs again with 3 new candidates | The edited and approved Gaps keep their questions; the 2 untouched are superseded; 3 new Gaps added (5 open); `kept_count` 2 | N/A |
| Export | Export after approving 2 of 3 questions | All 3 questions listed, status "Approved" or "Draft" | N/A |
| Privacy | Any edit | No question text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/adapters/models.py:107-122` `QuestionRow` (status check `('drafted','superseded')` at :111, `gap_id` unique) -- add columns and widen the check; `GapRow` :54-92.
- `backend/app/modules/gaps/domain/gaps.py` -- `QuestionStatus` :69-72, `QUESTION_MAX`/`TOPIC_MAX` :22-23; add the transitions (pure, unit-tested).
- `backend/app/modules/gaps/adapters/repository.py:203-232` `supersede_detected` (re-detection: skip touched Gaps), `questions_for` :378-389, `insert_gap` :283.
- `backend/app/modules/gaps/application/detection.py:201` `accept_gap_detection` (calls supersede at :245).
- `backend/app/modules/gaps/application/gaps.py` -- `list_gaps` (question built :143-144; sales-rep filter), `GapList` flags (:160); new `questions.py` commands modelled on `intake/application/requirement_edits.py` (`_authorized` :60, `_stale` :54, `_expected` :77, `edit_requirement` :90, `confirm_requirement` :164).
- `backend/app/modules/gaps/api/routes.py` -- new routes; copy the intake route helpers (`_IF_MATCH` ~:323, `_with_etag` :336). Concurrency helpers `platform/concurrency.py` (`etag` :39, `parse_if_match` :44, `check_row_version` :59).
- Identity: `identity/actions.py:26-27`, `domain/policy.py` (:83-131, `RELATION_EXCLUDED_ROLES` :99-102); update `tests/test_authorize.py`.
- Trace: `platform/trace/catalogue.py:198-252` -- add `edited` and `approved`, like `intake.requirement.edited/confirmed` (:176, :188). Add their labels to `web/src/lib/trace.ts` `EVENT_LABELS` (9.8 is merged).
- Migration `0016_gaps_question_approval`, revising `0015_estimates_carry_assumptions`.
- Export (8.8 is merged): widen `estimates/application/export_content.py:239` from `drafted` to `drafted|approved` and show the status.
- Web: `components/opportunities/gap-inspector.tsx` (`QuestionPill` :10, question block :68-82), `gaps-list.tsx` (`GapsList` :54 keys, row pill :133, `GapsSection` :215), `lib/gaps.ts:47-48`; reuse `inline-field.tsx` (`InlineField` :62, `InlineInput` :162), the 412 handling in `requirements-list.tsx` (:381, :580-591, :799), `staleMessage` (`lib/opportunities.ts:37`); server actions like `editRequirement` (:801) / `confirmRequirement` (:832) and `RequirementWriteResult` (~:699-727) in `app/opportunities/actions.ts`. Regenerate `schema.d.ts` from a local uvicorn.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/gaps/**`, identity, catalogue, migration 0016, export filter -- lifecycle, commands, routes, read model, re-detection rule
- [x] `backend/tests/test_gaps_questions*.py` -- every matrix row (Postgres), domain transition tests, re-detection rule test
- [x] Web: `schema.d.ts`, actions, editable question block, Approve / Approve all, pills, 412, sales-rep view, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity's Gaps, when the presales engineer rewords a question and presses Approve all, then every question shows "Approved" with who and when, and a re-detection does not undo it.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Extra column `changed_by`:** the person behind a question's latest edit or approval, exposed as `ClarificationQuestion.last_changed_by` so a 412 can say "Changed by {name}" (as Requirements do). The spec's three columns are there as specified; `approved_by` alone can't name an editor.
- **Read model:** `ClarificationQuestion` gains `approved_by` / `last_changed_by` (`UserRef`), `approved_at`, `edited_by_human`. A sales representative is a principal whose every role is `sales_representative` (same rule as `RELATION_EXCLUDED_ROLES`); their `list_gaps` returns non-approved questions as `question: null`. Other readers (e.g. head of delivery) see drafts.
- **Locking:** edit, approve and approve-all take the Opportunity's detection advisory lock (`lock_opportunity`), the same one `accept_gap_detection` holds, so the "keep touched Gaps" check in `supersede_detected` (a `NOT EXISTS` on edited/approved questions) can't race an edit.
- **Order of checks:** authorize (403/404) → question in this Opportunity (404) → body validation (422) → `If-Match` parse (428) → Gap open (409 `gap_not_open`) → stale (412) → no-op or write. Approving an approved question returns 200 whatever version `If-Match` names; an unchanged edit with a stale `If-Match` is still 412.
- **Trace payloads:** `gaps.clarification_question.edited` `{gap_id, fields, row_version}`, `gaps.clarification_question.approved` `{gap_id, approved_by, row_version}`; `gaps.detection.completed` gains `kept_count` (default 0, so older rows still validate).
- **Export:** the questions table gets a `Question status` column ("Draft" / "Approved") and the Gap's status moves to a `Gap status` column.
- **Review loop 1 fixes:** approve-all takes a JSON array body `[{id, row_version}]` and 412s (approving nothing) unless it equals the drafted questions of open Gaps; the web sends what it shows and reuses the stale notice. `update_question` also requires the Gap still `open` in its WHERE (no row: 409 `gap_not_open` if the Gap isn't open, else 412). A superseded question (`QuestionNotEditableError`) maps to 409. `edited` events carry `approval_revoked`. A failed re-read after Approve all shows the stale notice with Reload.
- **Web:** `InlineField` gains `type="textarea"` (Enter saves, Shift+Enter is a new line) and `editRequest` (the `e` shortcut on a Gap row opens the inspector with the question text in edit). The inspector shows "Draft since …" / "Approved since …" for the last status change.

## Spec Change Log

- **2026-10-05, review loop 1 (human-renegotiated intent).** Trigger: review found Approve all could approve wording the user never saw (no version check; a colleague's edit returns a question to drafted and it is then approved in the caller's name). Amended (frozen, by the human's choice "approve only what I saw"): approve-all takes the `[{id, row_version}]` the client shows and returns 412 when the set differs; one matrix row added. Known-bad state avoided: approvals of unseen text. Applied as a patch on top of the existing code at the human's direction, not a re-derivation. KEEP: everything else in the implementation (lifecycle, edit, single approve, re-detection rule, sales-rep view, export, trace labels, web editing).

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge | Approve all approves drafted questions the user never saw | medium | intent_gap → resolved | Intent defined approve-all as "every drafted question"; the human chose "approve only what I saw" and the frozen block was amended (Spec Change Log); applied as a patch. Fixed. |
| 2 | blind | Re-approving an approved question is 200 before the If-Match check | false | reject | The intent makes approving an approved question a 200 no-op. |
| 3 | blind+edge | Re-detection can add Gaps that duplicate kept ones | false | reject | The human accepted this trade-off with decision A ("the run may add a Gap that overlaps one you kept"). |
| 4 | blind | Trace doesn't show an approval was revoked by an edit | low | patch | Direct: one bool on the edited payload, no text. Fixed. |
| 5 | blind | Two tests' event prefixes cover only one event type | low | patch | `LIKE prefix%` with `…question.e` / `…question.a`. Fixed. |
| 6 | blind | Domain `touched()` duplicates the SQL predicate | low | reject | Developer-only; both are tested by behaviour. |
| 7 | blind+edge | `QuestionNotEditableError` uncaught → 500 | low | patch | Direct mapping to 409. Fixed. |
| 8 | blind | Empty PATCH body is a 200 no-op | low | reject | Consistent with "an unchanged value is a 200 no-op". |
| 9 | blind | 422 checked before 428/409 | low | reject | Same order as Story 2.6's edit; documented codes still occur. |
| 10 | blind | `approved_by`/`changed_by` have no FK | false | reject | Module boundaries: gaps doesn't reference identity tables (same as `accepted_by` in 8.4). |
| 11 | blind | Export "Status" column changed meaning | low | patch | Rename to "Question status". Fixed. |
| 12 | blind | Drafts appear in the export | false | reject | The amended intent lists drafted and approved questions with their status. |
| 13 | blind+edge | Failed refresh after Approve all leaves stale rows → self-named 412 | low | patch | Show the stale notice with Reload when the reload fails. Fixed. |
| 14 | blind | approve-all 404 description mentions a question id | low | patch | Folded into row 1's change. Fixed. |
| 15 | blind | Serialisation against detection untested | low | reject | Covered in practice by the shared lock; a concurrency test adds machinery for a demo. |
| 16 | edge | A Gap converted by estimates between the open check and the update still gets its question changed | low | patch | `mark_converted` takes no gaps lock; add "Gap still open" to the UPDATE's WHERE. Fixed. |
| 17 | edge | row_version overflow in approve-all | false | reject | Unreachable (2^31 edits). |
| 18 | edge | JS trim vs Python strip differ on exotic whitespace | low | reject | Unlikely; the server validates anyway. |
| 19 | edge | After all Gaps are converted, Approve all approves nothing | false | reject | The intent allows changes only to questions of open Gaps; demo note: approve questions before accepting Assumptions. |
| 20 | verify | No test of a sales rep who also holds another role | low | patch | Pre-verified. Fixed. |
| 21 | verify | Shift+Enter in the textarea field untested | low | patch | Pre-verified. Fixed. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
