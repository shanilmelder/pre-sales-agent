---
title: 'Story 3.5: Knowledge coverage view'
type: 'feature'
created: '2026-10-23'
status: 'in-review'
baseline_commit: '6b24fae81f910547f3aade606e13bbe742254072'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Admins can't see which products and Integration Types lack documentation or Checklists, so they don't know where Gap detection is weak or whose time to ask for.

**Approach:** `knowledge` gains a pure coverage rule, `knowledge.public.get_pair_coverage(products, integration_type_ids)` and `GET /api/v1/knowledge/coverage`. The web app gets a Knowledge → Coverage sub-tab built to the new mockup (`ux-designs/ux-pre-sales-agent-2026-10-01/new-mockups/Presales Agent Design Spec (standalone).html`, Knowledge → Coverage). It has a product × active Integration Type matrix card, an "Industry Checklists" list, and cells that open the Sources or Checklists sub-tab filtered to that pair.

## Boundaries & Constraints

**Always:**
- Source count: non-retired Sources whose latest version's embed status is `ready`. Stale count: how many of those are stale (`domain/sources.is_stale`, `knowledge_stale_months`). Checklist count: active Checklists that have a published version (`published_active`), using the published scope only.
- Pairing: a Source counts for its one product × each of its Integration Type tags. A Checklist counts for each scoped product × each scoped Integration Type. A Checklist with products but no Integration Types counts in every column of those products. One with Integration Types but no products counts in every row of those columns. One scoped only by industry appears only in the Industry list. Decision (human, review loop 1): this is deliberately narrower than `find_applicable_checklists`, which matches on any one dimension. A cell answers whether that exact pair is documented. Products match trimmed and casefolded (`match_key`).
- Status (pure function, boundary-tested): **Ready** = ≥1 non-stale Source and ≥1 Checklist. **Partial** = exactly one kind, or Sources all stale with a Checklist. **Missing** = no Sources and no Checklists. The tones follow the mockup: Ready green (`resolved`, `CircleCheck`), Partial amber (`gap`, `TriangleAlert`), Missing red (`blocker`, `CircleAlert`). Every cell shows its label and counts. A missing kind reads "None", and all-stale Sources read "Stale". Meaning never depends on colour.
- Product rows are the union of Source products, Checklist products and Opportunity products the caller can read. The route reads the Opportunity products through `opportunities.application.public.facets(uow, actor)`, which gives admins and Head of Delivery every Opportunity. Rows are sorted ignoring case. Columns are the active Integration Types.
- Every role can read Coverage (`_require_role`, like the other Knowledge reads). A caller with no role gets 403.
- Sub-tabs read Sources, Checklists, Coverage (Graph is added later by Story 3.6), in the mockup's segmented style.
- Cells are a `role="grid"`. Arrow keys move between cells. Row and column headers are announced. Skeleton cells show for ≥150 ms on first load. axe reports no violations.
- Decision (human): activating a cell (Enter or click) opens Sources filtered to its product and Integration Type. Inside the cell, the Checklist count is its own visible link to Checklists with the same filter, reached with Tab.

**Never:**
- No migration, no stored coverage, no Graph (3.6), no weak-coverage banners on other screens (Epic 4).
- `knowledge.application`/`domain` never import `opportunities`. Only the coverage route may, through one `ignore_imports` line.
- No new API filters on Checklists. Filtering is client-side.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Ready | P×T: 1 Ready fresh Source, 1 published Checklist | `ready`, sources 1, stale 0, checklists 1 | N/A |
| All stale | 2 Ready Sources, both stale, + Checklist | `partial`, "Stale" label | N/A |
| One kind | Source only, or Checklist only | `partial`, "None" for the absent kind | N/A |
| Neither | Product only on an Opportunity | Row present, every cell `missing` | N/A |
| Excluded | Source retired / not yet Ready; Checklist retired / draft-only | Not counted | N/A |
| Industry only | Checklist with industry "Retail", no products or types | Only in industries: Retail 1 | N/A |
| No role | Caller has no roles | — | 403 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/knowledge/domain/coverage.py` (new): `CoverageStatus` and `coverage_status(sources, stale, checklists)`. The pure rule.
- `backend/app/modules/knowledge/adapters/source_repository.py`: add a query for non-retired, latest-embed `ready` Sources with product, `last_reviewed_on` and tag entry ids. Reuse the `embed_status` join (:141) and `tags_for` (:189).
- `backend/app/modules/knowledge/adapters/checklist_repository.py`: `published_active` (:110) and `tags_for` (:123) already give scope.
- `backend/app/modules/knowledge/application/coverage.py` + `coverage_models.py` (new):
  - `get_pair_coverage(uow, *, products, integration_type_ids, stale_months)` returns counts per pair. Story 4.1's `get_coverage` (per product and per type, Sources only) lives in the same file and shares `source_repository.ready_sources`.
  - `coverage_matrix(uow, actor, *, extra_products, stale_months)` returns the integration types, rows, cells and industries.
  - Integration Types come from `list_catalogue(uow, Kind.INTEGRATION_TYPE)` (`catalogue.py:374`). Matching uses `domain/checklists.match_key` (:140).
- `backend/app/modules/knowledge/application/public.py:108-193`: export both functions and the models.
- `backend/app/modules/knowledge/api/coverage_routes.py` (new): `GET /knowledge/coverage`, `operation_id="get_knowledge_coverage"`. Copy the pattern at `source_routes.py:131-162` (settings come from `request.app.state.settings`). Mount it in `app/main_api.py:142-145`.
- `backend/pyproject.toml:272`: add `ignore_imports = ["app.modules.knowledge.api.coverage_routes -> app.modules.opportunities.application.public"]`. Precedent: the conflicts contract.
- Tests: `backend/tests/test_knowledge_coverage_domain.py` (pure) and `test_knowledge_coverage_matrix.py` (`test_knowledge_coverage.py` is Story 4.1's). Reuse the helpers `_ready`/`_drain`/`ollama` (`test_knowledge_embedding.py:114,230,301`), `_backdate` (`test_knowledge_sources.py:181`), `_entry`/`_published` (`test_knowledge_checklists.py:65,159`) and `tests/conftest.py`.
- `web/src/components/knowledge/knowledge-nav.tsx:3-8`: add Coverage (`/knowledge/coverage`). Restyle to the segmented track in `opportunities/opportunity-views.tsx:25-36`.
- `web/src/app/knowledge/coverage/page.tsx` + `actions.ts` (new): copy `app/knowledge/checklists/page.tsx:32-55` (`getMe`, `AccessGate`, `AppShell`, `PageHeader`, `PageContent`).
- `web/src/lib/coverage.ts` (new): types from `lib/api/schema.d.ts`, status labels and tones, and the cell href builder.
- `web/src/components/knowledge/coverage-matrix.tsx` + `industry-checklists.tsx` (new):
  - `Card` (`ui/card.tsx`), `Pill` with `icon` (`ui/pill.tsx:48`) and `Skeleton` (`ui/skeleton.tsx`).
  - Mockup layout: a `surface-alt` header band with a 12px secondary "Product" column of 200px, then equal columns and padded rows with a top border.
  - Grid keyboard code is new. Copy the roving approach in `sources-table.tsx:101`.
- `web/src/lib/use-skeleton-done.ts` (new): extract `useSkeletonDone` from `opportunities/opportunities-table.tsx:47-54` (`SKELETON_MIN_MS`, `lib/opportunities.ts:42`) and reuse it there.
- `web/src/app/knowledge/page.tsx` + `sources-tab.tsx:54`: Story 4.1's `initialFilters` prop, seeded from `?product=&integration_type=` (`initialSourceFilters`, which uses `seededFilters`).
- `web/src/app/knowledge/checklists/page.tsx` + `checklists-tab.tsx:51-55`: add product and Integration Type filters (client-side), seeded from the same params, in the same style as the selects at `sources-tab.tsx:168-190`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/coverage.py` + domain test: the status rule and every boundary.
- [x] Repository query, `application/coverage.py`, models, `public.py`: counts, the union and industries.
- [x] `coverage_routes.py`, mount, `pyproject.toml` ignore: the endpoint.
- [x] `backend/tests/test_knowledge_coverage.py`: every matrix row, the pairing rules, union and order, Opportunity products respecting visibility, 403.
- [x] `npm run gen:api`, then `lib/coverage.ts`, the hook extraction, nav, the Coverage page and components: the Coverage sub-tab.
- [x] Sources and Checklists URL-seeded filters, plus the Checklists filter UI.
- [x] Web tests: the matrix (labels, "None", "Stale", arrow keys, Enter navigates, skeleton ≥150 ms, axe), industry list, nav order, filters seeded from params.

**Acceptance Criteria:**
- Given the Coverage page at 1440px, in light and dark, then it matches the mockup's card, header band, row padding and pill styling.
- Given a cell, when it is activated, then the target sub-tab loads with its product and Integration Type filters already applied.
- Given another module, when it calls `get_pair_coverage(products, ids)`, then it gets the counts for exactly those pairs.

## Implementation Notes

- Work only in the worktree `D:\Projects\Office\pre-sales-agent-coverage` (branch `story/3-5-knowledge-coverage-view`); never edit `D:\Projects\Office\pre-sales-agent`. Do not commit or push.

## Spec Change Log

- Review loop 1 (intent_gap): the pairing rule claimed parity with `find_applicable_checklists` but is product × type. The human chose to keep product × type, and the frozen claim is reworded. The code already follows the rule, so it wasn't reverted (re-derivation would produce the same code). KEEP: everything implemented. Still to do: the patches marked "Patch" in the Review Triage Log, and rewording the parity claim in the docstrings of `application/coverage.py` and `web/src/lib/checklists.ts` (`applyChecklistFilters`).
- Merge of main (Stories 4.1 and 4.2), 24 Oct: 4.1 had already shipped its own `knowledge.get_coverage` (per product and per type, Sources only; used by the Gaps context) in the same `coverage.py`, plus `?product=&integration_type=` Sources filters. Decision (human): 4.1 keeps `get_coverage`; this story's pair counts become `get_pair_coverage`, and the frozen Approach and acceptance criterion are reworded to that name. The duplicate `ready_sources` query is merged into 3.5's (it carries tags), the URL param is `integration_type` everywhere (cells, Checklists, the Gaps banner) and parsed by `seededFilters` alone, and 3.5's API tests moved to `test_knowledge_coverage_matrix.py`. KEEP: everything else.

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| Checklist pairing (product × type) is narrower than `find_applicable_checklists` (`scope_matches`: product OR industry OR type), though the spec claims parity | high | `domain/checklists.py:177-192` matches on any single dimension; `_tally` counts [Q]×[T2] only at Q×T2. The frozen pairing rule contradicts its own parity claim → intent_gap |
| The industry part of a mixed scope (products + industry) is not shown | medium | Same root cause: which scope dimensions count where → grouped with the row above, intent_gap |
| Checklists filter from a cell link shows retired Checklists the count excludes | medium | `applyChecklistFilters` ignores `status`; `loadChecklists` asks for `include_retired`. Patch: exclude retired when a filter is set |
| Sources tab from a cell shows pending or failed Sources the count excludes | low | That tab is where pending Sources belong; the fix adds a new filter. Rejected |
| Checklist tagged only with retired types, and no products, appears nowhere | low | Rare, and depends on the pairing decision. Rejected |
| `coverage_matrix` re-implements the role check instead of `_require_role` | low | `_require_role` is private and copied per file (3 copies already). Rejected |
| Route calls `facets` before the role check | low | Behaviour correct and tested (`test_a_caller_with_no_role_gets_403`). Rejected |
| `get_coverage` reloads every Source and Checklist on each call | low | No caller yet; the fix is caching. Rejected |
| casefold vs `toLowerCase` between backend and web | low | Only rare characters; already rejected in Story 3.4. Rejected |
| Industry Checklists links open an unfiltered list | low | Needs a new industry filter UI. Rejected |
| `COVERAGE_STATUSES[*].icon` unused (duplicate of `ICONS`) | low | Direct deletion. Patch |
| Ctrl/Cmd/Shift-click on a cell does nothing | medium | `onCellClick` returns early on modifiers and the cell has no href. Patch: open `sourcesHref` in a new tab on modifier or middle click |
| Sprint status: 3-4 still `backlog` | low | Pre-existing, not caused by this story → defer |
| Spec file untracked in the main repo | false→fixed | It was a 0-byte file my own PowerShell write created at the wrong path; deleted. Not part of the diff |
| Missing tests: non-default `stale_months`, blank product, modifier link click, 403 with a real no-role user | low | Partly covered (domain tests, the 403 API test). Rejected beyond the verification-gap patches |
| Skeleton reappears on client-side navigation back to the tab | low | Same pattern as the Opportunities table. Rejected |
| `PRODUCT_PARAM_MAX = 200` is a guess | low | Backend `PRODUCT_MAX = 120` (`domain/sources.py:15`); 200 still covers it. Rejected |
| `get_coverage` with retired or unknown Integration Type ids counts product-only Checklists for them | low | No caller yet. Patch: keep only active ids (direct filter) |
| `withOption` doesn't trim | false | `seededFilters` trims `wanted`; Source and Checklist products are stored trimmed by the API |
| No page test that `?product=&type=` reaches the Sources and Checklists tabs | medium | Verification-gap, pre-verified. Patch: page tests with `searchParams` |
| No test of the "latest version only" Ready condition | medium | Verification-gap, pre-verified. Patch: add a version to a Ready Source and assert the counts |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest`: all pass. Use `PSA_DATABASE_URL` and `PSA_MIGRATIONS_DATABASE_URL` on `127.0.0.1:5432/psa_test`, NEVER the dev `psa` DB.
- `npm run gen:api`: against a fresh local uvicorn or a dumped `app.openapi()`.
- `cd web && npm run lint && npm run typecheck && npm test && npm run build`: all pass. Don't use Prettier.

**Manual checks:**
- Screenshot Coverage at 1440px in light and dark and compare it with the mockup.
