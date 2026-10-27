# Epic 10 Context: Actuals and delivery reporting

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Close the estimation loop. Delivery managers record Actuals (effort, duration, cost) against each Baseline Estimate line with a variance cause, by hand or by file import. The Head of Delivery sees estimate-vs-actual variance across delivered work and can trace an overrun back to the Assumption that failed and who accepted it, without asking anyone. The epic also records won or lost outcomes, which set retention dates. A controlled purge job enforces those dates, and a Pipeline report shows where the proposal workload sits. This is the data foundation for the estimate-accuracy success metric (Baseline within ±15% of Actuals) and for Calibration in Release 4.

## Stories

- Story 10.1: Record Actuals per Estimate line
- Story 10.2: Import Actuals from a file
- Story 10.3: Variance reporting views and the Reports table
- Story 10.4: Drill down from variance to the failed Assumption
- Story 10.5: Record the Opportunity outcome and retention dates
- Story 10.6: Controlled retention purge
- Story 10.7: Pipeline report

## Requirements & Constraints

- Actuals are recorded per Baseline Estimate line, or as **Unplanned work** with no line. Unplanned work needs an Integration Type or Work Package and a cause of `scope_change`, `unknown_requirement` or `other`, and it counts in the total variance. Kinds are `milestone | final`.
- Variance causes are a fixed set: `unknown_requirement, integration_complexity, customer_delay, scope_change, estimation_error, other`. A final Actual that differs from the estimate needs a cause, and `other` also needs a note.
- Failed Assumption references may point only to Assumptions in the same Baseline version's register, and each one is stored with its Assumption version.
- Actuals stay tied to the version they were recorded against, even after a later version becomes the Baseline.
- Roles: only delivery managers with access write Actuals. Everyone else with access gets a read-only view, and the API returns 403 on writes. Reports (all sub-tabs) are visible only to the Head of Delivery and the platform administrator; other roles, delivery managers included, don't see it and get 403. The Head of Delivery has read-only drill-down access to Opportunities where they aren't a collaborator.
- Performance: Reports and Pipeline APIs respond within 500 ms at P95, tested with seeded data (200 delivered Opportunities for Reports, 500 for Pipeline).
- Retention: a lost Opportunity is kept for 3 years from when the outcome was recorded. A won one is kept until contract end plus 7 years. Open Opportunities have no retention date and are never purged. The trace is append-only; only the purge job deletes anything.
- Privacy: no customer content in logs or in purge audit events. Exports (such as the import template) are audited with `opportunity_id`.
- Not a CRM, PSA or project-management tool. The Pipeline report shows only platform-derived status and dates and never touches CRM stages. R1 has no timesheet integration.
- Accessibility: WCAG 2.1 AA, with axe in CI. Variance direction is shown by a `+`/`−` sign and a label, never by colour alone. Bars carry their values as text.

## Technical Decisions

- **Ownership:** a new `actuals` module owns `actuals_actuals`. It reads Estimate data only through `estimates.public`. Outcome fields (`outcome`, `outcome_recorded_at`, `contract_end_date`) live in `opportunities` and change only through `opportunities.record_outcome` and `opportunities.update_contract_end_date`. Each table has exactly one owning module, and cross-module access goes through `application/public.py`.
- **Single mutation path:** command → `identity.authorize` → domain checks → `row_version`/`If-Match` (412 on a stale write) → write plus `platform.trace.append` in one Unit of Work. Action names follow `<module>.<entity>.<verb>` (for example `actuals.actual.record`). Trace events include `actuals.actual.recorded`, `.corrected`, `actuals.delivery.closed`, `actuals.import.completed`, `opportunities.opportunity.closed` and `platform.purge.completed`. Each event type has one payload model in the trace catalogue.
- **Corrections** create a new Actual version with a required reason. History is never overwritten.
- **Deterministic numbers:** variance (hours, cost, percent) is computed in SQL or domain code, never in the browser or by an LLM. The retention-date calculation is a pure domain function with unit tests. Money is stored as integer minor units plus an ISO-4217 currency; effort is `numeric(10,1)` person-hours.
- **Import:** uploads go through `platform.storage` (size limit, extension allowlist, magic-byte check, content-addressed by SHA-256). The file is parsed by an `actuals.import_file` job in the worker sandbox, never in `api`. The user sees a preview before anything is written, then the import is applied all-or-nothing in one Unit of Work using the same rules as manual entry. A repeated SHA-256 triggers a warning. The template download uses a short-lived HMAC-signed URL.
- **Reporting:** read-only `reporting_*` views (`reporting_estimate_vs_actual`, `reporting_failed_assumptions`) may join across modules. The app DB role has SELECT only, proven by a test. Queries filter through `identity.public` before they aggregate.
- **Pipeline** is a derived read model. It reuses `opportunities.public.status_summary()`, the single status query, with a test that proves the report and the Opportunity list agree. Lifecycle status is derived, never stored. The new `delivered` and `closed` statuses come from Actuals closure and the recorded outcome.
- **Purge:** a separate `psa_purge` DB role with DELETE rights, whose credentials are in their own sops secret and available only to the worker's purge job. The daily `platform.purge` schedule purges each Opportunity in its own transaction. It runs each module's registered `<module>/adapters/purge.py` step in dependency order, covering trace rows, `workflows_progress`, `platform_model_calls` and the LangGraph checkpoint threads. Files are reference-counted, and a blob is deleted only when its count reaches zero. Shared data (Knowledge, catalogue, registry, users) is never touched. Failures roll back per Opportunity and retry with backoff; a job that exhausts its retries goes `dead` and sends the email alert. The restore runbook must require a purge run after any restore.
- REST under `/api/v1` with problem+json errors and the generated TS client (run `npm run gen:api` after adding endpoints). Live updates come over the per-Opportunity SSE stream.

## UX & Interaction Patterns

- **Actuals tab (tab `8`):** the header reads "Actuals" with the subtitle "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line." Actions are **Import from file** and **Save Actuals**. Table columns: Line, Estimate h, Actual h (editable), Variance (for example "+5.0 h (13.9%)"; **amber when over, green when under**), Variance cause. It is sortable by variance. Unrecorded lines show "—" and "Not recorded" and are excluded from variance. Footnote: "Empty lines are not counted in variance. Each change is added to the Trace." Use tabular figures.
- **Actuals states:** with no Baseline, show "No Baseline yet. Actuals are recorded against the Baseline." With no Actuals, show the empty-tab card "No Actuals recorded" / "Record hours per Estimate line with a variance cause once delivery starts." / **Record Actuals**. **Close delivery** is disabled with a count message (for example "4 lines have no final Actual"). Version mismatch shows "Actuals recorded against v3; the current Baseline is v5". Other states: Parse failed with Retry, and the 412 alert with Reload and View diff.
- **Reports (`g r`):** sub-tabs Estimate vs actual, Pipeline, and Cost and usage (Cost and usage is built in Epic 7). Estimate vs actual shows KPI tiles (closed Opportunities, total variance, failed Assumptions) and a table grouped by Integration Type: Opportunity count, Estimate h, Actual h, a diverging variance bar with percent (**red only above +10%**, neutral within range, green under), a main-cause link and the failed Assumption count. Groups expand into their Opportunities. A group-by control, filters, and a toggle (final Actuals only by default, or including milestones) refine the view. Sortable headers are announced to screen readers, and the Baseline marker appears next to versions. Empty state: "No Actuals recorded yet. Delivery managers record them in an Opportunity's Actuals tab." The R4 Calibration note: "Calibration is not available yet. Suggestions need at least 5 closed projects per Integration Type."
- The two variance colour rules (amber per line on Actuals, red above +10% on Reports) are deliberate. Don't unify them.
- **Drill-down (Flow UJ-5):** Reports row → Actuals tab sorted by variance, with the Integration Type filter kept → select a line, and the Inspector lists the failed Assumptions (Condition or Contingency icon, wording or amount, who accepted it and when, Evidence chips) → **Open in Trace**, filtered to that Assumption. The target is three navigations.
- **Pipeline:** KPI tiles, "Opportunities by status" as bars with counts as text, and a "Due soon" table. Charts are bars only.
- **Overview outcome copy:** "Lost — data kept until {date}"; "Won — data kept until contract end plus 7 years ({date})".
- **Admin → Retention:** a read-only list of Opportunities due for purge in the next 30 days (UUID, outcome, retention date) and recent purge events. There is no delete-on-demand action.
- The visual reference is the newest standalone design spec in `new-mockups/`, which supersedes `mockups/`. Build on the redesign tokens and primitives from Epic 17.

## Cross-Story Dependencies

- Needs the Baseline (`estimates_baselines`, Story 9.7), the Assumptions Register (Story 8.5), the catalogue IDs (Story 3.1) and Decision Trace filtering by Assumption (Stories 9.8 and 9.9).
- 10.1 comes before 10.2, 10.3 and 10.4. 10.3 comes before 10.4. 10.4 extends the Story 9.10 end-to-end fixture with Actuals and a failed Condition.
- 10.5 comes before 10.6, because the purge uses 10.5's retention dates.
- 10.3 hosts the Reports shell that 10.7 and Cost and usage (Story 7.5) plug into.
- 10.7 depends on Story 8.6 and the single Opportunity status query. It is planned last in R1, after 10.1, because it adds no estimate-quality value.
- Release 4 Calibration and the past-project Evidence tool (`actuals.find_similar_lines`) will read this epic's data.
