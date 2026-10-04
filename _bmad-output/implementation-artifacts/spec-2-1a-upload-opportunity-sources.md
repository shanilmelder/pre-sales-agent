---
title: 'Story 2.1 (Part A): Upload Opportunity Sources'
type: 'feature'
created: '2026-10-04'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '89e6480f012e064ca954ef19827d0a1d52a6932b'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Customer emails, notes and transcripts have nowhere to live in the platform, so parsing and extraction have no input. The Sources tab says "Not available yet."

**Approach:**
- Add a new `intake` module (Sources) and a `platform.storage` layer that stores files unchanged, content-addressed by SHA-256 and reference-counted.
- Add a file upload API with a size limit, an extension allowlist and magic-byte checks. Each added Source appends an `intake.source.added` trace event.
- Make the Sources tab real: drag-and-drop or choose files, plus the list of Sources.

## Boundaries & Constraints

**Always:**
- **Who:**
  - The Opportunity's owner and collaborators (any role, so sales representatives are included) may add Sources through the new action `intake.source.add`. No role grants it on its own.
  - Other readers (HoD, admin) get 403. Non-readers get the Opportunity's 404.
  - Anyone who can read the Opportunity can list its Sources.
- **Allowlist:**
  - Kinds by extension, matched case-insensitively: `.eml` and `.msg` are `email`, `.txt` is `note`, `.vtt` is `transcript`, `.docx` and `.pdf` are `document`.
  - Magic bytes must match the extension:
    - pdf starts with `%PDF-`;
    - docx is a ZIP (`PK\x03\x04`) containing a `word/` entry;
    - msg is OLE (`D0 CF 11 E0 A1 B1 1A E1`);
    - vtt starts with `WEBVTT` (an optional UTF-8 BOM is allowed);
    - txt and eml are valid UTF-8 with no NUL bytes.
- **Size:**
  - 1 byte to 50 MB (`PSA_UPLOAD_MAX_BYTES`), enforced by the API only. No proxy is involved.
  - The API rejects early on `Content-Length`, then counts while streaming, so it never holds the whole body in memory.
- **Rejections:**
  - A rejected upload stores nothing: no blob, no row, no trace, and no temp file left behind.
  - The response is 422 with `code` `file_too_large`, `file_type_not_allowed`, `file_content_mismatch` or `file_empty`.
  - The `detail` is the exact UI sentence: "Rejected: .exe files aren't allowed", "Rejected: larger than 50 MB", "Rejected: the content doesn't match .pdf" or "Rejected: the file is empty".
- **Storage (AD-18):**
  - `platform.storage` streams to a temp file in `PSA_STORAGE_DIR` while hashing, then atomically renames it to `sha256/ab/cd/<sha256>`. A blob that already exists is never rewritten.
  - `platform_files(sha256 pk, size_bytes, ref_count, created_at)` is upserted in the request's UoW, and `ref_count` goes up by one per Source version that references the blob.
  - The blob is written before the DB writes. A blob orphaned by a failed transaction is acceptable in R1.
- **Model:**
  - `intake_sources(id, opportunity_id, kind, created_by, created_at, row_version)`.
  - `intake_source_versions(source_id, version, file_sha256, filename, size_bytes, uploaded_by, uploaded_at)`.
  - The filename is stored as given, trimmed and at most 255 characters, with no path components.
- **Versioning (decided):** identical bytes (same SHA-256) uploaded again to the same Opportunity become the next version of that Source. Different bytes are always a new Source, even with the same filename.
- **Trace:** `intake.source.added` with payload `{version, kind, size_bytes}` and `subject_id` set to the Source, appended once per added version. Ids and sizes only.
- **Opportunity version:** adding a Source never bumps the Opportunity's `row_version`.
- **Web:**
  - The Sources tab has a drop zone with a "Choose files" button, and the list of Sources newest first: kind, filename, version, uploader and time.
  - Several files go up one at a time. Each gets a row that shows Uploading, then Added or the API's "Rejected: …" sentence.
  - The read model gains `can_add_sources`. Without it the drop zone is hidden and the list still shows.
  - A 50 MB file must pass end to end through `proxy.ts` and the Next server. The Next body limits are raised to make that work, and a test proves it.

**Never:** No pasted text or rate limit (Part B). No parsing, status pills, viewer, download, SSE or job queue (Stories 2.2 and 2.3). No deletion. No Caddy or any proxy config. No Requirement, Assessment or Estimate actions. No ClamAV. No new third-party file-type library.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Upload | Collaborator uploads `call.vtt` | 201 with Source (kind transcript, v1), blob stored, `ref_count` 1, one trace event | N/A |
| Sales rep | Sales representative collaborator uploads `.pdf` | 201 | N/A |
| Reader only | HoD who isn't a collaborator uploads | 403, nothing stored | N/A |
| Non-reader | Unknown or unreadable Opportunity | 404, nothing stored | N/A |
| Bad type | `setup.exe` | 422 `file_type_not_allowed`, "Rejected: .exe files aren't allowed" | Nothing stored |
| Spoofed | `.pdf` that is really a PNG | 422 `file_content_mismatch` | Nothing stored |
| Too large | 50 MB + 1 byte | 422 `file_too_large`, "Rejected: larger than 50 MB" | No temp file left |
| Empty | 0-byte `.txt` | 422 `file_empty` | Nothing stored |
| Same bytes | Identical file uploaded again (any filename) | 201, same Source now v2, same blob, `ref_count` 2, one more trace event | N/A |
| Same name | `notes.txt` with different content | A new Source v1 and a new blob | N/A |
| List | Any reader | Sources newest first, with latest version and version count | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/` -- add `storage.py`: `put_stream(chunks, max_bytes) -> StoredBlob(sha256, size)` and `path_for(sha256)`, temp then rename, no DB. Add `files.py` with the `platform_files` row and `add_reference(uow, sha256, size)`. `config.py` gains `storage_dir` and `upload_max_bytes` (`PSA_` prefix).
- `backend/app/platform/errors.py:134` -- `UnprocessableError`; add subclasses with the four codes.
- `backend/app/modules/opportunities/` -- the reference layout (api/application/domain/adapters, `public.py`, routes with `_responses`). Mirror it as `backend/app/modules/intake/`, and register its router in `backend/app/main_api.py` and the module in `app/modules/__init__.py`.
- `backend/app/modules/opportunities/application/public.py` -- intake reaches Opportunity access only through this file. Add a query returning the `Resource` (owner and members) for an id, raising the same 404. Add `can_add_sources` to `Opportunity` (models.py L122) via `identity.can`.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- add `SOURCE_ADD = "intake.source.add"` to `POLICY` with no roles, and to both `OWNER_GRANTS` and `MEMBER_GRANTS`. Listing uses `OPPORTUNITY_READ`.
- `backend/app/platform/trace/catalogue.py` -- add `IntakeSourceAdded`.
- `backend/migrations/versions/20261004_0004_opportunities.py` -- the pattern for a revision with `psa_app` grants. The new revision creates `platform_files`, `intake_sources` and `intake_source_versions`.
- `backend/pyproject.toml` -- add `python-multipart`, pinned, and update `uv.lock`.
- `backend/tests/test_opportunities.py` -- helpers for seeding, tokens and roles. Tests use a temp `PSA_STORAGE_DIR`.
- `compose.yaml` -- a named volume `files` mounted on `api` at `PSA_STORAGE_DIR`. Document it in `.env.example`.
- `web/src/app/opportunities/[id]/[tab]/page.tsx` -- `sources` falls through to the placeholder today. Route it to a new `[id]/sources.tsx`, gated like `overview.tsx`.
- `web/src/app/opportunities/actions.ts` -- the server-action and problem-mapping pattern. Upload `FormData` through a server action or a Route Handler. `next.config.ts` needs the Server Action body limit and the proxy body limit raised above 50 MB; check the exact keys in Next 16.3's own docs under `node_modules/next/dist/docs`.
- `web/src/components/opportunities/collaborators.tsx`, `web/src/components/shell/live-region.tsx` -- patterns for pending state, announcements and inline errors.

## Tasks & Acceptance

**Execution:**
- [x] Backend platform: `platform/{storage.py,files.py,config.py,errors.py}`, `pyproject.toml` and `uv.lock` -- blob store, refcounts, settings, error types
- [x] Backend intake: `modules/intake/**`, `modules/opportunities/application/{public.py,models.py,opportunities.py}`, `identity/{actions.py,domain/policy.py}`, `trace/catalogue.py`, `main_api.py`, the migration -- the type checks in `intake/domain`, the `add_file` command, the `list` query, `POST /api/v1/opportunities/{id}/sources` (multipart `file`), `GET …/sources`, and `can_add_sources`
- [x] `backend/tests/test_intake_sources.py`, `test_storage.py`, `test_intake_filetypes.py`, `test_authorize.py` -- every matrix row as `psa_app`, plus magic-byte domain tests
- [x] `compose.yaml`, `.env.example` -- the files volume and settings
- [x] Web: `schema.d.ts`, `next.config.ts`, `app/opportunities/[id]/{[tab]/page.tsx,sources.tsx}`, `app/opportunities/actions.ts`, `components/opportunities/{source-upload.tsx,sources-list.tsx}` and their tests -- drop and choose, per-file rows, rejection copy, the list, hidden controls, axe

**Acceptance Criteria:**
- Given a collaborator on the Sources tab, when they drop three files including one `.exe`, then two Sources appear in the list and the `.exe` row says "Rejected: .exe files aren't allowed".
- Given CI, when it runs, then backend and web checks (including the generated-client drift check) pass.

## Implementation Notes

- The upload body is parsed as a stream with python-multipart's push parser (`app/platform/multipart.py`), not FastAPI's `UploadFile` (which spools the whole body before the handler runs). The type is rejected from the part headers before any file bytes are read; the size is counted while streaming; the whole body is capped at the limit plus 64 KiB of framing. The OpenAPI request body is declared through `openapi_extra`.
- `platform.storage.BlobStore(root).put_stream(chunks, max_bytes, check=...)`: `check` inspects the finished temp file (empty, magic bytes, docx `word/` entry, full UTF-8 scan) before it is hard-linked into place, so a rejected file never reaches `sha256/`.
- Same-bytes uploads are serialised per (Opportunity, SHA-256) with `pg_advisory_xact_lock`; a new version bumps the Source's `row_version`.
- The api image creates `/var/lib/psa/files` owned by the non-root `app` user so the new named volume is writable.
- The web rejects, without sending, only files past the web server's own body limit (50 MB + 1 MB), showing the API's sentence; anything up to that goes to the API, which enforces 50 MB.
- The 50 MB pass-through is proven by `web/src/lib/upload-limits.test.ts` (config values vs. a real 50 MB multipart body) and the `addSource` action test; there is no live test through a running `next start`.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | VG, BH | Concurrent identical uploads untested; the `lock_content` advisory lock is unprotected | low | Every test is sequential; removing the lock stays green | patch (test) |
| 2 | VG | Filename rejections and body-cap errors untested at the API | low | Only unit tests on `clean_filename` and `MultipartFile`; dropping an `except` would give 500s | patch (test) |
| 3 | ECH | `Content-Length` with a non-ASCII digit (`²`) passes `isdigit()`, then `int()` gives a 500 | low | Latin-1 headers decode 0xB2 to `²`; direct fix is `isascii()` | patch |
| 4 | ECH | Mixed-case `Multipart/Form-Data` rejected | low | Media type compared case-sensitively; direct `.lower()` | patch |
| 5 | ECH | A client disconnect mid-upload escapes as a 500 | low | Starlette `ClientDisconnect` isn't mapped; direct catch as `MultipartError` | patch |
| 6 | ECH | Bidi overrides and C1 controls in filenames can visually spoof the extension | low | `clean_filename` rejects C0 only; direct `unicodedata` Cc/Cf check | patch |
| 7 | ECH | PDFs with leading bytes before `%PDF-` are rejected | low | The PDF spec tolerates a header within the first 1024 bytes; direct change to the magic check | patch |
| 8 | ECH | One thrown `upload()` skips every later queued file, leaving rows stuck on "Uploading" | low | `queue.current.then(...)` has no `.catch`; direct fix | patch |
| 9 | BH | An upload that became v2 of another Source just says "Added", and the list row's name changes | low | The response has `version`; direct copy change to "Added as version N" | patch |
| 10 | BH | Early API rejections (type, 403/404, Content-Length) of a large body may reach Next as ECONNRESET, so the row says "The upload failed" | maybe-false | `TestClient` and the mocked fetch never close mid-body. Would be medium if true; needs a real uvicorn + undici test with a multi-MB `.exe` | defer |
| 11 | BH, ECH | Same bytes under another extension keep the first Source's kind | low | Follows from the frozen "same bytes, any filename" decision; rare | reject |
| 12 | BH | Retried uploads add another version | low | Needs a timeout after commit; no idempotency key in scope | reject |
| 13 | BH | Next buffers each upload in memory, and the raised proxy limit applies to every route | low | Server Action path allowed by the spec; a small team means a few 50 MB buffers at most | reject |
| 14 | ECH | A DB connection stays open while a slow upload streams | low | The spec puts the upload in the request UoW; a few concurrent uploads fit the pool | reject |
| 15 | BH, ECH | `.eml`/`.txt` must be UTF-8: 8-bit Latin-1 mails and UTF-16 text are rejected | low | Required by the frozen allowlist; modern exports are UTF-8 or MIME-encoded | reject |
| 16 | BH | Blobs aren't fsynced before commit | low | Crash-only window; R1 accepts orphan or partial risk | reject |
| 17 | BH | `.part` temp files from killed processes are never swept | low | Only on SIGKILL or OOM mid-upload | reject |
| 18 | BH | No DB CHECK constraints or FK from versions to `platform_files` | low | Writes only go through validated commands | reject |
| 19 | BH, ECH | The web hard-codes 50 MB, separately from `PSA_UPLOAD_MAX_BYTES` | low | The limit isn't changed anywhere; a future config change | reject |
| 20 | BH | Default `storage_dir` is relative to the working directory | low | The compose sets an absolute path; host runs use `backend/` | reject |
| 21 | BH | The Sources list isn't paginated | low | Tens of Sources per Opportunity in R1 | reject |
| 22 | BH, ECH | Client: queue continues after unmount, no beforeunload, no progress, list `initial` not re-synced | low | Rare paths, and the tab remounts on return | reject |
| 23 | BH | `filename*=` (RFC 5987) ignored | false | Browsers always send `filename=` in multipart/form-data | reject |
| 24 | BH | Tests import private helpers from `test_opportunities` | low | No named harm | reject |
| 25 | ECH | `upload_max_bytes` below 1 MB prints "0.0 MB" | low | Not configured anywhere | reject |
| 26 | ECH | A file at the limit plus more than 64 KB of other fields is rejected | false | The web sends only the `file` part | reject |
| 27 | ECH | Cancellation races `handle.write` in a thread | low | Cancellation only on disconnect; at worst a stray temp file | reject |
| 28 | ECH | `os.link` fallback hides ENOSPC/EACCES | false | `os.replace` then raises the same error, which propagates | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && PSA_MIGRATIONS_DATABASE_URL=<owner> uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass. Regenerate `schema.d.ts` from a local uvicorn running the new backend, not the Docker `api`.

**Manual checks (human):**
- Rebuild the stack, then upload one of each allowed type, a 45 MB PDF, an `.exe` and a renamed PNG, and the same file twice.
