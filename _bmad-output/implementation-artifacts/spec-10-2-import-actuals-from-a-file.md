---
title: 'Story 10.2: Import Actuals from a file'
type: 'feature'
created: '2026-10-27'
status: 'done'
baseline_commit: 'dc3a8f90eec9f8f2daaca26a176a3dee01ed2fce'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-1-record-actuals-per-estimate-line.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Delivery managers retype Actuals that already exist in their delivery spreadsheets. On the Actuals tab, **Import from file** is disabled with "Import arrives in a later release".

**Approach:** Enable **Import from file**. It opens an import dialog with **Download template** (an .xlsx file, one row per Baseline line, through a signed link) and **Choose file** (.xlsx or .csv). The upload is stored through `platform.storage` and parsed by an `actuals.import_file` worker job in the parse sandbox. The delivery manager then reviews a preview of rows to create, rows to correct and invalid rows with reasons. On **Confirm**, all rows are applied in one Unit of Work through the same validate-and-write path as Save Actuals. The tab header stays exactly as the new mockup draws it, and the import UI reuses the mockup's dialog pattern and the Sources **Parse failed** row pattern.

## Boundaries & Constraints

**Always:**
- Template columns: Line ID (estimate line UUID), Line (`L{n}`), Integration Type, Work Package, Estimate h, then empty columns for Kind, Milestone label, Actual h, Duration days, Cost, Currency, Variance cause, Failed Assumptions (`A{n}` labels, comma-separated), Note and Correction reason.
- The template download is traced with `opportunity_id`.
- Upload checks: actuals size limit, extension allowlist {xlsx, csv}, and a magic-byte check (ZIP with an `xl/` entry for xlsx, UTF-8 text for csv). Files are content-addressed by SHA-256, and parsing never happens in `api`.
- Preview rows are validated with manual-entry rules against the current state. Each reason reads "Row 7: line ID not in Baseline v3".
  - A row whose Actual fields are all blank is skipped.
  - A row for a line that already has a current Actual is a correction. It needs the row's Correction reason or one batch reason.
- Nothing is written before **Confirm**. Confirm is blocked while any row is invalid, unless invalid rows are excluded. It takes `If-Match`, rejects stale previews with 412, and writes nothing on any error.
- On success, write one `actuals.import.completed` event (file SHA-256, created, corrected, excluded and skipped counts) plus the usual per-row `recorded`/`corrected` events.
- Same SHA-256 already applied on this Opportunity: the preview warns "This file was already imported on 14 Oct", and Confirm needs an extra tick.
- When the job is `dead`, the import row shows a red **Parse failed** pill, the reason and **Retry**. Manual entry stays available.
- Only delivery managers who can record Actuals can import. Others get 403, and the button is hidden for them.

**Never:**
- No parsing in the API process and no partial writes.
- No new Actual rules beyond manual entry.
- No changes to the header layout the mockup draws, no Reports (10.3) and no cost on Estimate lines.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | 3 filled rows, no existing Actuals | Preview "3 to create" → Confirm → 3 `recorded` + 1 `import.completed` | N/A |
| Correction | Row for a line with an Actual, no reason anywhere | Row invalid "correction reason missing" until a batch reason is entered | Confirm blocked |
| Bad line | Line ID from another version | "Row 7: line ID not in Baseline v3" | Exclude or fix |
| Missing cause | Final 41 h vs 36 h, blank cause | "Row 12: variance cause missing for a final Actual" | Exclude or fix |
| Wrong type | `.pdf` renamed `.xlsx` | Not stored | 415 |
| Unparseable | Corrupt xlsx | Parse failed + reason + Retry after retries | Manual entry still works |
| Repeat file | Same SHA-256 applied before | Warning with date; needs explicit tick | 409 without the tick |
| Stale | Actuals changed after preview | Not applied | 412, preview refreshes |
| Non-DM | Reviewer POSTs an upload | Not stored | 403 |
| Blank line | Row with no Line ID | "Row N: line ID missing" | Exclude or fix |

**Decisions (2026-10-27):**
- The preview is a wide dialog (about 720 px) that scrolls. It uses the mockup's dialog pattern (DialogContent, 20 px title, outline Cancel and primary Confirm), with the Actuals table visible behind it.
- A row with a blank Line ID is invalid. Unplanned work stays manual, in the Inspector.
- The spec is kept whole at about 2,300 tokens, with no split.

</frozen-after-approval>

## Code Map

- `backend/app/modules/actuals/application/record.py:303` `save_actuals`. Extract lines 312–396 into `apply_items(uow, actor, resource, user_id, items, reason)` so Save Actuals and import Confirm share one validate-and-write path, including the `_check`:135 and `_error`:110 shapes.
- Upload: copy `modules/intake/application/sources.py:167` `store_upload`, `platform/storage.py:57` `put_stream(check=)`, `platform/files.py:33` `add_reference` and `platform/multipart.py:46` `MultipartFile`. Add `_is_xlsx` and `csv` to `platform/upload_validation.py` (pattern `_is_docx`:83, `_is_utf8_text`:94). Add an `actuals_import_max_bytes` setting in `platform/config.py`. For 413/415/422 route responses, see `opportunities/api/imports_routes.py:82-110`.
- Preview flow: Story 1.7 `opportunities/application/imports.py` (`upload_import`:151, worker status with `from_statuses`, `create_from_import`:223 consume-once) and its table `opportunities_imports`.
- Jobs: `platform/jobs/registry.py:85` `JobType` plus `register`, `queue.py:40` `enqueue`, and `PermanentJobError`. On the last attempt, mark the import failed (see `intake/application/jobs.py:143`). Retry follows `intake/application/parsing.py:33` `retry_parse` (409 when not failed).
- Sandbox: `platform/parsing/runner.py:108` `run_parse(..., child_module=)`. Add an `actuals/adapters/import_cli.py` child that reads xlsx with openpyxl 3.1.5 (`read_only`, `data_only`) or csv with stdlib and prints a JSON list of raw rows.
- Template: `gaps/application/question_export.py:66` `export_questions` (render, `put_stream`, `downloads.sign`, trace) and `ExportStorage`:51. Write the workbook like `estimates/adapters/export_xlsx.py:68`. Line labels and `A{n}` come through `estimates.public` (`version_lines`, `version_assumptions`). `A{n}` must match the Register's order in `web/src/components/opportunities/assumptions-register.tsx:78`.
- Wiring: migration `20261027_0054_actuals_imports.py` (down revision `0053_actuals_actuals`). Trace payloads go in `platform/trace/catalogue.py` after `ActualsDeliveryClosed`:921. Actions go in `identity/actions.py:103` (`ACTUAL_IMPORT`) and `identity/domain/policy.py:119,171,207,240`, plus `scripts/seed_auth0.py`. Register the job where `PARSE_SOURCE_JOB` is registered.
- Web:
  - `components/opportunities/actuals-table.tsx:297-311`: replace the disabled button. Keep the header.
  - New `actuals-import.tsx`: a dialog built like `:634-652` and `set-baseline.tsx:244`. Reuse `ReasonInput`, the `ParseStatusPill` and **Retry** from `sources-list.tsx:70,207-251`, `source-upload.tsx:151` (FormData through a server action), and `questions-export.tsx:36` for the download.
  - Server actions go in `app/opportunities/actions.ts:4005+`. Strings and types go in `lib/actuals.ts:28-45`.
  - Poll the import status every `PARSE_POLL_MS` while it is queued or running. On apply, the tab re-reads through the existing `actuals.*` frames.
  - Run `npm run gen:api`.
- Tests: `actuals-table.test.tsx:168-191` (Import assertions), `web/src/test/axe.ts`, and `backend/tests/test_actuals_*.py`.

## Tasks & Acceptance

**Execution:**
- [x] `actuals/application/record.py`: extract `apply_items` and keep the Save Actuals behaviour. This gives the import one shared rule path.
- [x] Migration 0054 plus `adapters/models.py`/`repository.py`: add `actuals_imports` (id, opportunity_id, uploaded_by, file_sha256, size_bytes, filename, file_kind, status `queued|running|parsed|failed|applied`, error_code, rows JSONB, created_at, applied_at, counts). Grant `psa_app` SELECT, INSERT and UPDATE. This is where the import state lives.
- [x] `platform/upload_validation.py` and `config.py`: xlsx/csv magic checks and the size limit, for upload safety.
- [x] `actuals/adapters/import_cli.py`, `template_xlsx.py`, and `application/imports.py`:
  - `download_template`
  - `upload_import` (store, add the reference, enqueue)
  - the `actuals.import_file` job
  - `get_preview` (validates through the shared rules and flags duplicates)
  - `retry_import`
  - `apply_import` (If-Match, exclusions, batch reason, the duplicate tick, `apply_items`, the trace)
- [x] `actuals/api/routes.py`:
  - `GET …/actuals/template`
  - `POST …/actuals/imports` (multipart)
  - `GET …/actuals/imports/latest` and `GET …/{import_id}`
  - `POST …/{import_id}/retry` and `POST …/{import_id}/apply`
- [x] Identity, trace catalogue (`actuals.template.exported`, `actuals.import.completed`), seed and job registration.
- [x] `backend/tests/test_actuals_import*.py`: the I/O matrix, a parse failure leaving the job `dead`, all-or-nothing rollback, 403, and a check that the API never parses.
- [x] Web: the import dialog, actions, strings and the Retry row, with vitest and axe tests that update the 10.1 Import assertions.

**Acceptance Criteria:**
- Given a delivery manager on the Actuals tab, when they choose **Import from file**, then the dialog offers **Download template** and **Choose file**, and the tab header matches the mockup.
- Given a preview with 2 valid rows and 1 invalid row, when the delivery manager excludes the invalid row and confirms, then exactly 2 Actuals are written and the counts in `import.completed` include 1 excluded.
- Given a reviewer, when they open the tab, then no Import action is shown.

## Implementation Notes

- Shared path: `record.check_items` (validate only, used by the preview) and `record.apply_items` (validate, 422 or write) back both Save Actuals and Confirm. An import passes per-row `item_reasons` (a row's Correction reason, falling back to the batch reason), its own row-read problems (`read_errors`) and a `describe` hook that words rule errors as "Row N: ...".
- Action `actuals.actual.import` joins `ACTUALS_ACTIONS` (delivery managers only, people only); Confirm also checks `actuals.actual.record`, and `.correct` when a row corrects.
- Confirm's `If-Match` is the Actuals tab `row_version` the preview was checked against; the preview returns it. Statuses: `queued|running|parsed|failed|applied`; reading errors `unreadable|timeout|too_large|missing_columns|too_many_rows`.
- 415 covers both a type off the allowlist (`file_type_not_allowed`) and content that doesn't match it (`file_content_mismatch`, new `UploadContentMismatchError`). Empty file is 422. Limit `PSA_ACTUALS_IMPORT_MAX_BYTES` (5 MB).
- The child reads the blob through a `BytesIO` (openpyxl refuses an extension-less path). The template adds a "Lists" sheet (kinds, causes, `A{n}` with wording). Template download goes through a web route (`/api/opportunities/{id}/actuals-template`) like the questions export.
- Choices beyond the spec: a row whose cells name a cause by label or value is accepted (`Estimation error` or `estimation_error`); in numbers a `,` is a thousands separator only in 3-digit groups ("1,250.50"), otherwise a single `,` with no `.` is a decimal comma ("41,5" is 41.5), and anything else is "must be a number"; Confirm with every row blank or excluded is 422 "Nothing to import". The preview of a parsed import is shown only while delivery is open.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-27). Reviewers: B = blind-hunter, E = edge-case-hunter, V = verification-gap.

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| B4/E1 | A `;` CSV with decimal commas is read ten times too big | high | `domain/imports.py` `_decimal` strips every `,`, so "41,5" becomes 415 with no error; `;` is the usual European Excel export | patch |
| B10/E7/E8/E12/V1 | A dead job can leave the import `running`, and polling stops silently | medium | `jobs/runner.py:136` `asyncio.timeout` cancels the handler; `import_file` catches `Exception` only, so CancelledError skips `_mark_failed`; `retry_import` then answers 409; the dialog's poll stops at `PARSE_POLL_LIMIT_MS` with no message; the retry-exhaustion branch has no test | patch |
| B3/E2 | A quoted CSV cell with a line break splits the row | medium | `import_cli._csv` uses `text.splitlines()`; Notes with line breaks are ordinary; row numbers then drift | patch |
| B5/E4 | Float noise from xlsx formulas makes valid figures invalid | medium | `cell_text` uses `repr(float)`, so 41.300000000000004 fails the cost precision rule | patch |
| B8/E6/V2 | A row's own correction reason that is too long shows as "missing", a batch reason seems to fix it, then Confirm gives 422 | medium | `_reasons` reports it as `field: reason`; `_preview` maps that to `reason_missing`; `rowProblems` clears it on a batch reason; no test | patch |
| E10 | Applying an import discards unsaved inline edits | medium | `actuals-table.tsx` `onApplied` calls `setDrafts({})` | patch: Import is disabled while the table has unsaved edits |
| V3 | Template route and import server actions are untested | medium | no `route.test.ts`; `actions.test.ts` has no import block; the component tests mock every action | patch: tests |
| E5 | More than 50 failed Assumptions in a row gives 500 | low | `ActualInput.failed_assumption_ids` has `max_length=FAILED_ASSUMPTIONS_MAX` (50); `_input` builds it unguarded; one-line row problem | patch |
| E3 | A title row above the CSV header defeats delimiter detection | low | `_csv` counts delimiters on the first line only; widening to the first `HEADER_SEARCH_ROWS` lines is a direct change | patch |
| E9 | A parsed import shows "Every row is blank" once delivery is closed or no Baseline exists | low | `_view` returns no rows when `open_baseline` raises; the dialog has no other message; direct copy fix | patch |
| B12 | The preview's `row_version` is read after the rows are checked | low | `_view` calls `change_count` after `_preview`; apply re-validates under the lock, so no bad data; moving the read is a direct reorder | patch |
| B14 | Import files and raw rows are kept forever | medium (unverified scope) | no DELETE grant, and `platform_files` references are never released; Story 10.6's purge must cover `actuals_imports` | defer |
| B1/E11/V-o1 | Windows cache files under `backend/%SystemDrive%` in the change | false | caused by the review's intent-to-add staging, not by the story; un-staged with `git reset` during triage; the folder is untracked and pre-existing on `main` | reject |
| B2 | Sprint status and spec status disagree | false | by design: step 5 syncs sprint status | reject |
| B6 | Template Work Package column always empty | false | 10.1 decision: planned-line Actuals have no Work Package | reject |
| B7 | Template has no dropdowns or protected columns | low | the Lists sheet covers it, the preview catches mistakes, and validation adds complexity | reject |
| B9 | Retry offered for deterministic failures | false | the spec requires Parse failed + Retry (UX-DR20) | reject |
| B11 | Repeat date is UTC with no year | low | rare (an import near midnight, or one from a year ago); the spec's copy is "14 Oct"; a fix needs user time zones | reject |
| V-o3 | Preview needs `actuals.actual.correct` | low | every delivery manager holds both permissions (`ACTUALS_ACTIONS`); theoretical | reject |

## Design Notes

The parsed rows are stored raw, and the preview is validated fresh on every read and again under the lock on apply. A preview therefore never applies data that another save made invalid. Cost is entered in major units and converted with the currency's minor-unit exponent (the 10.1 formatter). Kind defaults to `final` when it is blank.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_actuals_* tests/test_architecture.py -q`: expected to pass.
- `cd backend && uv run lint-imports && uv run ruff check . && uv run mypy app`: expected to be clean.
- `cd web && npm run gen:api && npm run typecheck && npm test -- actuals && npm run lint`: expected to pass.

**Manual checks:**
- Screenshot the Actuals tab and the import dialog, and compare them with the mockup's Actuals screen and dialog style.
