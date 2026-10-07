---
title: 'Story 3.2: Register Knowledge Sources by upload'
type: 'feature'
created: '2026-10-07'
status: 'done'
baseline_commit: '8da210effbeade6bc7287ef651c9157bc7e2ab17'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agents have no internal documentation to cite, and nobody can see when product or integration docs go stale. Story 3.1 added the catalogue but there is no Knowledge Source registry.

**Approach:** Add Knowledge Sources in the `knowledge` module: tagged, owned, versioned uploads stored unchanged by SHA-256, parsed by a `knowledge.parse_source` job in the existing sandbox, with a derived stale flag, Mark reviewed, re-version/retag/retire, and a Knowledge → Sources tab with inspector.

## Boundaries & Constraints

**Always:** Mutations follow AD-3 (authorize → rules → `If-Match` → write → trace, edge commits). Header + immutable version rows, `row_version` on headers. Trace events `knowledge.source.*` with `opportunity_id = null`, ids only. Tags validated through `validate_catalogue_ref` (retired rejected). Stale is derived from `PSA_KNOWLEDGE_STALE_MONTHS` (default 12), never stored. Writes: platform administrator or Source owner (403 otherwise); any role reads. Shared upload validation lives in `app/platform`, not imported from `intake`.

**Decisions:** (1) Old versions download through a short-lived HMAC-signed token and route in `platform`, with a new config secret. (2) Status updates by polling, like the Opportunity Sources list; no SSE. (3) Owner is a platform user, defaulting to the uploader; an administrator may pick another user, found through identity's public API. (4) Add a UTF-8 text `.md` parser for Knowledge only.

**Never:** No chunking/embedding/Embedding+Ready statuses (3.3). No Checklists (3.4) or coverage (3.5). No change to intake behaviour, its parse child command, migration 0019, or `OWNER_GRANTS` semantics for Opportunities.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Register | Valid .pdf/.docx/.txt/.md + title, owner, product, ≥1 active Integration Type, version | Source + version row, blob stored by SHA-256, parse job queued, `knowledge.source.registered`; last-reviewed = today | N/A |
| Bad file | Over 50 MB, bad extension, or magic mismatch | Rejected with specific reason, nothing stored | 4xx problem+json with reason |
| Retired tag | Retired catalogue entry chosen | Rejected | 422 |
| Parse failure | Corrupt file | Pill **Parse failed** + reason + **Retry**; others unaffected | N/A |
| Stale | last-reviewed > 12 months | `stale: true`; **Mark reviewed** sets today, appends `knowledge.source.reviewed` | N/A |
| Non-owner non-admin | Write attempt | 403, actions hidden | 403 |
| Concurrent edit | Missing / stale `If-Match` | 428 / 412 | problem+json |

</frozen-after-approval>

## Code Map

- `backend/app/modules/knowledge/{adapters,application,api,domain}` -- 3.1 layout; add Source rows/repo/commands/routes. Mirror `CatalogueEntryRow`/`CatalogueEntryVersionRow`; export via `application/public.py` (`validate_catalogue_ref` reused).
- `backend/migrations/versions/20261006_0019_knowledge_catalogue.py` -- pattern and grants (header SELECT/INSERT/UPDATE, versions SELECT/INSERT). New `20261007_0020_knowledge_sources.py`, down_revision `0019_knowledge_catalogue`; `alembic check` must pass.
- `backend/app/platform/trace/catalogue.py` (knowledge section ~448) -- register `source.registered/reviewed/version_added/retagged/retired` payloads (ids only); `test_trace_catalogue.py`.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- add `KNOWLEDGE_SOURCE_*` actions (admin or owner); check how `authorize` resolves resource ownership before adding a grant.
- `backend/app/modules/intake/domain/sources.py` -- `EXTENSION_KINDS`, `content_matches`, `too_large_message`: extract generic helpers to new `app/platform/upload_validation.py`, intake imports it unchanged in behaviour.
- `backend/app/modules/intake/application/sources.py::add_file`, `app/platform/{storage,files,multipart}.py` -- streaming upload, `BlobStore.put_stream`, `files.add_reference`.
- `backend/app/modules/intake/application/jobs.py`, `adapters/{parse_runner,parse_cli}.py`, `adapters/parsers/` -- job and sandbox pattern; knowledge gets its own job `knowledge.parse_source` and own child entry reusing platform-level parsing; do not edit intake's `CHILD_MODULE`. Register in `_JOB_MODULES` in `app/main_worker.py`.
- `backend/app/platform/config.py` -- add `PSA_KNOWLEDGE_STALE_MONTHS`.
- `backend/pyproject.toml` (~189) -- knowledge contract forbids intake; run `uv run lint-imports`.
- `web/src/app/knowledge/page.tsx` (placeholder) -- Sources tab; copy from `components/opportunities/{source-upload,sources-list}.tsx`, `lib/{sources,upload-limits}.ts`, `components/admin/catalogue-inspector.tsx`; `npm run gen:api` and commit.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/upload_validation.py` -- shared extension/magic/size checks, `.md` text check -- avoids knowledge→intake import
- [x] `backend/migrations/versions/20261007_0020_knowledge_sources.py` + knowledge `adapters/models.py` -- sources, versions, tags, parse state
- [x] knowledge `domain/` + `application/` -- register, re-version, retag, retire, mark reviewed, list/get with derived stale, filters
- [x] knowledge `application/jobs.py`, parse child, `main_worker.py` -- `knowledge.parse_source`, retry, extracted-text artifact
- [x] knowledge `api/routes.py`, identity actions/policy, trace payloads, config -- endpoints, authz, events
- [x] `web/src/app/knowledge/**`, `web/src/components/knowledge/**`, `web/src/lib/api` -- Sources tab, upload form, filters, inspector, stale/retired/status labels, empty state
- [x] backend tests (mirror `test_knowledge_catalogue.py`, `test_intake_sources.py`, `test_intake_parse_job.py`) and web tests -- cover the I/O matrix

**Acceptance Criteria:**
- Given a registered Source, when a new version is uploaded, then earlier versions remain readable and the change is traced.
- Given the Sources list, when no Sources exist, then it shows "No Knowledge Sources yet. Upload product or integration documentation to start."
- Given a stale or retired Source, then it shows a "Stale" or "Retired" label with an icon, never colour alone.

## Implementation Notes

## Spec Change Log

## Review Triage Log


| Finding | Verdict | Evidence / route |
|---|---|---|
| Download signing key default accepted in prod | medium | No validator existed. Patched: prod refuses the default key; test added. |
| Non-ASCII download token gives 500 | medium | compare_digest on non-ASCII str raised. Patched, test added (403). |
| Retry/final-attempt branches of parse job untested | medium | Gap finding, pre-verified. Patched: two job-level tests. |
| Expired link and vanished blob on download route untested | medium | Patched: route-level test (403 / 404). |
| Docstring says missing blob is never unreadable | low | Docstring contradicted _final_code. Patched the docstring. |
| Registering open to reviewer roles | high | Deviated from spec and AC (admin or owner only). Fixed before review (policy, web, tests). |
| Orphan blobs when a later write fails (register, add_version, parse text) | low | Real, but intake upload has the same store-before-record pattern. Deferred. |
| Metadata in query string reaches logs | false | Access log is disabled (--no-access-log, uvicorn.access disabled); middleware logs paths only. |
| Retired tag persists through retag | false | Intended by spec/test (existing retired tags stay, cannot be added). |
| Token bearer, replayable, not user-bound; no per-fetch audit | false | The chosen design (decision 1); TTL 300 s. |
| retry_parse race with add_version | maybe-false | Needs a concurrent test to settle; deferred as unverified medium. |
| Windows has no RLIMIT memory/CPU; killed child is permanent unreadable | low | Platform limit shared with intake; deferred. |
| Unbounded integration_type_ids / list_sources / read_text size, N+1 tag checks | low | No reachable harm shown; rejected. |
| _require_role bypasses authorize for reads | low | Reads are open to any role by design; rejected. |
| Parse failure not traced | low | Spec lists no such event; rejected. |
| Missing FKs / hex CHECKs, hardcoded 720 s timeout, stale-filter arg mismatch, async is_file, rowVersion/tagIds form edges, migration CHECK duplication | low | Cosmetic or unreachable through the API; rejected. |
| Download proxy route.ts untested | low | Deferred. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest` -- all pass
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- all pass
