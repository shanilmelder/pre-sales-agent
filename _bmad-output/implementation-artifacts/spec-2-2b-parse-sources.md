---
title: 'Story 2.2 (Part B): Parse Sources in the background'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '8d6f39d87f9f83fd3f178c7f87d6074e23117cd1'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Added Sources are stored, but nobody can read their text. Extraction (Story 2.5) needs plain text with stable offsets, and one broken file must not block the rest.

**Approach:**
- Every added Source version enqueues an `intake.parse_source` job (Story 2.2 Part A queue).
- The worker parses the file in a sandboxed subprocess and stores the extracted text as an immutable blob.
- The Sources tab shows each version's parse state, with **Retry** and **Paste text instead** on failure.

## Boundaries & Constraints

**Always:**
- **Enqueue:** the shared `_record` path in `intake/application/sources.py` enqueues `ParseSource(source_id, version)` (`interactive` priority) in the same Unit of Work as the version row, so uploads and pastes both get parsed.
- **Parse state** lives in a new `intake_source_parses` table, because version rows are immutable. Columns: `source_id`, `version` (PK), `status` (`queued | parsing | parsed | failed`), `error_code`, `text_sha256`, `char_count`, `parser`, `updated_at` and `row_version`. The row is inserted `queued` together with the version.
- **Sandbox:**
  - The handler sets `parsing`, then runs `python -m app.modules.intake.adapters.parse_cli <blob path> <ext>` in a subprocess. It has a wall-clock limit (`PSA_PARSE_TIMEOUT_S`, default 120), and on Linux `RLIMIT_AS` (`PSA_PARSE_MAX_MEMORY_MB`, default 1024) and `RLIMIT_CPU`, set in `preexec_fn`. On other platforms only the timeout applies.
  - The child writes UTF-8 text to stdout and exits non-zero with a short code on stderr when it can't parse.
  - The parent never parses in-process. No Unit of Work is open while the child runs.
- **Parsers** (the extension is from the version's filename; pasted text is `.txt`):
  - `.txt`: as is.
  - `.eml`: stdlib `email` with the default policy. Subject, From, To and Date lines, a blank line, then the text/plain parts. If there are none, the text/html parts with tags stripped. Attachments are ignored.
  - `.msg`: not parsed yet. It fails with `not_supported`.
  - `.vtt`: in-house. Drop the `WEBVTT` header, cue ids, timing lines and NOTE blocks. Turn `<v Name>text` into `Name: text`, strip other tags, and join cues with newlines.
  - `.pdf`: `pypdf` (BSD), pinned. Page texts joined by a blank line.
  - `.docx`: read `word/document.xml` with the stdlib (`zipfile` plus ElementTree). One line per `w:p`, with `w:t` concatenated, `w:tab` as a tab and `w:br` as a newline.
- **Normalising:** the output has CRLF and CR turned into LF and is NFC-normalised. Story 2.5's code-point offsets index this exact string, so it must never change after storage.
- **Storage:**
  - The text is stored UTF-8 encoded through `platform.storage` (`put_stream`), referenced in `platform_files`, and recorded on the parse row with `parsed`, `text_sha256`, `char_count` and `parser` (`<name>@<version>`).
  - `intake.source.parsed` trace event, with `{version, char_count}` only.
  - An empty result is `failed` with `no_text`.
- **Failure codes:** `unreadable` (corrupt, encrypted or a parser error), `not_supported` (`.msg`), `no_text` (for example a scanned PDF), `timeout` and `too_large_output` (more than 5,000,000 characters).
  - Permanent codes (`unreadable`, `not_supported`, `no_text`, `too_large_output`) mark the parse `failed` and finish the job without retry.
  - A `timeout` raises, so the queue retries it (`max_attempts` 2). When the job goes dead, the row ends `failed` with `timeout`, set by the handler on its final attempt.
  - Unexpected handler errors (for example the database) raise and are retried by the queue.
- **Read model:**
  - `Source` gains `parse: {status, error_code} | null` for its latest version.
  - The internal query `extracted_text(uow, source_id, version) -> str | None` is exposed in intake's `application` package for Story 2.5.
- **Retry API:** `POST /opportunities/{id}/sources/{source_id}/parse` (`intake.source.add` action) re-enqueues a `failed` latest version and sets it back to `queued`. Returns 409 if it isn't `failed`, and 404 or 403 like Part A.
- **Web:**
  - **Sources list:** a Status column with pills for Queued, Parsing (running dot), Parsed, and Parse failed (red, with the reason sentence).
  - **Reason sentences:** "The file couldn't be read", "No text found — scanned PDF?", "Parsing took too long", "Too much text to process" and "Outlook .msg files aren't supported yet — paste the text instead".
  - **Failed actions:** a failed row shows **Retry** and **Paste text instead**. The latter opens the Part B paste area and focuses it. Both are hidden without `can_add_sources`.
  - **Polling:** while any row is Queued or Parsing, the tab polls the list every 2 s.
- **Decided (2026-10-04):** only permissively licensed parsers for now: `pypdf` instead of `pymupdf` (AGPL-3.0). `.msg` parsing (`extract-msg` is GPL-3.0) is deferred as `[post-demo]`.
- **Privacy:** logs, trace and `last_error` carry ids, codes and sizes only, never text or filenames.

**Never:**
- No docling: it's tracked `[post-demo]`.
- No OCR. No source viewer or download (Story 2.3). No SSE.
- No parsing in the `api` process.
- No extraction trigger here: Story 2.5 Part A hooks into `parsed`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Enqueue | Any upload or paste | Version row + parse row `queued` + one job, in one transaction | N/A |
| Each kind | Sample `.txt` `.eml` `.vtt` `.pdf` `.docx` fixtures | `parsed`; text matches the expected fixture output; blob stored | N/A |
| VTT voices | `<v Ana>Hello` cues | `Ana: Hello` lines, no timings | N/A |
| CRLF / NFD | `a\r\nb` plus a decomposed `é` | Stored `a\nb` with an NFC `é`; `char_count` in code points | N/A |
| .msg | Any `.msg` | `failed`, `not_supported`, with Paste text instead | Job succeeds |
| Corrupt | `.pdf` with a valid header and broken body | `failed`, `unreadable`, no retry | Job succeeds |
| Scanned | PDF with no text layer | `failed`, `no_text` | Job succeeds |
| Hang | Parser exceeds the timeout (test with a tiny timeout and a slow fixture or stub) | Child killed, retried, then `failed`, `timeout` | Job dead |
| Isolation | 3 Sources, the middle one corrupt | The other two are `parsed` | N/A |
| Retry API | `POST …/parse` on a failed version | 202 or 201; row `queued`; new job | 409 if not failed |
| Who | HoD reader calls Retry | 403 | N/A |
| Privacy | Any failure | No source text in logs, trace or `last_error` | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/jobs/` (Story 2.2 Part A) -- `register(JobType(...))`, `enqueue(uow, payload)`, `JobContext.engine` plus `unit_of_work`. Add `app.modules.intake.application.jobs` to `_JOB_MODULES` in `backend/app/main_worker.py`.
- `backend/app/modules/intake/application/sources.py` -- `_record` (from Part B of Story 2.1) is the single place that writes a version. Enqueue and insert the parse row there.
- `backend/app/modules/intake/adapters/` -- `models.py` (add `SourceParseRow`), `repository.py` (parse row reads and writes; join the latest parse in `_latest_query`), and a new `parse_cli.py` plus `parsers/` (one module per format, pure functions `bytes -> str` raising `ParseError(code)`).
- `backend/app/platform/storage.py` -- `BlobStore.path_for(sha)` gives the child its input; `put_stream` stores the text.
- `backend/app/platform/trace/catalogue.py` -- `IntakeSourceParsed`.
- migrations -- `intake_source_parses`, with grants, plus a backfill: existing versions get a `queued` row and a job, so Part A's uploads get parsed too.
- `web/src/components/opportunities/sources-list.tsx` and `source-upload.tsx` -- the status column, Retry, and "Paste text instead". Expose an `openPaste()` from the upload area via a ref or lifted state.
- Tests -- fixtures under `backend/tests/fixtures/sources/` (small, generated, no real customer data), parser unit tests, a job test against Postgres, an API test, and web component tests with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/adapters/{parse_cli.py,parsers/*}` and `pyproject.toml` -- parsers and the CLI, with the chosen libraries pinned
- [x] `backend/app/modules/intake/{application,adapters}/*`, migration, trace catalogue, `main_worker.py` -- parse row, job, enqueue, read model, retry route
- [x] `backend/tests/test_intake_parsers.py`, `test_intake_parse_job.py` and fixtures -- every matrix row
- [x] Web: `schema.d.ts` (from local uvicorn), the actions, `sources-list.tsx`, `source-upload.tsx` and their tests -- pills, polling, Retry, Paste text instead, axe

**Acceptance Criteria:**
- Given the worker running, when a collaborator uploads a transcript, an email and a PDF, then within seconds all three show Parsed, without a manual refresh.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- Child protocol: stdout is the UTF-8 text only; on success stderr carries `parser=<name>@<version>`, on failure only the error code (exit 3). The parent waits for the child in a thread (`subprocess.Popen` + `communicate(timeout=)`), because the worker runs the Windows selector loop, which has no asyncio subprocess support. A child killed by `RLIMIT_CPU` (SIGXCPU) counts as `timeout`; any other crash or unknown stderr is `unreadable`.
- Job: `intake.parse_source`, `interactive`, `max_attempts` 2, job timeout 720 s (`PSA_PARSE_TIMEOUT_S` is capped at 600 so the child limit always fires first). The migration backfill enqueues existing versions at `background` priority.
- Retry: 202 with the Source; also appends `intake.source.parse_retried` `{version, error_code}` (AD-3: every command traces). 409 code: `parse_not_failed`.
- Parser ids: `text@1`, `email@1`, `vtt@1`, `docx@1`, `pypdf@6.19.0`.
- Web polling uses a `loadSources` server action; poll results are merged with Sources this page added since the read began (`mergeSources`).

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH, VG | A final-attempt failure that isn't a timeout (DB, `put_stream`, spawn) leaves the row `parsing`. Retry then answers 409 and the UI polls forever | high | `parse_source` marks `failed` only for `ParseError` and a final-attempt timeout | patch |
| 2 | ECH | Anything on the child's stderr before `parser=` (pypdf warnings, `PYTHONWARNINGS`) turns a successful parse into a permanent `unreadable` | high | `parse_runner` reads the whole stderr; warnings are suppressed only after the parser imports | patch |
| 3 | ECH | A poll that started before a successful Retry lands afterwards and reverts the row to Parse failed, and polling stops | medium | No ordering guard in `SourcesSection`'s poll and mutation updates | patch |
| 4 | BH | `preexec_fn` in a threaded worker can deadlock the fork | medium | Python docs warning; the worker uses `to_thread`. Fix: the child sets its own rlimits at the start of `main()` | patch |
| 5 | ECH | The child inherits the worker's full environment (DB URL, Auth0 secrets) | medium | `Popen` without `env`; a parser exploit would get the secrets. Direct env allowlist | patch |
| 6 | BH | A SIGKILL from the CPU hard limit or OOM is reported as permanent `unreadable` | low | Only SIGXCPU maps to timeout; direct mapping of negative return codes | patch |
| 7 | BH, ECH | A missing or unreadable stored blob is recorded as permanent `unreadable`; `extracted_text` raises `FileNotFoundError` | low | Infrastructure fault treated as a bad file; direct existence check and retryable raise | patch |
| 8 | ECH | `.docx` text boxes appear twice (`mc:Choice` and `mc:Fallback`) | medium | Duplicated text feeds extraction offsets; direct skip of `mc:Fallback` | patch |
| 9 | BH | `.docx` XML has no guard against internal entity expansion | medium | Untrusted input; direct reject of `<!DOCTYPE`/`<!ENTITY` before parsing | patch |
| 10 | BH | HTML email bodies are unescaped twice | low | `convert_charrefs=True` plus `unescape()`; direct removal | patch |
| 11 | BH | Retry shows for `not_supported`, which re-parsing can't fix | low | Direct UI condition | patch |
| 12 | BH | Polling never backs off or stops, and runs while the tab is hidden | low | Direct: pause on `document.hidden`, stop after 15 minutes | patch |
| 13 | BH | `PERMANENT_CODES` is unused and can drift from the handler | low | Direct: use it in the handler | patch |
| 14 | BH | Every "Paste text instead" button has the same accessible name | low | Direct `aria-label` with the filename | patch |
| 15 | BH | `loadSources` doesn't check that the id is a UUID | low | Direct `UUID_RE` check | patch |
| 16 | VG | The migration backfill is never tested on existing rows; CI migrates an empty DB | medium | No test seeds at 0006 and then upgrades | patch (test) |
| 17 | VG | Cancelling `run_parse` must kill the child; untested | medium | Only the timeout branch is tested | patch (test) |
| 18 | VG | `mergeSources` keeping locally added Sources is untested | medium | No test with a local-only Source during a poll | patch (test) |
| 19 | BH, ECH | The worker is killed on the final attempt, so the runner marks the job dead without calling the handler and the row stays `parsing` | medium | Needs a dead-job hook or a stale-row sweep (new public surface) | defer |
| 20 | VG | Retry sentences for 403 and 404 aren't asserted | low | Copy only | reject |
| 21 | BH | Two runs can parse the same version at once | low | Writes are guarded by the `parsing` → `parsed` transition; at worst a wasted parse | reject |
| 22 | BH, VG | A blob written before a lost race is left unreferenced; downgrade doesn't release references | low | Orphans are acceptable in R1 (Part A precedent) | reject |
| 23 | BH | A malformed email header makes the whole email unreadable; attachments-only emails are `parsed` with headers only | low | Rare; "Paste text instead" covers it | reject |
| 24 | BH | `parsing.py` imports private helpers from `sources.py` | low | No named harm | reject |
| 25 | ECH | Backfilled jobs have identical `created_at`, so claim order is arbitrary | low | Backfill runs once | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
