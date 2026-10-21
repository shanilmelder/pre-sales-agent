---
title: 'Story 3.3: Chunk, embed and search Knowledge with citable passages'
type: 'feature'
created: '2026-10-21'
status: 'done'
baseline_commit: '135fc762a6031d864d9a125a7bfe5dc48883d313'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Knowledge Sources are parsed (3.2) but nothing can search them or cite a passage, so agents have no internal Evidence base.

**Approach:** After parse, a `knowledge.embed_source` job splits the extracted text into heading/paragraph chunks with code-point offsets, embeds them through `platform.model_gateway` (`bge-m3`, `background`), stores them in pgvector `knowledge_chunks`, and moves the Source to Ready. `knowledge.public.search` returns citable top-k chunks; a `knowledge` Evidence resolver validates `knowledge_chunk` refs. `make eval-retrieval` scores hit rate at k and citation validity. Parts B (Evidence chip UI) and C (re-embed) are deferred.

## Boundaries & Constraints

**Always:** Embeddings only via the gateway; each call writes `platform_model_calls`. Chunk text and query text never logged or traced (ids/counts only). Every vector query uses `embedding::vector(1024)` and `WHERE embedding_model = 'bge-m3'`, matching the partial HNSW index. Search reads authorize via `identity.authorize`. Chunk/size/overlap from `platform.config`. Chunks are insert-only per Source version; earlier versions' chunks stay so old citations still resolve. Search returns only Ready, non-retired, current-version chunks.

**Decisions:** (1) Search is exposed as `knowledge.public.search` plus an authorized `GET /api/knowledge/search` (any role); no search UI. (2) A version parsed but never embedded (pre-3.3 Sources) shows an **Embed** action that calls the same endpoint as Retry; no migration backfill.

**Never:** No re-embed job, Admin trigger or banner (C). No Evidence chip / inspector highlight UI (B). No change to intake parsing or the shared `ParseStatus` enum. No second search store.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Embed | Version parsed | Embed job queued in parse UoW; status Embedding → Ready; chunks with offsets slicing the extracted text exactly | N/A |
| Model down | Gateway fails every attempt | "Embedding failed" + reason + **Retry**; no partial chunks; other Sources unaffected | Retry re-queues; 409 if not failed |
| Empty/whitespace sections | Headings without body | No empty chunks | N/A |
| Search | query + optional product / Integration Type / product version, k | Top-k `{text, source title, version, stale, evidence:{kind:knowledge_chunk,id,version,span}}` | 422 on empty query or k out of range |
| Retired / superseded | Source retired or newer version | Excluded from search | N/A |
| Resolve ok | Ref to existing chunk, span inside offsets | Accepted | N/A |
| Resolve bad | Unknown id, wrong version, span outside | Rejected | Error naming the ref |

</frozen-after-approval>

## Code Map

- `backend/app/modules/knowledge/adapters/models.py` -- `SourceParseRow` (:127) holds parse status; add `SourceEmbedRow` (`knowledge_source_embeds`, PK `(source_id, version)`, status `queued|embedding|ready|failed`, error_code, chunk_count, model) and `ChunkRow` (`knowledge_chunks`: id UUIDv7, source_id, version, ordinal, text, start/end code-point offsets, product, product_version, integration type ids, embedding_model, embedding_dims, untyped `vector` column).
- `backend/migrations/versions/` -- latest `20261020_0033_conflict_agent.py` (rev `0033_conflict_agent`); add `20261021_0035_knowledge_chunks.py` (rev `0035_knowledge_chunks`, down_revision `0033_conflict_agent` for now: open PR #58 owns `0034_requirement_lifecycle`, so rechain to it once #58 merges) with grants as in `20261013_0025_knowledge_sources.py:120` (chunks S/I, embeds S/I/U) and the partial HNSW expression index. Vector extension exists (baseline :19, image `pgvector/pgvector:0.8.6-pg18`). Add `pgvector` to `backend/pyproject.toml`.
- `backend/app/modules/knowledge/application/jobs.py` -- `parse_source` (:102) / `_parse` (:125): enqueue embed inside the parsed UoW (pattern: `intake/application/jobs.py:236`). Register `knowledge.embed_source` (`priority="background"`, retries). Final-attempt handling as in `parse_source`. Read text like `sources.read_text` (:356) without its role check.
- `backend/app/modules/knowledge/application/sources.py::retry_parse` (:769) + `api/source_routes.py:394` -- mirror for `retry_embed` (`POST /{source_id}/embed`, allowed when embed state is `failed` or absent on a parsed latest version); add `GET /api/knowledge/search`; new identity action `KNOWLEDGE_SOURCE_RETRY_EMBED` (`identity/actions.py:39`, owner grants `policy.py:131`); search action readable by any role.
- `backend/app/modules/knowledge/application/public.py` -- export `search`, `resolve_evidence`; add `embed` state to `KnowledgeSource` API model.
- `backend/app/platform/model_gateway/{port.py,gateway.py,adapter.py,ollama.py,openai_compat.py,profiles.py}` -- add `embed(EmbedRequest) -> list[list[float]]` to the port; `ModelGateway` reuses the semaphore and `_record` (`gateway.py:161,253`); Ollama `/api/embed`, OpenAI-compat `/embeddings`; `bge-m3` profile (1024 dims) selected by new `model_profile_embed` setting.
- `backend/app/platform/config.py` -- `knowledge_chunk_chars`, `knowledge_chunk_overlap_chars`, `model_profile_embed` (pattern `:61`, validator `:235`).
- `backend/app/agents/contract.py:30,45` -- `Span`, `EvidenceRef`; add a small kind → resolver registry here or in `app/platform/evidence.py`; knowledge registers `knowledge_chunk`. No accept command emits this kind yet; registry exposes `resolve_all(uow, refs)` for future `accept_*`.
- `backend/app/platform/trace/catalogue.py` (:809) -- `knowledge.source.embedded`, `.embed_retried` (ids/counts only).
- `web/src/components/knowledge/{sources-table,source-inspector}.tsx`, `web/src/lib/knowledge-sources.ts` -- show Embedding / Ready / Embedding failed + Retry next to parse state, and **Embed** for a parsed version with no embed state (Retry button pattern `source-inspector.tsx:487`); polling continues while embedding. `npm run gen:api`.
- `backend/app/evals/__main__.py`, root `Makefile` -- add `retrieval` subcommand + `eval-retrieval`; fixtures in `evals/knowledge/`.
- Tests: stub gateway via `provider.install(fake)` (`tests/test_assessments_specialists.py:102`), `httpx.MockTransport` for adapters (`tests/test_model_gateway.py:236`).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/model_gateway/**`, `config.py`, `pyproject.toml` -- embed port, adapters, `bge-m3` profile, settings -- gateway-only embeddings
- [x] `backend/migrations/versions/20261021_0035_knowledge_chunks.py`, knowledge `adapters/models.py` + repo -- tables, grants, HNSW index
- [x] knowledge `domain/chunking.py` -- pure heading/paragraph splitter with overlap, code-point offsets
- [x] knowledge `application/jobs.py`, `sources.py`, `api/source_routes.py`, identity, trace -- embed job, statuses, retry, events
- [x] knowledge `application/search.py`, `evidence.py`, `public.py` + evidence registry -- search, resolver
- [x] `web/src/{lib,components}/knowledge/**`, `web/src/lib/api` -- Embedding/Ready/Embedding failed + Retry
- [x] `evals/knowledge/**`, `backend/app/evals/retrieval.py`, `Makefile` -- fixtures + report
- [x] backend tests (chunker property: `text[start:end] == chunk.text`; job; search filters; resolver; index exists) and web tests -- cover the matrix

**Acceptance Criteria:**
- Given migration 0035, then `pg_indexes` shows the partial HNSW index on `((embedding::vector(1024))) WHERE embedding_model = 'bge-m3'`, and search SQL uses the same cast and filter.
- Given an embedded Source, then `platform_model_calls` has rows with profile `bge-m3`, priority `background`, and no log record contains chunk or query text.
- Given `make eval-retrieval`, then it prints hit rate at k and citation validity, and every returned reference resolves.

## Implementation Notes

- Search embeds its query in the `api` process: `app.state.model_gateway` (embeddings only). The import-linter contract "api never calls a model" now reads "never calls a chat model" with one `ignore_imports` exception for `app.platform.model_gateway.gateway`. Query embeds use `interactive` priority so a searcher isn't queued behind an embed job; chunk embeds use `background` (AC).
- Search filters use the Source's current product, tags and the latest version's product version (so a retag is reflected at once); the copies on each chunk are kept but not filtered on.
- Any-role grant `ANY_ROLE_GRANTS` added to identity policy for `knowledge.chunk.search`; `knowledge.source.retry_embed` added to owner grants, Auth0 seed and web test permissions.
- Defaults: chunk 1500 chars, overlap 200; k default 8, max 50; query max 2000 chars; embed job 3 attempts, 3600 s timeout; batch size 16.
- Gateway `_record` now swallows its own write failure for both chat and embed calls (behaviour unchanged for chat).
- `make eval-retrieval` ran end to end with a stub embedder; not run against live `bge-m3` (Ollama not running here).
- Test DBs: `psa_test` now at 0035; `psa_eval_test` reset by the eval test.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| Embed job timeout (CancelledError not caught) or final-attempt lease loss leaves row `embedding` forever; `retry_embed` 409s | medium | Runner cancels the handler under `asyncio.timeout` and marks lease-lost final attempts dead without calling it (`jobs/runner.py:109,135`). Patch: `retry_embed` also re-queues a `queued`/`embedding` row older than the embed job's timeout. |
| Blank `product`/`product_version` filter matches nothing | low | `"".strip()` still adds the predicate. Patch: blank → no filter. |
| Search route: `k` bounds and 503 missing from OpenAPI | low | `_responses(403, 422)` only; `k` has no ge/le. Patch. |
| `gateway.py` docstring says the api never calls a model | low | Now false. Patch the docstring. |
| `#` lines inside fenced code blocks treated as headings | low | `_HEADING` matches inside ``` fences; common in install guides. Patch: skip fenced lines. |
| `embed_not_failed` notice wrong when version not parsed | low | Message only covers queued/running/done. Patch the wording. |
| Gateway embed batching never exercised (>16 texts) | medium | Verification-gap, pre-verified. Patch: batching test. |
| Embed error-code mapping untested except `model_unavailable` | medium | Verification-gap, pre-verified. Patch: parametrized test. |
| Owner grant for `retry_embed` untested | low | Verification-gap, pre-verified. Patch: owner API case. |
| SourcesTab polling while embedding untested | low | Verification-gap, pre-verified; no SourcesTab test existed. Defer. |
| Migration 0035 forms a second Alembic head with PR #58 | low | Known and documented; rechain at merge time. Defer (merge task). |
| Chunk product/tag copies unused and not updated on retag | low | Stored as the AC requires; search reads current tags by design (Implementation Notes). Rejected. |
| Source unsearchable while a new version parses/embeds or after it fails | false | Frozen intent: search returns current-version chunks only. |
| No re-embed path after profile change | false | Part C deferred by intent (Never: no re-embed job). |
| No bulk backfill for pre-3.3 Sources | false | Decision (2): Embed action, no backfill. |
| api gateway adds its own model slots; search uses chat timeout | low | Extra requests queue in Ollama (latency only). Rejected. |
| AD-8 import contract narrowed by `ignore_imports` | low | Deliberate; surfaced to the user for confirmation. Rejected as a code change. |
| Embed holds one slot for a whole Source; restarts from zero | low | Few batches per Source; background priority. Rejected. |
| `hnsw.iterative_scan` fails on pgvector < 0.8 | false | Image pinned to pgvector 0.8.6 (`compose.yaml:18`). |
| Zero vector → NaN distance | low | bge-m3 returns normalized vectors. Rejected. |
| Non-gateway exception / missing adapter → 500 with no call row | low | Adapters map transport errors; `bge-m3` provider is always configured. Rejected. |
| `KnowledgeSpan` allows end <= start; ids typed `str` | low | Built only from DB rows with an offsets CHECK. Rejected. |
| `knowledge.resolve_evidence` duplicates `platform.evidence.resolve_all` | low | Thin wrapper for the public API named in the spec. Rejected. |
| Retrieval eval weak (small corpus, no filter cases, no baseline) | low | Meets the AC (hit rate at k, citation validity). Rejected. |
| Eval exit codes; crash on resolver error; `k: true` accepted | low | Dev tooling, unlikely. Rejected. |
| No test for api lifespan closing the gateway, 503 call row, `_cut` newline at 0 | low | Unlikely to regress unnoticed. Rejected. |

## Design Notes

Status shown to users: parse state while not `parsed`; then embed state (Embedding, Ready, Embedding failed). Search: `ORDER BY embedding::vector(1024) <=> :q` filtered to latest version, Source `active`, embed `ready`, `embedding_model = active`. Stale flag computed as in 3.2.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest` -- all pass. Use `PSA_DATABASE_URL=postgresql+psycopg://psa_app:<pw from .env>@127.0.0.1:5432/psa_test` (127.0.0.1, not localhost; NEVER the dev `psa` DB — migration tests drop tables); `alembic upgrade head` on `psa_test` first via `PSA_MIGRATIONS_DATABASE_URL` (owner role)
- `npm run gen:api` -- regenerate against a fresh local uvicorn or a dumped `app.openapi()`, not the Docker `api` (stale image)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- all pass
- `make eval-retrieval` -- report printed (needs `ollama pull bge-m3`)
