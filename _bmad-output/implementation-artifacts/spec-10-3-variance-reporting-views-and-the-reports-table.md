---
title: 'Story 10.3: Variance reporting views and the Reports table'
type: 'feature'
created: '2026-10-27'
status: 'in-progress'
baseline_commit: 'dc3a8f90eec9f8f2daaca26a176a3dee01ed2fce'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-1-record-actuals-per-estimate-line.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Actuals are now recorded (10.1), but nobody can see across Opportunities where estimates go wrong. `/reports` is a placeholder visible to every role.

**Approach:** Add read-only SQL views `reporting_estimate_vs_actual` and `reporting_failed_assumptions`. Add a `reporting` module that aggregates them in SQL behind a new role-scoped action `reporting.report.read`, granted only to the Head of Delivery and the platform administrator. Build the Reports **Estimate vs actual** sub-tab exactly as the **new mockup** draws it (the `<!-- REPORTS -->` block): segmented sub-tabs, three KPI tiles, the card "Estimate versus actual by Integration Type" with a diverging variance bar, and the info strip.

## Boundaries & Constraints

**Always:**
- **Views:** `reporting_estimate_vs_actual` has one row per current Actual: opportunity id/title/products, closed_at, estimate_version_id + version number, line id + label `L{n}`, line effort (0 for Unplanned work), actual effort, kind, cause, integration_type_ids, work_package_id, failed count. `reporting_failed_assumptions` has one row per failed-Assumption reference, carrying the Assumption kind and version.
- **Grants:** `psa_app` has SELECT only on `reporting_*`, with INSERT, UPDATE and DELETE explicitly revoked because the default privileges grant them. A test proves all three fail.
- **Arithmetic:** all variance arithmetic is in SQL or the domain, never in the browser.
- **API:** `GET /api/v1/reports/estimate-vs-actual?group_by=integration_type|opportunity|product|work_package|cause&product=&work_package_id=&cause=&closed_from=&closed_to=&include_milestones=false`. It returns:
  - the KPIs: closed Opportunities, total variance h and %, est/actual totals, failed Assumptions by kind;
  - groups: key, label, opportunity count, est h, actual h, variance h/%/direction/label, main cause, failed count;
  - each group's Opportunities, with version number and Baseline flag.
- **Access:** other roles, including the delivery manager, get 403. Rows are restricted to the Opportunities the actor can read, via a new `opportunities.public` visibility helper, before aggregating.
- **Variance colour:** the bar and percent are red only above +10%, green below −5%, otherwise neutral, always with a `+`/`−` sign and an sr-only "over"/"under" label.
- **Defaults:** final Actuals only. Milestones are included only via the toggle.
- **Table:** sortable headers carry `aria-sort`. Figures use tabular numbers.
- **Empty state:** "No Actuals recorded yet. Delivery managers record them in an Opportunity's Actuals tab."
- **Nav:** the Reports nav item, palette entry and `g r` show only with `reporting.report.read`. The page renders "No access" without it.

**Never:**
- No drill-down sorting or filter carry-over on the Actuals tab, and no failed-Assumption list (10.4).
- No Pipeline (10.7) or Cost and usage (7.5) content: those sub-tabs render "Not available yet."
- No calibration logic.
- No write path, no new tables, no browser arithmetic.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Group | IT "SAP EWM": est 420, act 468 | Row "+11.4%", red bar right of centre | N/A |
| Under | est 96, act 88 | "−8.3%", green, left of centre | N/A |
| Unplanned | no line, 12 h, WP only | Counts est 0 / act 12 in totals; IT group "No Integration Type" | N/A |
| Multi-tag | Actual with 2 ITs | Appears in both IT groups; KPIs count it once | N/A |
| Milestone | current Actual `milestone` | Excluded unless `include_milestones=true` | N/A |
| Zero estimate | group est 0 | percent null, label "+12.0 h" | N/A |
| Forbidden | delivery manager GET | — | 403 problem+json |
| Empty | no Actuals | Empty state text; KPIs hidden | N/A |
| Write on view | psa_app INSERT/UPDATE/DELETE | — | permission denied |

**Decisions (2026-10-27):**
- **Columns:** keep the mockup's five columns. Each group name carries a muted subline, "3 Opportunities · 2 failed Assumptions", with the counts as text.
- **Export and strip:** the header shows **Export** disabled, with the tooltip "Export arrives in a later release". The "Calibration is not available yet." strip is shown, and its sentence is computed from real closed-Opportunity counts per Integration Type (the threshold is 5).
- **Controls:** one toolbar row sits between the sub-tabs and the KPIs: Group by, Product, Work Package, Cause, closed from/to, and an "Include milestones" switch. All of it is kept in URL params.
- **Main-cause link:** on a group row it applies `cause=` as a filter. On an expanded Opportunity row it opens that Opportunity's Actuals tab.
- **Scope:** the full scope stays in this story (no split), at about 2,500 tokens.

</frozen-after-approval>

## Code Map

- **New module `backend/app/modules/reporting/`:**
  - `application/estimate_vs_actual.py` (SQL aggregation over the views, using `sa.text`/`table()`)
  - `application/models.py` (pydantic view)
  - `api/routes.py` (model it on `knowledge/api/coverage_routes.py`; Query params as in `opportunities/api/routes.py:114-170`)
  - `domain/variance.py`: reuse `actuals.domain.actuals.variance` only via `actuals/application/public.py` (add an export), or move the rounding rule. Do not import actuals' domain directly.
  - Register it in `app/main_api.py:17-40,135+`.
  - Add an importlinter contract in `pyproject.toml`, copying the actuals block at :482-528.
- **Migration** `backend/migrations/versions/20261027_0055_reporting_views.py`, revision `0055_reporting_views`, down `0054_actuals_imports` (re-chained after Story 10.2 took 0054):
  - `CREATE VIEW`, then `GRANT SELECT` and `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ... FROM psa_app` (the trap is at `0002_platform_trace.py:82-85`).
  - The downgrade drops the views.
  - Line label: `row_number() OVER (PARTITION BY version_id ORDER BY position)` over `estimates_estimate_lines`.
  - Catalogue name: max `version` in `knowledge_catalogue_entry_versions` per `entry_id`.
  - Baseline: latest `set_at` in `estimates_baselines`.
  - Closed: `actuals_deliveries.closed_at`.
  - Failed refs: `jsonb_array_elements(failed_assumptions)` → `estimates_assumptions.kind`.
- **Access:**
  - `identity/actions.py:22-123,144-215`: add `REPORTING_REPORT_READ = "reporting.report.read"` and its category.
  - `scripts/seed_auth0.py:50-89`: grant it to `head_of_delivery` and `platform_administrator`.
  - The route calls `authorize(actor, Action.REPORTING_REPORT_READ)` (pattern `identity/application/role_admin.py:61`).
  - `opportunities/application/public.py`: expose a readable-ids or predicate helper built from `opportunities.py:183 _visibility`.
- **Web:**
  - `web/src/app/reports/page.tsx`: replace the placeholder. Sub-tabs are routes: `/reports` (Estimate vs actual), `/reports/pipeline`, `/reports/cost`. Copy the segmented nav from `components/knowledge/knowledge-nav.tsx:16-40`, restyled to the mockup's pill segments.
  - Data: `app/reports/data.ts` with the `{kind: ok|forbidden|error}` pattern (`app/knowledge/coverage/actions.ts`); the no-access page pattern is `admin/agents/page.tsx:55-62`.
  - New `components/reports/{variance-kpis,variance-table,variance-bar,report-filters}.tsx`.
  - Extract `KpiTile` from `opportunities/overview-summary.tsx:116-151` into `components/ui/kpi-tile.tsx`.
  - Reuse the sortable header from `actuals-table.tsx:415-429` and `lib/actuals.ts:80-99`, `causeLabel` (`lib/actuals.ts:71`), `Select`, `Switch`, the native date input from `filter-bar.tsx:147`, URL parsing in the style of `opportunities/filters.ts`, `EmptyTabCard`, and `tabHref` (`lib/workspace.ts:30`).
  - Nav: `lib/navigation.ts`, add `requires?: Permission` on `NavItem`. Update `visibleNav`, `lib/shortcuts.ts:46,115`, `shell/keyboard-shortcuts.tsx:127` and `shell/command-palette.tsx:46`. Update the tests listed at `navigation.test.ts:8-36` and `app-shell.test.tsx:120,163,466,561,578,792,851` to use a head_of_delivery user, and update `src/test/permissions.ts`.
  - Run `npm run gen:api`.
- **Mockup:** `new-mockups/Presales Agent Design Spec (standalone).html`, the `<!-- REPORTS -->` block (offset ~511677), data at ~637900 (`VR`, `varRows`, `varKpis`).
  - KPI grid `repeat(3,1fr)` gap 16, tiles padding 20, value 28/36 semibold.
  - Table card radius 12; header "Estimate versus actual by Integration Type" with the subline "N closed Opportunities · hours".
  - Grid `minmax(0,1fr) 90px 90px 220px minmax(0,1fr)`, head row `surface2` 12px, row pad `calc(var(--rowpad)+6px) 20px`.
  - Bar: 8px track, centre tick at 50%, width `min(50,|p|*0.6)`%, 64px right-aligned percent.
  - Info strip: `primary-t` background, radius 10.

## Tasks & Acceptance

**Execution:**
- [ ] Migration 0055 + `tests/test_reporting_views.py` -- views, grants, write-denied test, row shape for planned, Unplanned and multi-IT Actuals -- the reporting layer.
- [ ] `identity` action + category, seed, `opportunities.public` visibility helper -- access.
- [ ] `reporting` module (application, api, importlinter, main_api) + `tests/test_reporting_api.py` -- the I/O matrix, 403 for delivery_manager, presales_engineer and pm_reviewer, each group_by, each filter, the milestone toggle, and a perf test seeding 200 delivered Opportunities that asserts P95 < 500 ms over 20 calls per grouping.
- [ ] Web nav gating + test updates -- Reports visible only with the permission.
- [ ] Web Reports page, sub-tabs, KPIs, table (expand, sort), filters, empty state + vitest/axe tests -- per mockup.

**Acceptance Criteria:**
- Given the Head of Delivery, when they press `g r`, then Reports opens on Estimate vs actual with the KPIs and the grouped table, and expanding a group lists its Opportunities with "v3" and the Baseline marker.
- Given a presales engineer, when the shell renders, then Reports is absent from the sidebar, the palette and `g r`, and `/reports` shows "No access".
- Given group-by is set to Cause, when the page reloads, then the URL keeps the grouping and filters.

## Implementation Notes

- **Line labels follow section, then position.** The Code Map's `row_number() OVER (PARTITION BY version_id ORDER BY position)` numbers lines out of the order the Actuals tab shows them, because the Estimate grid orders by section (`estimates.domain.Section`: functional, integration, data, security, non-functional, commercial) and then position. The view orders by `(section rank, position, id)` instead. It computes each Actual's label with a correlated count over its own version's lines, so it doesn't number every Estimate line. Unplanned work has no line and no label.
- **Writes to the views fail with "cannot insert into view", not "permission denied".** Both views join several tables, so Postgres rejects INSERT, UPDATE and DELETE as non-updatable before it checks privileges. The I/O matrix's "permission denied" row is therefore unreachable. The grants are still SELECT only, with INSERT, UPDATE, DELETE and TRUNCATE revoked. `test_psa_app_may_only_select` asserts that with `has_table_privilege`, and also checks that each write raises.
- **The `g r` shortcut is gated.** `shell/keyboard-shortcuts.tsx` matched key sequences against every shortcut, not only the user's, so `g r` still opened `/reports` without `reporting.report.read`. It now matches only the shortcuts `shortcutsFor(permissions)` (`lib/shortcuts.ts`) returns for the user, the same list the help dialog shows. Tests that press `g r` sign in a Head of Delivery.
- **`KpiTile` is extracted** from `opportunities/overview-summary.tsx` into `components/ui/kpi-tile.tsx`. The Overview and Reports > Estimate vs actual both use it, and the Overview's markup is unchanged.
- **Performance:** each request runs one SQL statement. The view is read once into materialized CTEs, which feed the KPIs, groups, failed-Assumption counts, calibration counts and filter options. Catalogue names and the Baseline are looked up through indexes per row instead of scanning every entry first.
- **Page tests:** `/reports` now loads the report, so `app/page.test.tsx` checks the generic shell behaviour on `/reports/pipeline`. `/reports` has its own tests in `app/reports/page.test.tsx`: the Head of Delivery, No access, a 403 from the API, an API failure, and URL parameters reaching the API.

## Spec Change Log

## Review Triage Log

## Design Notes

- **Group percent:** `(Σact − Σest) / Σest` over the group's rows. Main cause is the most frequent non-null cause, with ties going to the larger summed |variance|, then alphabetical.
- **Product grouping:** product is `products text[]`, so a multi-product Opportunity appears in each product group, as a multi-IT Actual does. KPIs are computed over distinct rows.
- **Scope of rows:** every readable Opportunity with Actuals is included. The date-range filter applies to `closed_at`, so it excludes Opportunities that aren't closed.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_reporting_* tests/test_architecture.py tests/test_actuals_* -q` -- expected: pass
- `cd backend && uv run lint-imports && uv run ruff check . && uv run mypy app` -- expected: clean
- `cd web && npm run gen:api && npm run typecheck && npm test -- reports navigation app-shell && npm run lint` -- expected: pass

**Manual checks:**
- Screenshot `/reports` as the Head of Delivery and compare it side by side with the mockup's Reports screen.
