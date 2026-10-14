---
title: 'Story 4.6 (demo slice): export Clarification Questions and mark them sent'
type: 'feature'
created: '2026-10-14'
status: 'done'
baseline_commit: '8f661aada68abd27e84cd6e039c11282cc1520be'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-4-gaps-tab.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-5-edit-questions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Approved Clarification Questions can't leave the platform in a customer-ready form, and nobody can record that they were sent or that the customer won't answer, so no one knows what is outstanding (FR-12, FR-64).

**Approach:** From the Gaps tab, **Copy**, **Export .docx** or **Export email draft (.eml)** the approved questions, grouped by topic, in customer wording only. Then **Mark sent** (with a date) and later **No answer**, each a traced lifecycle step. The Overview shows sent and awaiting counts.

## Boundaries & Constraints

**Always:**
- **Depends on:** 4.5 (question lifecycle, approve), 4.4 (Gaps tab, `x` selection, inspector), 8.8 (python-docx), 3.2 (`platform.storage`, `platform.downloads.sign`).
- **Lifecycle:** `QuestionStatus` gains `sent` and `unanswered`. Pure domain transitions: `approved → sent` (with `sent_on`), `sent → unanswered`. Any other source status is 409 `question_not_approved` (mark sent) or `question_not_sent` (No answer). Only questions of `open` Gaps (409 `gap_not_open`). A `sent` or `unanswered` question can't be edited or approved (409 `question_not_editable`). The Gap stays `open` throughout.
- **Storage (migration 0030, revising 0029):** `gaps_clarification_questions` adds `sent_on DATE` and `sent_by`, set only while `sent|unanswered` (check). The status check is widened. The approval check becomes "approval fields set iff status in `approved|sent|unanswered`", so approval history is kept after sending. `status_changed_at` and `changed_by` move on each step.
- **Re-detection:** questions in `sent` or `unanswered` count as touched (`touched()` and the `supersede_detected` predicate), so their Gaps are kept.
- **Export:** `POST /opportunities/{id}/clarification-questions/export` `{format: copy|docx|eml}`.
  - It covers every `approved` question of an `open` Gap, grouped by topic (topics A–Z, then questions by Gap rank), numbered.
  - Content: the Opportunity's customer name, a date, topic headings and question text only. No Gap title, reason, impact, trigger, Knowledge Source or Evidence.
  - `copy` returns `{text}` inline. `docx` and `eml` are stored with `BlobStore.put_stream` and returned as `{url, file_name, expires_at}` from `downloads.sign` (TTL `download_link_ttl_s`).
  - `.eml`: a plain-text `EmailMessage` with a subject, no recipient and `X-Unsent: 1`. Nothing is ever sent.
  - With no approved questions it returns 409 `no_approved_questions`.
  - Trace `gaps.clarification_question.exported {format, question_ids}` with the Opportunity as subject. No text in trace or logs.
- **Mark sent:** `POST …/clarification-questions/mark-sent` `{sent_on, questions: [{id, row_version}]}` (1–200 items). It is all or nothing: 412 if any question is stale, not approved, or on a non-open Gap. `sent_on` defaults to today in the web and may not be in the future (422). One `gaps.clarification_question.sent {gap_id, sent_on, row_version}` event per question.
- **No answer:** `POST …/clarification-questions/{qid}/no-answer` with `If-Match`. Trace `gaps.clarification_question.marked_unanswered {gap_id, row_version}`.
- **Who:** new action `gaps.clarification_question.send` (export, mark sent, No answer) for the owner and every collaborator, sales representatives included. No access is a 404. `GapList` gains `can_send_questions`. A sales representative's view shows questions in `approved|sent|unanswered`.
- **Commands** take `lock_opportunity` and follow the 4.5 order of checks: authorize → 404 → 422 → 428 → 409 → 412.
- **Web (Gaps tab):**
  - Header **Export** menu: Copy, Word (.docx), Email draft (.eml), shown when approved questions exist. Copy uses the clipboard and announces "N questions copied". Files download through a Next route that fetches the signed link server-side.
  - **Mark N selected sent** when the selection holds approved questions, else **Mark all sent (N)**. Either opens a small form with a date (default today) and a confirm button.
  - Pills: Sent (send icon, neutral) and No answer (gap amber).
  - The inspector shows "Sent {date} by {name}", a **No answer** button on a sent question, and **Mark sent** on an approved one.
  - 412 shows the stale notice with Reload. Run axe on the new states.
- **Overview:** the Gaps card adds "N questions sent · M awaiting an answer". Sent counts `sent|unanswered`; awaiting counts `sent`.
- **Estimate export (8.8):** `QUESTION_STATUS_LABELS` gains "Sent" and "No answer".
- **Trace tab:** labels for the three new events.

**Never:**
- No answering or Record answer (4.7). No SSE live updates, no tab badge, no merge/drop.
- No sending from the platform, no recipient field, no export of drafted, sent or Gap-internal content.

These are `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Copy | 3 approved (2 topics), 1 drafted | `{text}` with 2 topic headings, 3 numbered questions, no Gap fields; 1 `exported` event | N/A |
| Docx / eml | Same, `docx` or `eml` | Signed link; the file holds only customer wording; the `.eml` has `X-Unsent: 1` and no `To` | N/A |
| Nothing approved | Only drafted questions | 409 `no_approved_questions` | No file, no event |
| Mark sent | 2 approved selected, `sent_on` today | Both `sent`, 2 `sent` events | N/A |
| Not approved | A drafted question in the list | 412 | Nothing marked |
| Future date | `sent_on` tomorrow | 422 | Nothing marked |
| No answer | A sent question, current If-Match | `unanswered`, Gap still `open` | 409 `question_not_sent` if not sent |
| Edit sent | PATCH a sent question | 409 `question_not_editable` | Nothing changed |
| Sales rep | Rep exports and marks sent; tries to edit | 200s; edit is 403 | N/A |
| Re-detect | 1 sent and 1 untouched open Gap, new run | Sent Gap kept; untouched superseded | N/A |
| Privacy | Any command | No question text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/domain/gaps.py` -- `QuestionStatus` :90, `QuestionState` :248, `edit_question` :279 / `approve_question` :306 (reject sent/unanswered), `touched` :315; add `mark_sent`, `mark_unanswered` and their errors.
- `backend/app/modules/gaps/adapters/models.py` -- `QuestionRow` :162-190 (checks :170-175).
- `backend/app/modules/gaps/adapters/repository.py` -- touched predicate :228-242, `update_question` (row_version WHERE plus Gap still open), the question record (:85-87, :572, :634-650).
- `backend/app/modules/gaps/application/questions.py` -- reuse `_authorized` :86, `_load` :98, `_expected` :107, `_open` :115, `_write` :131, `_approve_listed` :287 pattern for mark-sent. Add the export in a new `question_export.py`. Add pure content (grouping and plain text) plus a `.docx`/`.eml` renderer under `gaps/adapters/` (model the renderer on `estimates/adapters/export_docx.py`).
- `backend/app/modules/gaps/application/gaps.py` -- `gap_views` `approved_only` :207-218 → visible statuses; `GapList` flag. `models.py` `ClarificationQuestion` :45 (+`sent_on`, `sent_by`).
- `backend/app/modules/gaps/api/routes.py` -- new routes beside approve-all; storage settings come from `request.app.state.settings` (`storage_dir`, `download_signing_key`, `download_link_ttl_s`), as `knowledge/api/routes.py` does. `platform/downloads.py` `sign` :61, `link_for`; `platform/storage.py` `BlobStore.put_stream`. Feed the bytes as one async chunk.
- `backend/app/modules/identity/{actions.py:27,domain/policy.py}` -- `GAP_QUESTION_SEND` in OWNER and MEMBER grants, not excluded. Update `tests/test_authorize.py`.
- `backend/app/platform/trace/catalogue.py` (~:266) -- three payloads. `platform/errors.py` -- `question_not_approved`, `question_not_sent`, `question_not_editable`, `no_approved_questions`.
- `backend/app/modules/estimates/application/export_content.py` -- `QUESTION_STATUS_LABELS`. The `_questions_table` :227 filter stays the same.
- `backend/migrations/versions/20261014_0030_gaps_question_sent.py`.
- Web: `components/opportunities/gaps-list.tsx` (header, `GapsSection`), `gap-inspector.tsx`, `lib/gaps.ts` (`toApprove`/`approveAllLabel` → the mark-sent equivalents), `app/opportunities/actions.ts` (approve-selected action and `QuestionWriteResult`), `overview-summary.tsx` (`gapCounts`, Gaps card ~:259), `lib/trace.ts` `EVENT_LABELS`. Add a new route `app/api/opportunities/[id]/questions-export/route.ts`, modelled on `estimate-export/route.ts`. The menu follows `estimate-export.tsx`. Regenerate `schema.d.ts` from a local uvicorn.

## Tasks & Acceptance

**Execution:**
- [x] `gaps/domain/gaps.py` + domain tests -- transitions, touched, edit/approve guards
- [x] migration 0030, `adapters/models.py`, `adapters/repository.py` -- columns, checks, touched predicate
- [x] `application/questions.py`, `question_export.py`, export content/renderers, `gaps.py`, `models.py` -- commands, export, read model, sales-rep visibility
- [x] `api/routes.py`, identity, catalogue, errors, estimates labels -- wiring
- [x] `backend/tests/test_gaps_send.py` -- every matrix row against Postgres, including the parsed `.docx`/`.eml` contents
- [x] Web: schema, actions, export menu and route, mark-sent form, No answer, pills, Overview counts, trace labels, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity with approved questions, when the presales engineer exports the email draft and opens it, then it is an unsent draft grouped by topic with only the question wording. When they then mark the questions sent today, the Gaps tab shows "Sent", the Overview shows them as awaiting an answer, and the Trace tab lists the exported and sent events.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Read model:** `ClarificationQuestion` gains `sent_on` (date) and `sent_by` (`UserRef`); `GapList` gains `can_send_questions`. The export answers one `QuestionExport` shape: `{format, question_count, text, url, file_name, expires_at}`, with `text` set for `copy` and the link fields for `docx`/`eml`.
- **Content:** `gaps/adapters/question_document.py` holds the pure grouping (topics A–Z ignoring case and spacing, then Gap rank: impact, age, id; numbered 1..N across the document), the plain text, the `.docx` and the `.eml` (`policy=SMTP`, CRLF line ends, `Subject`, `X-Unsent: 1`, no `To`). File names: `clarification-questions-<customer slug>-<yyyy-mm-dd>.<ext>`. Blobs are not reference-counted in `platform_files` (nothing deletes blobs in R1).
- **Mark sent:** an unknown id, a listed id with two versions, a non-approved question and a question of a non-open Gap are all 412 (as approve-selected). `sent_on` is compared with the API's UTC date. The single 409 `question_not_approved` only arises from the domain transition (defensive).
- **No answer:** 409 `question_not_sent` for any status but `sent` (including `unanswered` again).
- **Edit/approve:** `sent|unanswered` → 409 `question_not_editable`, checked after `gap_not_open` and before the 412, as the 4.5 order requires.
- **Web:** the Next route is `POST /api/opportunities/{id}/questions-export?format=docx|eml` (it causes a trace event, so not a GET); it fetches `GET /api/v1/downloads/{token}` server-side and serves the file with its proper type. Copy goes through the `copyClarificationQuestions` server action and the clipboard. Selection (`x`) is offered to everyone who may approve or send questions; **Approve N selected** stays editors-only. The date form uses `noValidate` so a future date shows our message instead of the browser's. The Overview's Gaps stat gets a second line "N questions sent · M awaiting an answer" (shown whenever the counts are, including 0).

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge | Server checks `sent_on` against the UTC date, web defaults to local today: users ahead of UTC get 422 early in their day | medium | patch | `questions.py` `_today()` is UTC; `gaps.ts` `localToday()` is local; Sri Lanka 00:00–05:30 is refused. Fix: accept up to UTC today + 1. |
| 2 | blind | Mark sent isn't tied to the exported document | low | reject | Intent defines Mark sent as acting on the listed questions the user sees (with row versions, all or nothing); linking to an export batch is new design. |
| 3 | blind | Sent questions can't be re-exported | false | reject | Intent "Never": no export of sent content. |
| 4 | blind | No undo for sent / No answer, no confirmation | low | reject | Not in intent; adding transitions or a dialog is new surface, not a correction. |
| 5 | blind | No `answered` status, so "awaiting" never drops on an answer | false | reject | Intent "Never": answering is Story 4.7. |
| 6 | blind+edge | Overview counts sent questions on dismissed/converted Gaps as awaiting | low | patch | `overview.ts` `gapCounts` uses `list.items`; `list_gaps` returns converted and dismissed Gaps too. Direct fix: use `openGaps`. |
| 7 | blind | 409 `question_not_approved` unreachable through the API | low | reject | Defensive mapping of the domain transition, documented in Implementation Notes; removing it changes nothing for users. |
| 8 | blind+edge | Export holds the Opportunity lock while rendering; blob orphaned on rollback | low | reject | Orphaned blobs on a failed transaction are accepted by `platform/storage.py` ("acceptable in R1"); the lock is held for milliseconds at demo scale, and lifting it needs a new authorize path. |
| 9 | blind | `question_export.py` imports private `_authorized` | low | reject | Same module (`gaps.application`); no caller diverges; renaming is churn. |
| 10 | blind+edge | No answer returns 409 before 412 on a stale If-Match | false | reject | The frozen intent fixes the order "→ 409 → 412" (as 4.5/4.4). |
| 11 | blind+verify | Estimate export "Sent"/"No answer" labels untested | medium | patch | Pre-verified: neither estimates test fixture holds a sent or unanswered question. |
| 12 | blind | Other untested paths (safeName, clipboard unavailable, duplicate ids with the same version) | low | reject | Negligible; the server validates names, duplicates with one version are deduped by design. |
| 13 | blind | Logs use `actor.actor.id` vs `str(user_id)` | false | reject | Both are the user's UUID string, and the codebase uses both (e.g. `estimates/export.py:99`, `line_edits.py:198`). |
| 14 | blind | Inspector Mark sent form stays open after a failed outcome | low | patch | `gap-inspector.tsx:249` closes only on "ok"; the header form closes. Direct fix. |
| 15 | edge | `sent_on` may be far in the past or before approval | low | reject | Adds a guard the intent doesn't ask for; a user may record a past send. |
| 16 | edge | Header Mark sent form submits a stale snapshot after an inspector change | low | patch | `markSentFor` holds Gap objects from when it opened; resolve ids against the current list on submit. |
| 17 | edge | Copy/.eml text not cleaned of control characters, unlike .docx | low | patch | `plain_text` skips `clean_text`; direct fix. |
| 18 | verify | `question-not-editable` branch in the Gaps tab untested | medium | patch | Pre-verified: no component test returns that kind. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
