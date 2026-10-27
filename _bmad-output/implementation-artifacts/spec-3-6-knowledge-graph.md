---
title: 'Story 3.6: Knowledge Graph'
type: 'feature'
created: '2026-10-27'
status: 'in-progress'
baseline_commit: '05c8905c68fe34414d63ff4a757fd77adf892611'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Admins and Checklist editors can read coverage only as tables, so they can't easily see how Products, Integration Types, Sources and Checklists connect, or where documentation is thin.

**Approach:** `knowledge` gets `get_graph` and `GET /api/v1/knowledge/graph`. Both are derived in Postgres from Story 3.5's coverage data, with no new tables. A pure score and status rule lives in `knowledge/domain`. The web app gets a Knowledge → **Graph** sub-tab, first in the nav and shown only to permitted users, built to the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Knowledge → Graph).

## Boundaries & Constraints

**Always:**
- **Who sees it:** the endpoint calls `identity.authorize(actor, Action.KNOWLEDGE_CHECKLIST_EDIT)`, which admins also hold. Anyone else gets 403. In the web app the Graph tab is hidden for those users, and `/knowledge/graph` shows the access-denied branch.
- **Nodes:**
  - Products are the union of Source products, Checklist products and the caller's Opportunity products, matched with `match_key`, as in 3.5.
  - Integration Types are the active ones.
  - Sources are all non-retired Sources, in any state.
  - Checklists are the active Checklists that have a published version (published scope).
- **Edges:**
  - Source–Product and Source–Integration Type, from the Source's tags.
  - Checklist–Product and Checklist–Integration Type, from the Checklist's scope.
  - A Checklist scoped only by industry has no edges.
  - Decision (human): Product–Integration Type edges come from the Knowledge Base only. A **Ready** pair gets a solid `linked` edge. A **Partial** pair, covered only by Sources or only by Checklists, gets a dashed amber `gap` edge. A pair nothing covers gets no edge.
- **Source node status** comes from a pure mapper:
  - **Embedding:** parse or embed is still queued or running.
  - **Embedding failed:** parse or embed failed.
  - **Stale:** Ready but past the stale threshold.
  - **Ready:** Ready and not stale.
- **Product and Integration Type status** is aggregated from their pairs: **Ready** if every pair is Ready, **Missing coverage** if they have no covered pair, otherwise **Partial coverage**. A Checklist takes the status of the pairs it scopes. Decision (human), the computed score:
  - A pair scores 50 when it has at least one fresh Ready Source, or 25 when its Ready Sources are all stale.
  - A pair scores another 50 when it has at least one published Checklist.
  - A Product, Integration Type or Checklist scores the rounded mean of its pairs, or 0 when it has no pairs.
  - A Source scores 15 when its pipeline failed and 70 while it is still embedding. Otherwise it scores the mean of its product × Integration Type pairs.

  Status and score are pure functions in `knowledge/domain/graph.py`, with boundary tests.
- **Canvas:**
  - 660px high (`h-graph`), always dark on `bg-graph-canvas`, using the `graph-*` tokens. The tokens already exist in `globals.css`.
  - Node radius by type: 21, 21, 17 and 19, plus 5 for a node with 6 or more connections.
  - Each node has its type icon, a status badge with a glyph, its label, and the status text (empty when Ready).
  - Stale, failed and missing nodes get a dashed status ring.
  - Edges are solid, and dashed amber for missing coverage.
  - The legend, toolbar, chips, dimming and colours are copied from the mockup.
- **Layout:** the mockup's force loop (420 iterations, same constants, seeded circle start), ported as a pure, deterministic TS function and memoised per data set. No new dependency.
- **Search and filters:**
  - Search dims non-matching nodes to opacity .28.
  - Turning off a type chip removes that type's nodes and every edge touching them.
  - Each chip shows its type's count.
- **Drawer:** an `<aside aria-label="Node details">`, 340px wide, inset 16px, which fills the 372px `w-graph-detail` slot.
  - **Header:** type, label, and "Owner X · Reviewed date". Owner is the Source owner or the Checklist's `created_by`. Products and Integration Types show "—".
  - **Score card:** the score, "/100", a status pill with an icon, and a progress bar.
  - **Tabs:** Overview, Connections and Citations. Overview shows Connections and Stale in only. Connections rows select the neighbour, and a missing-coverage neighbour reads "Missing coverage" in amber. Decision (human): Citations shows only "Citations appear once agent retrieval is logged."
  - **Primary action:** "Open source" opens `/knowledge` with that Source selected. "Edit checklist" opens `/knowledge/checklists` with that Checklist selected. "View coverage" opens `/knowledge/coverage`, filtered for that product or type.
  - **Mark reviewed** appears only on Source nodes, for the Source's owner or an admin who are allowed to write to it (`canWrite`). It reuses `markReviewed` with If-Match. A 412 shows the stale notice, and success announces the change and reloads the graph.
- **Accessibility:**
  - Nodes are `role="button"` with `tabIndex=0` and the aria-label "{label}, {type}, {status}". Enter or Space selects a node, and Esc closes the drawer.
  - Skeleton shows for ≥150 ms (`useSkeletonDone`).
  - axe reports no violations.
- **Empty state:** with no nodes, show an empty card linking to Sources.

**Never:**
- No migration, graph store, or LLM.
- No retrieval statistics ("Used by agents", "Last retrieved", "Cited by"), not even as zero.
- No Mark reviewed for Checklists, since they have no review action.
- No duplicated coverage logic. Reuse 3.5's `_load`/`_tally`.
- `knowledge.application` and `knowledge.domain` never import `opportunities`. Only `graph_routes` may, through one `ignore_imports` line.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Ready pair | P×T: fresh Ready Source + published Checklist | P, T, Source and Checklist nodes; edges S–P, S–T, C–P, C–T; P and T Ready | N/A |
| Stale Source | Ready Source past threshold | Source node `stale`, dashed ring; its pairs not Ready | N/A |
| Pipeline | Source parsing or embedding / parse or embed failed | `embedding` / `embedding_failed` node, still linked | N/A |
| Opportunity-only product | Product only on an Opportunity | Product node, `missing`, no solid edges | N/A |
| Industry-only Checklist | Checklist scoped by industry only | Node with no edges | N/A |
| Excluded | Retired Source / retired or draft-only Checklist / retired type | Not in the graph | N/A |
| Not permitted | Caller with a role but no `knowledge.checklist.edit` | — | 403 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/knowledge/domain/graph.py` (new): `NodeStatus`, `source_node_status(parse, embed, stale)`, `pair_score(...)`, `node_score(...)`, `aggregate_status(...)`. Reuse `domain/coverage.py:14` `coverage_status`, `sources.py:90` `is_stale`, and the parse/embed enums (`platform/parsing/rules.py:15`, `domain/embedding.py:17`).
- `backend/app/modules/knowledge/application/coverage.py:78,96`: `_load` and `_tally`. Move them to a shared internal module, or make them module-level non-private. Do not change their behaviour.
- `backend/app/modules/knowledge/application/graph.py` + `graph_models.py` (new): `get_graph(uow, actor, *, extra_products, stale_months, today=None) -> KnowledgeGraph{nodes, edges}`. A node has `id, type, label, status, score, owner, last_reviewed_on, row_version?, can_review, stale_in_days?`. An edge has `source, target, kind: linked|gap`.
  - Sources come from `source_repository.list_sources` (:147) via `sources._views` (:219), which provides owner names and the stale flag.
  - Checklists come from `checklist_repository.published_active` (:110) and `tags_for` (:123).
  - Integration Types come from `list_catalogue(uow, Kind.INTEGRATION_TYPE)`.
  - Node ids are prefixed by type (`product:<match_key>`, `source:<uuid>`, …).
- `backend/app/modules/knowledge/application/public.py:61-66,146+`: export `get_graph` and the models.
- `backend/app/modules/knowledge/api/graph_routes.py` (new): `GET /knowledge/graph`, `operation_id="get_knowledge_graph"`. Copy `coverage_routes.py:124-143`, including `facets` for the Opportunity products. Mount it in `app/main_api.py:27-31,146-150`, and add the `ignore_imports` line beside `pyproject.toml:332`.
- Tests: `backend/tests/test_knowledge_graph_domain.py` (pure, boundaries) and `test_knowledge_graph.py` (API, the matrix above). Reuse the fixtures and helpers in `test_knowledge_coverage_matrix.py:55-135`, plus `_ready` (`test_knowledge_embedding.py:303`), `_backdate` (`test_knowledge_sources.py:181`), `_author` and `_published` (`test_knowledge_checklists.py:60-159`).
- `web/src/lib/coverage.ts:14-16`: add `GRAPH_HREF="/knowledge/graph"`. In `components/knowledge/knowledge-nav.tsx:7-11`, put Graph first and make it conditional through a `showGraph` prop. Callers pass `canAuthor(me.permissions)` (`lib/checklists.ts:63`).
- `web/src/app/knowledge/graph/page.tsx` + `actions.ts` (new): copy `knowledge/coverage/page.tsx` and its `actions.ts` (ok / forbidden / error).
- `web/src/lib/knowledge-graph.ts` (new): types from `schema.d.ts`, the status table (colour token, glyph, label), type metadata (icon, colour, radius), `layoutGraph(nodes, edges)` (the pure port), and `filterGraph`.
- `web/src/components/knowledge/graph-canvas.tsx`, `graph-toolbar.tsx`, `graph-legend.tsx`, `graph-drawer.tsx` (new). The tablist pattern comes from `opportunities/workspace-tabs.tsx`. Use `Pill`, `Skeleton`, `Button` and `useAnnounce`. Mark reviewed follows the flow in `source-inspector.tsx:230-236`.
- Web tests: `lib/knowledge-graph.test.ts` (layout determinism and bounds, filter), the component tests (aria-labels, keyboard, chips and counts, drawer content, no retrieval stats, Mark reviewed gating and 412, axe, skeleton), `knowledge-nav.test.tsx`, and `graph/page.test.tsx` (ok, 403, unreachable). Fixtures go in `test/knowledge-fixtures.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/graph.py` + domain test: status, score and aggregation rules with boundaries.
- [x] Share `_load`/`_tally`; `application/graph.py`, models, `public.py`: build the nodes and edges.
- [x] `graph_routes.py`, mount, `pyproject.toml` ignore: the endpoint with 403.
- [x] `backend/tests/test_knowledge_graph.py`: every matrix row plus edge kinds.
- [x] `npm run gen:api`, then `lib/knowledge-graph.ts` with the layout port and filters.
- [x] Nav, the Graph page, canvas, toolbar, legend, drawer.
- [x] Web tests as listed in the Code Map.

**Acceptance Criteria:**
- Given the Graph at 1440px, in light and dark, then it matches the mockup's canvas, toolbar, legend, nodes and drawer, and the canvas stays dark in the light theme.
- Given the same data, when the page reloads, then every node is in the same position.
- Given a Source node selected by its owner, when they press Mark reviewed, then the node is no longer Stale and the change is announced.
- Given a user who can't edit Checklists, when they open Knowledge, then there is no Graph tab and `/knowledge/graph` shows the access-denied message.

## Implementation Notes

- Work only in the worktree `D:\pre-sales-agent\.claude\worktrees\story-3-6-knowledge-graph` (branch `task/story-3-6-knowledge-graph`). Never edit `D:\pre-sales-agent` outside it. Do not commit or push.

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest`: all pass. Use `PSA_DATABASE_URL`/`PSA_MIGRATIONS_DATABASE_URL` on `127.0.0.1:5432/psa_test`, NEVER the dev `psa` DB.
- `npm run gen:api` against a fresh local uvicorn or a dumped `app.openapi()`.
- `cd web && npm run lint && npm run typecheck && npm test && npm run build`: all pass. Don't use Prettier.

**Manual checks:**
- Screenshot the Graph at 1440px in light and dark and compare it with the mockup.
