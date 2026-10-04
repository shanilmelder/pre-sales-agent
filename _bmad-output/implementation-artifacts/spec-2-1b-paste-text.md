---
title: 'Story 2.1 (Part B): Paste text as a Source'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '5937e3128872dcbaed1fbb61961b5a30b88f8d11'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-1a-upload-opportunity-sources.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Customer input often arrives as text in a chat, a call note or an email body that isn't saved as a file. Today the only way in is a file upload, which slows down both real use and the 2026-10-07 stakeholder demo.

**Approach:** Add a JSON endpoint that stores pasted text as a `note` Source. It reuses Part A's storage, versioning and trace path. The Sources tab gets a "Paste text" area next to the drop zone.

## Boundaries & Constraints

**Always:**
- **Who:** the same as file upload. Owner and collaborators use `intake.source.add`. Other readers get 403, and non-readers get the Opportunity's 404.
- **Endpoint:** `POST /api/v1/opportunities/{id}/sources/text` with the body `{"text": string}`.
- **Trimming and length:**
  - The text is trimmed of leading and trailing whitespace.
  - It must then be 1 to 1,000,000 characters (Unicode code points, as counted by Python `len`).
  - Blank text gives 422 `file_empty`, "Rejected: the text is empty".
  - Text over the limit gives 422 `file_too_large`, "Rejected: longer than 1,000,000 characters".
- **Unsupported characters:** text containing a NUL character or a lone surrogate gives 422 `file_content_mismatch`, "Rejected: the text contains unsupported characters".
- **Storage:** the trimmed text is stored UTF-8 encoded through `platform.storage`, content-addressed and reference-counted, exactly like a `.txt` upload. The Source has kind `note`, and its version filename is `Pasted text`.
- **Versioning:** Part A's rule applies unchanged. Identical bytes in the same Opportunity become the next version of the Source that already holds them, whether that Source was pasted or uploaded.
- **Trace:** one `intake.source.added` per added version, the same as Part A.
- **No side effects:** adding a Source never bumps the Opportunity's `row_version`. A rejection stores nothing.
- **Web:**
  - The upload area gets a **Paste text** button that opens a labelled textarea with **Add** and **Cancel**.
  - **Add** is disabled while the trimmed text is empty. Ctrl+Enter or ⌘+Enter submits, and Esc cancels.
  - Submitting adds a `Pasted text` row to the existing upload rows. The row shows Uploading, then Added, "Added as version N", or the API's "Rejected: …" sentence.
  - On success the area closes and clears. On rejection it keeps the text.
  - The new Source appears in the list right away.
  - The area is hidden without `can_add_sources`.

**Never:** No rate limit. It's deferred until after the demo, and its deferred-work entry stays open. No title field or custom name for pasted text. No editing of pasted text. No changes to the file-upload path's behaviour. No migration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Paste | Collaborator posts "  Customer needs SAP sync\n" | 201: kind note, filename `Pasted text`, v1. Blob is the trimmed bytes, `ref_count` 1, one trace event | N/A |
| Sales rep | Sales representative collaborator pastes | 201 | N/A |
| Reader only | HoD who isn't a collaborator | 403, nothing stored | N/A |
| Non-reader | Unknown or unreadable Opportunity | 404, nothing stored | N/A |
| Blank | `"   \n\t"` | 422 `file_empty` | Nothing stored |
| Too long | 1,000,001 characters after trimming | 422 `file_too_large` | Nothing stored |
| At limit | Exactly 1,000,000 characters, including multi-byte ones | 201 | N/A |
| NUL or surrogate | Text containing `\u0000` or a lone `\ud800` | 422 `file_content_mismatch` | Nothing stored |
| Same text | The same text pasted again | 201, same Source v2, `ref_count` 2 | N/A |
| Matches upload | Paste identical to an uploaded `.txt` file's bytes | 201, the next version of that `.txt` Source | N/A |
| Bad body | Missing `text` or not a string | 422 `validation_error` | Nothing stored |

</frozen-after-approval>

## Code Map

- `backend/app/modules/intake/application/sources.py:110` -- `add_file`. Move everything after `put_stream` (advisory lock, find or insert, reference, version, trace, log, re-read) into a private helper. Both `add_file` and the new `add_text(uow, actor, opportunity_id, text, *, store)` use it. Authorize first, as `add_file` does. Store the text with `store.put_stream` over a single chunk, `max_bytes` set to the encoded length.
- `backend/app/modules/intake/domain/sources.py` -- add `PASTED_TEXT_FILENAME`, `TEXT_MAX_CHARS = 1_000_000`, the three new messages, and a pure `clean_pasted_text(raw) -> str` that raises domain errors. Map these to the platform errors in `application` (`errors.py:150-175` already has the four codes).
- `backend/app/modules/intake/application/{models.py,public.py}` -- add the `AddTextSource` request model and export `add_text`.
- `backend/app/modules/intake/api/routes.py` -- add `POST ""/text`, `operation_id="add_text_source"`, using `_responses(403, 404, 422)` with the 422 description updated.
- `backend/tests/test_intake_sources.py` -- reuse its seeding and token helpers and the temp storage fixture. Add a test per matrix row, plus a domain unit test for `clean_pasted_text`.
- `web/src/lib/api/schema.d.ts` -- regenerate from a local uvicorn, not the Docker `api` (see memory).
- `web/src/app/opportunities/actions.ts:334` -- `addSource`. Add `addTextSource(opportunityId, text): Promise<AddSourceResult>` with the same status mapping, and reuse `rejectionReason`.
- `web/src/components/opportunities/source-upload.tsx` -- add the paste area. Reuse `outcome`, `settle`, the `queue` and the rows, so pastes and files share one ordered queue. Follow the existing Esc-layering pattern used by other inline editors (`inline-field.tsx`), so Esc doesn't also trigger shell handlers.
- `web/src/components/opportunities/source-upload.test.tsx` -- extend it, mocking `addTextSource` the same way as `addSource`, plus axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/domain/sources.py` -- the text rules and messages -- pure and unit-testable
- [x] `backend/app/modules/intake/application/{sources.py,models.py,public.py}` -- `add_text` plus the shared record helper -- one write path for both kinds of input
- [x] `backend/app/modules/intake/api/routes.py` -- the text route
- [x] `backend/tests/test_intake_sources.py` (and the domain test file) -- every matrix row, run as `psa_app`
- [x] `web/src/lib/api/schema.d.ts`, `web/src/app/opportunities/actions.ts` (+ test) -- the client type and server action
- [x] `web/src/components/opportunities/source-upload.tsx` (+ test) -- the paste UI, keys, row outcomes, list update and axe

**Acceptance Criteria:**
- Given a collaborator on the Sources tab, when they choose Paste text, paste a call note and press Add, then a `Pasted text` row says Added and a Note Source named `Pasted text` tops the list.
- Given CI, when it runs, then the backend and web checks, including the generated-client drift check, pass.

## Implementation Notes

- `clean_pasted_text` raises `PastedTextEmptyError` / `PastedTextTooLongError` / `PastedTextUnsupportedError` (subclasses of `PastedTextError`, each carrying the UI sentence); `add_text` maps them to `file_empty` / `file_too_large` / `file_content_mismatch`. Lone surrogates are detected by a failed UTF-8 encode.
- `add_file` and `add_text` share `_authorized_uploader` (404, then 403) and `_record` (advisory lock, find or insert, reference, version, trace, log, re-read).
- `AddTextSource` uses `StrictStr` and `extra="forbid"`, so a non-string `text` or an extra field is `validation_error`.
- Web: `addTextSource(opportunityId, text)` shares `addSourceResult` with `addSource`; a 422 without a "Rejected:" detail falls back to "Rejected: the text couldn't be read". The paste area keeps Add disabled while a paste is pending, and a late success can't close an area reopened after Cancel.
- `schema.d.ts` was regenerated from a dumped `app.openapi()` of the working tree (the diff is additions only).

- Review patch: the text route reads its body through a byte cap (`TEXT_BODY_MAX_BYTES`), so an oversized body is a 422 `file_too_large` before authorization: a non-collaborator sending more than the cap gets 422, not 403/404. Nothing leaks: the cap is public and nothing is read or stored. The request body is declared through `openapi_extra`, so the generated client inlines `{ text: string }` instead of a named `AddTextSource` schema.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH, VG | `POST …/sources/text` has no body cap. FastAPI reads the whole JSON body, even before auth, so any size is buffered | medium | No proxy (`no-reverse-proxy`), no size middleware in `main_api.py`. The upload route caps `Content-Length` and the stream; this route doesn't | patch |
| 2 | ECH | Esc during IME composition closes the area and discards the draft | low | `onPasteKeyDown` doesn't check `nativeEvent.isComposing`; direct one-line guard | patch |
| 3 | ECH | Edits made while a paste is pending are wiped when it succeeds | low | Textarea stays editable while `pasteBusy`; `closePaste` clears it; direct `readOnly` | patch |
| 4 | ECH, BH | Cancel or Esc while pending, then a rejection: the text is gone | low | `closePaste` clears `pasteText` while the request is still queued; direct fix is to make Cancel and Esc inert while busy | patch |
| 5 | VG | A late success closing a reopened area is untested | low | No test reopens the area while pending. After #4 the area can't close while busy, so the test asserts that instead | patch (test) |
| 6 | VG | Focus is returned only when it's still inside the area, and the negative case is untested | low | Only the inside-area case is asserted; cheap to cover in #5's pending test | patch (test) |
| 7 | BH | 422 description omits that unknown fields (`extra="forbid"`) are also `validation_error` | low | Route description text; direct wording fix | patch |
| 8 | BH | The UI never states the 1,000,000-character limit | low | The hint only gives shortcuts; direct copy addition | patch |
| 9 | BH | The Paste text button has `aria-expanded` but no `aria-controls` | low | Direct attribute | patch |
| 10 | BH | No 401 test for the text endpoint | low | Other routes test 401; direct test | patch (test) |
| 11 | BH, ECH | Browser `trim()` and Python `strip()` differ (BOM, U+001C–001F, U+0085) | low | Only text made entirely of those characters; the API still decides and shows its sentence | reject |
| 12 | BH | A paste identical to an `.eml` or `.vtt` becomes a version of that email or transcript Source | low | Follows the frozen same-bytes rule (Part A #11 rejected the same); rare | reject |
| 13 | BH | Text rejections reuse `file_*` codes | false | The frozen spec specifies these codes | reject |
| 14 | BH | Every paste row is named "Pasted text" | false | The frozen spec specifies the row and filename `Pasted text` | reject |
| 15 | BH | Body validation runs before auth: a non-reader with a malformed body gets 422, not 404 | low | Same as every other JSON route in the app; no data leak | reject |
| 16 | BH | `single_chunk` generator instead of a `put_bytes` helper | low | No named harm | reject |
| 17 | BH | `trim()` runs on every keystroke over up to 1M characters | low | O(n) native trim, a few ms at 1M | reject |
| 18 | BH | No log-privacy test for pasted content | low | `_record`'s log line is unchanged from Part A and holds ids and sizes only | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks:**
- On the Sources tab, paste a few paragraphs and Add, paste the same text again (v2), and try blank text (Add disabled).
