---
title: 'Story 1.7 (Part B): All Opportunities filters'
type: 'feature'
created: '2026-10-04'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '862558d7efea590122cc32c2ae054b2295aa22b7'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** All Opportunities lists every Opportunity a user can read, with no way to narrow it down. Once a Head of Delivery or an admin sees every deal, the list stops being usable.

**Approach:** Add filters for status, owner, product and target-proposal-date range to the All Opportunities list API and page. Add a facets query that supplies the owner and product choices, scoped to what the caller can read. Filters live in the URL, so they survive reload, sharing and pagination.

## Boundaries & Constraints

**Always:**
- **Scope:** filters apply to `scope=all` only. My Opportunities stays unfiltered.
- **Filters:** all are optional and combine with AND.
  - `status`: one of the derived status values, filtered in SQL through the same derivation as the status column.
  - `owner`: one user id.
  - `product`: one product name, matched case-insensitively against any of the Opportunity's trimmed products.
  - `from`/`to`: inclusive calendar dates on the target proposal date.
- **Visibility:** filtering never widens it. Results are always a subset of what `list_all` returns for the caller.
- **Facets:** `GET /api/v1/opportunities/facets` returns the distinct owners (id, name) and product names across the Opportunities the caller can read, sorted case-insensitively.
- **Web:**
  - The filter bar sits above the All Opportunities list. Its labelled controls are a status select, an owner select, a product select, and from/to date inputs.
  - Filter values are read from and written to the URL query. Changing a filter resets the page to 1, and pagination links keep the filters.
  - There is a visible "Clear filters" control.
  - When a filter matches nothing, the list says "No Opportunities match these filters." with Clear filters (not the create empty state).
  - Skeleton and keyboard behaviour are as in Part A.

**Never:** No free-text search, no saved filters, no multi-select, no filters on My Opportunities, no backend changes to visibility rules.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Status | `status=intake` / any other valid status | All readable / none (every Opportunity is `intake` today) | N/A |
| Owner | `owner=<id>` | Only Opportunities that user owns, within visibility | Unknown id → empty page |
| Product | `product=crm` with stored "CRM " | Matched | N/A |
| Dates | `from=2026-11-01&to=2026-11-30` | Target dates in that range, inclusive | `from > to` → 422 |
| Combined | Owner + product + range | AND of all three | N/A |
| Invalid | Bad status, bad date or bad UUID | 422 naming the parameter | Web drops invalid params and shows the unfiltered list |
| Visibility | User A filters by an owner whose Opportunities A can't read | Empty page | N/A |
| Facets | User who can read 2 of 5 Opportunities | Owners and products of those 2 only | N/A |
| Empty | Filters match nothing | "No Opportunities match these filters." + Clear filters | N/A |
| URL | Reload or share `/opportunities?owner=…&page=2` | Same filters and page | Page past the end → redirect, as in Part A |
| Mine | `scope=mine` with filter params | Filters ignored | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/opportunities/adapters/repository.py:112` -- `list_page(...)`, ordered by `created_at desc, id desc`. Add the filter predicates here. `products` is `ARRAY(Text)`, so match with `EXISTS (SELECT 1 FROM unnest(products) p WHERE lower(trim(p)) = lower(trim(:product)))`. Status filtering uses a SQL expression that mirrors `domain/opportunity.py:derived_status()` (a constant `'intake'` today) so later stories change one place.
- `backend/app/modules/opportunities/application/opportunities.py:165-190` -- `list_mine`, `list_all` (`identity.can(actor, OPPORTUNITY_READ)` decides everything versus membership). Add a `filters` argument to `list_all` and a `facets(uow, actor)` query using the same visibility predicate.
- `backend/app/modules/opportunities/api/routes.py:88-104` -- `GET /opportunities?scope=`. Add the `status`/`owner`/`product`/`from`/`to` query params (validated, `from <= to`) and the `GET /opportunities/facets` route.
- `backend/app/modules/identity/application/public.py` -- `user_names(uow, ids)` for owner names in facets.
- `backend/tests/test_opportunities.py` -- seeding helpers with roles and the token stub; extend them for filters and facets.
- `web/src/app/opportunities/{data.ts,list-page.tsx,page.tsx}` -- `listOpportunities`, `parsePage`, `OpportunityListPage({scope, searchParams})`, the past-last-page redirect. Add filter parsing and serialisation and pass the filters to the API for `scope=all`.
- `web/src/components/opportunities/opportunities-table.tsx` -- the empty state and skeleton. Add a "filtered" empty variant.
- `web/src/lib/api/schema.d.ts` -- regenerate.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/opportunities/{adapters/repository.py,application/opportunities.py,application/models.py,domain/opportunity.py,api/routes.py}` -- filter predicates, the SQL status expression, `facets`, routes and validation
- [x] `backend/tests/test_opportunities_filters.py` -- every matrix row as `psa_app`, including visibility and facets scoping
- [x] `web/src/lib/api/schema.d.ts`, `web/src/app/opportunities/{data.ts,list-page.tsx,filters.ts}`, `web/src/components/opportunities/{filter-bar.tsx,opportunities-table.tsx}` -- URL filter parsing and serialisation, the filter bar fed by facets, the filtered empty state, page links that keep filters
- [x] `web/src/components/opportunities/filter-bar.test.tsx`, `web/src/app/opportunities/filters.test.ts`, `web/src/app/opportunities/pages.test.tsx` -- parsing (invalid values dropped), URL updates reset the page, clear, filtered empty state, axe

**Acceptance Criteria:**
- Given a Head of Delivery on All Opportunities, when they choose an owner and a product, then the URL holds both, the list shows only matching Opportunities, and reloading keeps them.
- Given CI, when it runs, then backend and web checks all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | Typing a year into a date input pushes a history entry per keystroke; partial years are dropped and the input clears mid-typing | medium | `change` fires on each keystroke with `router.push`; `parseFilters` rejects years < 100 | patch |
| 2 | VG, BH | FilterBar out of sync after Back/Clear; reset compares object references | medium | No test rerenders with new `filters`; `shown !== filters` is reference-based, so a pending selection can be lost | patch |
| 3 | BH, ECH | `scope=mine` returns 422 on invalid filter params | medium | The frozen matrix says Mine ignores filters; FastAPI validates them first | patch |
| 4 | — | SQLAlchemy cartesian-product warning in the facets query | low | `SAWarning` from the products facet; an explicit lateral join over `unnest` is direct | patch |
| 5 | BH, ECH | Reversed date range is silently dropped and both inputs blank | low | No inline error; direct: show an error and don't navigate | patch |
| 6 | BH, ECH | Product length checked before trimming in the API | low | `Query(max_length)` on the raw value; direct | patch |
| 7 | BH, ECH | Facet and status tests compare against a global count in the shared DB | low | Flaky when other rows are inserted between reads; assert within tagged rows | patch |
| 8 | VG | Uppercase owner UUID lowercasing untested | low | Removing `.toLowerCase()` stays green | patch |
| 9 | BH | Facets cases untested: blank stored products, owner tie order | low | Direct tests | patch |
| 10 | BH | When facets fail, a URL owner shows as "Unknown user" | low | Misleading label; direct fallback text | patch |
| 11 | BH | Schema omitted from the diff | false | Deliberately excluded from the review diff; CI's drift check covers it | reject |
| 12 | BH, ECH | Facets unbounded, re-queried per view, no product index | low | Small tables; no named harm yet | reject |
| 13 | BH | Date-order check exists in the route and in the model | low | The model check has no other caller | reject |
| 14 | BH, ECH | `casefold` vs `lower()` vs JS `toLowerCase` on non-ASCII products | low | Rare; the fix needs a normalised stored key | reject |
| 15 | ECH | `min()` spelling depends on the DB collation | low | Display-only choice | reject |
| 16 | BH | Two "Clear filters" links in the no-match state | false | The frozen spec requires Clear filters in the empty state and on the bar | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks (human, signed in as HoD or admin with a few Opportunities):**
- Filter All Opportunities by owner, product and date range; reload and share the URL; clear the filters.
