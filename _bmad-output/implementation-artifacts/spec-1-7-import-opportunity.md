---
title: 'Story 1.7 (demo slice): start a New Opportunity from an email or transcript'
type: 'feature'
created: '2026-10-06'
status: 'done'
baseline_commit: '28d049a3df970685e7e395c3bfe849613a85049b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Creating an Opportunity means retyping what is already in the customer's email or the meeting transcript (customer, what they want, industry, deadline), then uploading that same file again as a Source.

**Approach:** On the New Opportunity form, **Import from file** takes one `.eml` or `.vtt` (also `.txt`, `.docx`, `.pdf`). The worker reads it and suggests the form's fields; the presales engineer reviews and edits them, then creates the Opportunity, and the imported file becomes its first Source so the usual pipeline (parse → Requirements → Gaps → Estimate → Assessments) starts by itself.

## Boundaries & Constraints

**Always:**
- **Approach (decided):** the model reads the file in the worker; built now, before the demo freeze.
- **No model in the API (AD-8):** the API stores the file and queues an `opportunities.read_import` job; the worker parses it with the existing intake parsers and asks a new `opportunity_intake_agent` (`0.1.0`, prompt v1, chat profile) for suggestions. The form polls (2 s, stops after 2 min with "Couldn't read the file — fill the form in by hand").
- **Suggestions:** `title`, `customer_name`, `industry`, `products` (0–5) and `target_proposal_date` (only if the text states a deadline; never in the past), each with the short quote it came from. Each passes the form's own validation or is dropped. Fields the agent can't support stay empty — never invented — with two exceptions (renegotiated by the user, 2026-10-06): **industry** may be inferred from what the customer does (a short industry label such as "Food & grocery distribution"), quoting the text it is inferred from; and when the file states no deadline, the form proposes a **default target proposal date** of today + 30 days. The customer is the buying organisation, not the vendor or a person.
- **Form:** suggestions fill only empty fields (a value the user already typed wins), are marked "From file" with the quote on hover/focus (an inferred industry is marked "Inferred from file"; the default date "Default: 30 days from today, not in the file"), and stay editable; nothing is created until the user presses **Create**. **Clear import** removes the suggestions and the file.
- **On create:** the import is consumed: the stored file is attached as the Opportunity's first Source (same storage, size limit and parse job as an upload), in the same Unit of Work as the Opportunity. An import is single-use, belongs to its uploader, and expires after 24 h (a cleanup is not needed for the demo; expired imports are refused 410).
- **API:** `POST /opportunity-imports` (multipart, same size and type limits as Source upload; action `opportunities.opportunity.create`), `GET /opportunity-imports/{id}` (`queued | running | succeeded | failed` + suggestions; uploader only), and `NewOpportunity` gains optional `import_id`.
- **Migration:** `opportunities_imports` (id, uploader, file ref, filename, status, error_code, suggestions JSON, created_at, consumed_at); grants SELECT/INSERT, UPDATE on status/suggestions/consumed columns only, no DELETE.
- **Trace:** `opportunities.opportunity.created` gains `from_import: true`; the Source added is traced as any upload. No file text or quotes in logs or trace.
- Keyboard and axe as the rest of the form; sales representatives can't create Opportunities, as today.

**Never:** No creating the Opportunity without the user pressing Create, no several files per import, no mailbox/Teams connector (Stories 13.4/13.5), no Requirement extraction before create, no LangGraph code.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Email | `02-email-it-integration-follow-up.eml` | Customer "Meridian Fresh Foods", a title, industry and products suggested with quotes; fields marked "From file" | N/A |
| Transcript | `01-discovery-call-teams-transcript.vtt` | Same fields suggested from the call | N/A |
| Deadline | Text says "Proposal due: 23 October 2026" | Target date 2026-10-23 | A past date is dropped |
| No deadline | The transcript states no deadline | Target date = today + 30 days, marked "Default" | User may change it |
| Industry inferred | The IT email never names the industry | Industry suggested from what the customer does (e.g. "Food & grocery distribution"), marked "Inferred from file" with its quote | N/A |
| Typed first | User typed the customer before importing | The typed customer stays; other empty fields fill | N/A |
| Create | Review and Create | Opportunity created; the file is its first Source and parsing starts | N/A |
| Unreadable | Corrupt file or no usable text | Import `failed`; "Couldn't read the file — fill the form in by hand" | Form still works |
| Bad type / size | `.exe`, or over the upload limit | 415 / 413 before any job | Message under the button |
| Reuse | Same `import_id` used twice, or by another user | 409 / 404 | N/A |

</frozen-after-approval>

## Code Map

- Web: `web/src/app/opportunities/new/page.tsx`, `web/src/components/opportunities/create-form.tsx` (+ tests), `web/src/app/opportunities/actions.ts` (create action, Source upload action), `web/src/lib/upload-limits.ts`.
- Backend: `backend/app/modules/opportunities/application/models.py` `NewOpportunity` (fields and validators), `application/opportunities.py` (create), `domain/rules.py`; Source upload in `backend/app/modules/intake/api/routes.py` and `intake/application` (storage, parse job), parsers `intake/adapters/parsers/{eml,vtt,txt,docx,pdf}.py`; `platform/storage.py`, `platform/multipart.py`; jobs `platform/jobs/registry.py`; agent pattern `backend/app/agents/red_team_agent/` and `agents/contract.py`; AD-8 contract `backend/pyproject.toml:83-86`.
- Tests follow `backend/tests/test_intake_*` (fake gateway, hidden jobs) and `create-form.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/*_0020_opportunities_imports.py`, `opportunities/adapters/**` -- imports table and grants
- [x] `backend/app/agents/opportunity_intake_agent/**` -- agent, schema, v1 prompt (data blocks fenced with a per-call token, like `red_team_agent`)
- [x] `backend/app/modules/opportunities/{application,api}/**`, identity if needed, catalogue -- import upload and read routes, `opportunities.read_import` job (registered in `main_worker`), validation of suggestions, `import_id` on create attaching the file as the first Source through `intake.application.public`
- [x] `backend/tests/**` -- every matrix row (fake gateway, hidden jobs), grants, AD-8 contract still kept
- [x] Web: `schema.d.ts`, import actions + tests, **Import from file** on `create-form.tsx` with polling, "From file" markers with quotes, Clear import, tests with axe

**Acceptance Criteria:**
- Given the demo email or transcript, when the presales engineer imports it on New Opportunity, then the form fills with the customer and the other fields it supports, each traceable to a quote, and Create makes the Opportunity with that file as its first Source.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **413 / 415 vs the Source upload's 422.** The matrix asks 415 / 413 for a bad type or size, while Source upload answers 422 `file_type_not_allowed` / `file_too_large`. Imports use the same checks (`intake.store_upload`, factored out of `add_file`) and the same `code` and sentence, but with status 415 / 413 (`UploadTypeNotAllowedError`, `UploadTooLargeError`). A spoofed or empty file stays 422 as for uploads. `.msg` is accepted like a Source upload, then fails to read (`unreadable`).
- **Module cycle.** `intake` already imports `opportunities.application.public`, so the import commands and the job live in `opportunities/application/imports.py`, which `public.py` does not re-export; the routes and `main_worker` import it directly. The Source is added through the new `intake.add_stored_file` (same write path, trace and parse job as an upload); the file is parsed in the worker through the new `intake.read_stored_text` (same parse child process and limits).
- **File ref.** `opportunities_imports` stores `file_sha256` and `size_bytes`; the import adds one `platform_files` reference, and the Source version adds its own on create.
- **Quote check.** Besides the form's rules, a suggestion is kept only when its quote (at least 3 non-space characters, at most 300) appears in the parsed text (whitespace and case ignored), and the customer name must appear in its own quote — the "never invented" guard. Only the first 40,000 characters of the text go to the model.
- **Failed or timed-out import.** The form shows "Couldn't read the file — fill the form in by hand" and keeps the import: the file still becomes the first Source unless the user presses Clear import (the API accepts an `import_id` in any status).
- **Editing a filled field** removes its "From file" marker (it is the user's value now); Clear import empties only fields still holding the file's value.
- **Trace.** `opportunities.opportunity.created` now always carries `from_import` (`false` for a plain create); two existing tests that asserted an empty payload were updated.
- **Retry.** `opportunities.read_import` is interactive priority, 2 attempts; an unreadable file fails at once without a model call. A final attempt cancelled by the job timeout marks the import `failed` / `model_timeout` (shielded write).
- **Gone / re-import / uploading.** A poll answered 404/410 drops the import (the file won't be attached). Choosing a second file clears the first one's suggestions (typed values stay). Create is disabled while a file uploads. A consumed import is 409 even once expired.
- **Inferred industry / default date (renegotiated).** The agent returns `industry_inferred`; the API stores it in the suggestions and also sets it whenever the industry's value doesn't appear in its quote (the quote must still be real text, ≥ 3 characters). The form marks it "Inferred from file". The default date (today + 30 days, UTC) is filled by the web form only, after a successful, failed or timed-out read, when the date field is empty and the file gave no valid deadline; it is marked "Default: 30 days from today, not in the file", is not counted in "Filled N fields", and is removed by Clear import or a new import.
- **Blob reference.** The import's `platform_files` reference is never released: `platform.files` has no release function (nothing deletes blobs in R1), so a consumed import's blob ends with `ref_count` 2.

## Spec Change Log

- **2026-10-06 (human renegotiation, during review):** the user asked that the industry be inferred when the file doesn't name it, and that a missing deadline default to a proposal date. Amended the frozen Suggestions and Form bullets and added two matrix rows (default: today + 30 days; inferred industry marked as such). KEEP: everything else in the reviewed implementation, including the quote guard (an inferred industry still needs a real quote from the file; the customer must still appear in its quote).

## Review Triage Log

Pass 1 (2026-10-06; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | Create during upload drops the file and orphans the import (blind, edge) | medium | `importId` undefined while `uploading`; Create not disabled | patch |
| 2 | After 404/410 while polling, the form keeps the dead id and promises the file will be attached (blind) | medium | `gone` → `failed` with the id | patch |
| 3 | A second import leaves the first file's values unmarked; Clear import hidden mid-upload (edge ×2) | low | `startImport` doesn't reset markers | patch |
| 4 | Zero usable suggestions announced as "Filled 0 fields" (blind) | low | `fieldCount` | patch |
| 5 | Final-attempt timeout leaves the import `running` (edge, blind) | low | CancelledError skips `except Exception` | patch: shielded fail |
| 6 | Consumed and expired → 410, not 409 (blind, edge) | low | Expiry checked first | patch |
| 7 | Quote check doesn't tie the value to the quote; one-letter quotes pass (blind, edge) | medium | Injection could push any customer with a real sentence | patch: min quote, customer in quote |
| 8 | Prompt limits (200/80) differ from code (300/200); truncation unstated (blind) | low | `prompts/v1.md` | patch |
| 9 | Import blob reference never released (blind, edge) | low | `add_reference` without release | patch if a release API exists |
| 10 | VG: expiry call site only tested with a stub | medium | Pre-verified | patch: aged row |
| 11 | VG: `model_timeout` / `output_invalid` mapping untested | medium | Pre-verified | patch: parametrised |
| 12 | VG: failed import still sends `import_id` on Create untested | medium | Pre-verified | patch |
| 13 | VG: stale reply after Clear import untested | medium | Pre-verified | patch |
| 14 | Non-model failures reported as `model_unavailable` (blind, edge) | low | Same mapping as the other jobs | reject |
| 15 | No per-user rate limit on imports (blind) | low | Same as Source upload; internal app | reject |
| 16 | UI gives up at 120 s, job may run 900 s × 2 (blind, edge) | low | The file is still attached; live calls take seconds | reject |
| 17 | `add_stored_file` doesn't verify the blob (blind) | low | Internal public API, only called with a stored import's file | reject |
| 18 | Unused index on the imports table (blind) | low | Harmless | reject |
| 19 | Missing tests: create while queued/running, read after consume, concurrent creates, `.msg`, downgrade (blind) | low | Row lock and status rules are simple; downgrade verified by hand | reject |
| 20 | `schema.d.ts` missing from the diff; spec unfinished (blind) | false | Left out of the review diff on purpose (generated); spec sections fill during review | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
