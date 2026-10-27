# Epic 3 Context: Knowledge Base and catalogue

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the platform its own internal evidence base. Admins and domain experts load product and integration documentation, write versioned Checklists, and maintain the Integration Type and Work Package catalogue. Administrators and Checklist editors can then see where coverage is weak, both as tables (Coverage matrix, Sources list) and as an explorable Knowledge Graph. There is no archive of past proposals, so at launch the Knowledge Base is the main source of citable evidence, and Gap detection (Epic 4) and the agents (Epic 5) depend on it.

## Stories

- Story 3.1: Integration Type and Work Package catalogue
- Story 3.2: Register Knowledge Sources by upload
- Story 3.3: Chunk, embed and search Knowledge with citable passages
- Story 3.4: Author and version Checklists
- Story 3.5: Knowledge coverage view
- Story 3.6: Knowledge Graph

## Requirements & Constraints

- Knowledge Sources (`.pdf`, `.docx`, `.txt`, `.md`) have an owner, product, Integration Type tags, product version and a last-reviewed date. A Source not reviewed in 12 months (`PSA_KNOWLEDGE_STALE_MONTHS`, default 12) is flagged stale. The flag is derived, not stored, and is cleared by **Mark reviewed** (owner or admin).
- Upload limits and the extension allowlist are shared with Opportunity Sources (Epic 2). Files are stored unchanged by SHA-256. An oversized file, a disallowed extension or a magic-byte mismatch is rejected with a specific reason.
- Checklists are authored by engineering, PM or security reviewers or platform administrators. Other roles can only read them. Items are questions or risks and can be marked mandatory. Mandatory items always produce a Gap when unanswered (Epic 4). A mandatory item on a `security` Checklist is a mandatory security control that can never be overridden.
- The catalogue classifies Checklists, Assessment lines, Estimate lines and Actuals consistently. Only admins write to it, and every user with a role can read it. Retired entries can't be chosen for new tags, but existing references keep resolving and show a "Retired" label.
- **Coverage:** a matrix of products by active Integration Types. Each cell has a Source count, a Checklist count and a stale count, and reads Ready (a Ready Source and an active Checklist), Partial (only one of them, or all Sources stale) or Missing (neither). Product rows are the union of Source and Checklist tags and the products in scope on Opportunities.
- **Knowledge Graph:** nodes are Products, Integration Types, Knowledge Sources and Checklists, with their links. It has search and type filters with counts. Each node shows owner, last reviewed, a deterministic Coverage score (0 to 100) and a status (Ready, Partial or Stale, Missing or Failed, Embedding). Missing coverage is drawn as a distinct link. The score uses Ready non-stale Sources and active published Checklists for each product and Integration Type pair. The PRD flags the exact score formula as an open assumption, so keep it in one pure function with boundary tests.
- Only admins and roles that can edit Checklists can open the Graph. Anyone else gets 403 from the endpoint. The Sources table and Coverage matrix must always hold the same facts, so the graph is never the only route to the data.
- Retrieval statistics ("Used by agents", "Last retrieved", "Cited by") are left out entirely until agent retrieval is logged. Don't show them even as zero.
- Every cited passage must resolve to an exact span of Source text. Logs and traces never contain chunk text or search query text.
- Writes use `If-Match`. A stale `row_version` returns 412 with the concurrent-edit message.

## Technical Decisions

- **Module ownership.** `knowledge` owns catalogue entries, Sources, chunks and Checklists in `knowledge_*` tables. Other modules use only `knowledge/application/public.py`: `list_catalogue`, `get_catalogue_entry`, `validate_catalogue_ref`, `search`, `find_applicable_checklists`, `get_coverage`, and `get_graph(filters)` (added in 3.6).
- **Versioning.** Each entity has a mutable header with `row_version` plus immutable version rows. IDs are stable UUIDv7. Checklist items keep their ID across versions. Only one draft Checklist exists at a time, and the published version stays in use until the draft is published.
- **Trace.** Every mutation appends `knowledge.<entity>.<past_tense_verb>` with `opportunity_id = null` (for example `catalogue_entry.created`, `source.registered`, `source.reviewed`, `checklist.published`, `reembed.completed`). Each event needs a payload model in the trace catalogue, and each authorization action must be registered in the identity action catalogue.
- **Retrieval.** Uses Postgres pgvector with no second search store. `knowledge_chunks` stores code-point offsets into the extracted-text artifact, plus `embedding_model`, `embedding_dims` and an untyped `vector`. Each model gets a partial HNSW expression index (`embedding::vector(1024) WHERE embedding_model = 'bge-m3'`), and every query uses the same cast and filter. A model change triggers a background `knowledge.reembed` job. Embeddings go only through `platform.model_gateway` (`bge-m3`, `background` priority).
- **Evidence.** A citation is `{kind: knowledge_chunk, id, version, span}`. A `knowledge` resolver validates it for later `accept_*` commands.
- **Files and parsing.** Files go through `platform.storage`. The `knowledge.parse_source` job runs in the Epic 2 sandboxed subprocess, and `knowledge.embed_source` follows it. Source statuses are Queued, Parsing, Parsed, Parse failed, Embedding, Embedding failed and Ready, and they update live over SSE.
- **Graph as a derived read model.** `get_graph` computes nodes and edges over the `knowledge_*` tables in Postgres. There is no graph database or graph store. Products come from tags, and edges come from Source tags and Checklist scopes. The Coverage score and status are pure functions in `knowledge/domain`, with unit and boundary tests and no LLM involvement. Reuse the Coverage (3.5) data rather than duplicating its logic. Retrieval stats will later come from an insert-only `knowledge_retrievals` table (chunk ID, agent ID, run ID, time, no query text) written by the ToolGateway search tool (Story 5.4). Don't build that table in this epic.
- **Authorization.** Roles are enforced in the API through `identity.authorize`. Run `npm run gen:api` after adding the graph endpoint.

## UX & Interaction Patterns

- Knowledge sub-tabs are, in order, Graph, Sources, Checklists and Coverage (`g k`). The Graph tab appears only once 3.6 ships and only for permitted roles. The catalogue lives under Admin → Catalogue.
- Lists use padded rows. `j`/`k` and Enter open the right-pane inspector, `c` creates, and inline edits save on blur. Single-key shortcuts follow the Settings switch (default Off), and every action also has a visible control. Actions a user can't take are hidden.
- **Graph canvas:** 660px high and force-directed on `graph-canvas` (always dark, even in the light theme). Node colour tokens are `graph-product`, `graph-integration-type`, `graph-knowledge-source` and `graph-checklist`. Status badges use `graph-ready`, `graph-checklist`, `graph-missing` and `graph-product`, always with a glyph and a text label. Edges use `graph-edge`, `graph-edge-selected` when selected, and dashed `graph-edge-gap` (amber) for missing coverage. The legend shows solid for documented or linked, dashed for missing coverage, and a dashed ring for stale, failed or missing nodes.
- **Node drawer (372px):** shows type, owner, last reviewed, Coverage score and status pill. It has Overview, Connections and Citations tabs. The primary action depends on the node: Edit checklist, Open source or View coverage. **Mark reviewed** reuses 3.2 and is shown to the owner or an admin.
- **Accessibility:** graph nodes are keyboard-focusable and announce their type, label and status. The keyboard alternative is the Coverage matrix plus the Sources table. Coverage cells are navigable with arrow keys and announce their headers. Mandatory, Stale and Retired always show an icon plus a label. axe must report no WCAG 2.1 AA violations in CI. Skeletons show for at least 150 ms.
- **Copy:** the Checklist denial reads "You do not have permission to edit Checklists. Ask an admin for the right role." The Sources empty state reads "No Knowledge Sources yet. Upload product or integration documentation to start." The catalogue empty state reads "No catalogue entries yet. Press c to add an Integration Type or Work Package."

## Cross-Story Dependencies

- Epic 3 builds on Epic 1 (UoW, trace, `authorize`, 412, problem+json, app shell) and Epic 2 (upload limits from 2.1, worker and sandbox from 2.2, SSE from 2.3, ModelGateway from 2.4). Epic 17's token layer (17.1) comes before every new UI story, so the `graph-*` tokens should come from it.
- 3.1 comes before 3.2 and 3.4, which tag against the catalogue. 3.3 extends the 3.2 pipeline. 3.5 reads 3.2, 3.3 and 3.4, and gets Opportunity products through `opportunities` public queries. 3.6 depends on 3.4 and 3.5, reuses 3.2's Mark reviewed, and is scheduled last in Release 1.
- Downstream, Epic 4 uses `find_applicable_checklists`, `search` and `get_coverage`. Epics 5, 8 and 10 reference catalogue IDs and cite `knowledge_chunk` Evidence. Story 5.4 later adds `knowledge_retrievals`, which turns on the graph's retrieval stats.
