# Epic 3 Context: Knowledge Base and catalogue

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the platform its own internal evidence base. Admins and domain experts load product and integration documentation, write versioned Checklists, and maintain the Integration Type and Work Package catalogue, and administrators see where coverage is weak. There is no archive of past proposals, so at launch the Knowledge Base is the main source of citable evidence, and Gap detection (Epic 4) and the agents (Epic 5) depend on it.

## Stories

- Story 3.1: Integration Type and Work Package catalogue
- Story 3.2: Register Knowledge Sources by upload
- Story 3.3: Chunk, embed and search Knowledge with citable passages
- Story 3.4: Author and version Checklists
- Story 3.5: Knowledge coverage view

## Requirements & Constraints

- Knowledge Sources (`.pdf`, `.docx`, `.txt`, `.md`) have an owner, product, Integration Type tags, product version and a last-reviewed date. A Source not reviewed in 12 months (`PSA_KNOWLEDGE_STALE_MONTHS`, default 12) is flagged stale. The flag is derived, not stored, and is cleared by "Mark reviewed".
- Upload limits and the extension allowlist are shared with Opportunity Sources (Epic 2). Files are stored unchanged by SHA-256, and an oversized file, disallowed extension or magic-byte mismatch is rejected with a specific reason.
- Checklists are authored by engineering, PM or security reviewers or platform administrators. Other roles read only. Items are questions or risks and can be marked mandatory. A mandatory item on a `security` Checklist is a mandatory security control that later epics treat as policy that can never be overridden. Mandatory items always produce a Gap when unanswered (Epic 4).
- The catalogue classifies Checklists, Assessment lines, Estimate lines and Actuals consistently. Only platform administrators write to it, and every user with a role can read it. Retired entries can't be chosen for new tags, but existing references keep resolving and show a "Retired" label.
- Coverage shows products by active Integration Types, with Source and Checklist counts and a stale count. Missing coverage is shown as "None" as well as amber, and stale as a "Stale" label.
- Every cited passage must resolve to an exact span of Source text. Logs and traces never contain chunk text or search query text.
- Non-admins who aren't the Source owner get 403 on Knowledge Source writes. All writes use `If-Match`, and a stale `row_version` returns 412 with a concurrent-edit message.

## Technical Decisions

- **Module ownership.** The `knowledge` module owns catalogue entries, Knowledge Sources, chunks and Checklists, in `knowledge_*` tables. Other modules use only `knowledge/application/public.py`: `list_catalogue`, `get_catalogue_entry`, `validate_catalogue_ref`, `search`, `find_applicable_checklists` and `get_coverage`.
- **Versioning.** Entries, Sources and Checklists each have a mutable header with `row_version` and immutable version rows. Earlier versions stay readable. IDs are stable UUIDv7. Checklist items keep a stable item ID across versions. Only one draft Checklist exists at a time, and the published version stays in use until the draft is published.
- **Trace.** Every mutation appends a trace event with `opportunity_id = null`, named `knowledge.<entity>.<past_tense_verb>`, for example `knowledge.catalogue_entry.created`, `.updated` and `.retired`, `knowledge.source.registered` and `.reviewed`, `knowledge.checklist.published` and `.retired`, and `knowledge.reembed.started` and `.completed`. Each event needs a payload model in the trace catalogue, and authorization actions are registered in the identity action catalogue.
- **Retrieval (AD-14).** Postgres with pgvector, with no second search store. `knowledge_chunks` stores text, Source version, catalogue and product tags, Unicode code-point offsets into the extracted-text artifact, `embedding_model`, `embedding_dims` and an untyped `vector` column. Each active model has a partial HNSW expression index `((embedding::vector(1024))) WHERE embedding_model = 'bge-m3'`, and every query uses the same cast and filter so vectors from different models are never compared. Changing the model means a background `knowledge.reembed` job, and search uses only chunks already embedded with the active model.
- **Embeddings.** Produced only through `platform.model_gateway` with the `bge-m3` profile (1024 dims) at `background` priority. Each call writes a `platform_model_calls` row. Chunk size and overlap come from `platform.config`.
- **Evidence (AD-13).** A citation is `{kind: knowledge_chunk, id, version, span}`. A `knowledge` resolver validates it for every later `accept_*` command, and unresolvable references are rejected. A chip whose Source is superseded or retired shows as struck through.
- **Files and parsing (AD-18).** Files go through `platform.storage` and are immutable. Parsing runs as a `knowledge.parse_source` job in the sandboxed subprocess from Epic 2 (CPU, memory and time limits). Extracted text is an immutable artifact linked to the Source version. Embedding runs as `knowledge.embed_source`. Old versions are downloaded through short-lived signed URLs.
- **Search reads** go through `identity.authorize`.
- Source processing statuses: Queued, Parsing, Parsed, Parse failed, Embedding, Embedding failed, Ready. Statuses update live over SSE.
- **Eval fixtures.** `evals/knowledge/` plus `make eval-retrieval` report hit rate at k and citation validity.

## UX & Interaction Patterns

- Knowledge has three sub-tabs, Sources, Checklists and Coverage (`g k`). The catalogue is under Admin → Catalogue.
- Lists use 32px rows, with `j`/`k` and Enter opening the inspector. Selecting a row opens the inspector with metadata, extracted text and version history. `c` creates, and inline edits save on blur.
- Catalogue list: Integration Types and Work Packages shown as two groups, with code, name, current version and status pill. Empty state: "No catalogue entries yet. Press c to add an Integration Type or Work Package."
- Sources list: filters by product, Integration Type, owner and stale. Empty state: "No Knowledge Sources yet. Upload product or integration documentation to start."
- A parse failure shows the red **Parse failed** pill with the reason and **Retry**, and does not affect other Sources.
- Mandatory, Stale and Retired are always an icon plus a label, never colour alone. Actions a user can't take are hidden.
- Coverage matrix: cells are arrow-key navigable with announced row and column headers, and Enter opens the Sources or Checklists sub-tab filtered to that pair. Industry-only Checklists appear in a separate list. Skeletons show for at least 150 ms, and axe must pass in CI (WCAG 2.1 AA).
- Evidence chips open the inspector at the highlighted span with the Source version.
- A duplicate-name rejection reads like "An active Integration Type with this name already exists".

## Cross-Story Dependencies

- Depends on Epic 1 (UoW, trace, `authorize`, `row_version`/412, problem+json, app shell) and on Epic 2 (upload limits and allowlist from Story 2.1, the worker and sandboxed parsing from 2.2, live updates from 2.3, ModelGateway from 2.4).
- 3.1 comes first, because 3.2 and 3.4 tag against catalogue entries. 3.3 extends 3.2's Source pipeline and statuses. 3.5 reads Sources (3.2/3.3), Checklists (3.4) and Opportunity products (via `opportunities` public queries).
- Downstream: Epic 4 uses `find_applicable_checklists`, `search` and `get_coverage` for Gap detection and weak-coverage banners. Epics 5, 8 and 10 reference catalogue IDs and cite `knowledge_chunk` Evidence. Epic 7 reuses the embedding profile and the eval harness.
