# Epic 10 Context: Actuals and delivery reporting

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Close the loop between estimating and delivery. Delivery managers record Actuals (hours, duration, cost) against each Baseline Estimate line with a variance cause, by hand or by file import. The Head of Delivery then sees where estimates are consistently wrong in Reports and drills from an overrun to the Assumption that failed and the decision chain behind it. The epic also records each Opportunity's outcome (won/lost), which sets its retention date, and adds the controlled purge job that deletes data once retention ends. It finishes with the Pipeline report. The result is a reliable estimate-vs-delivery history that later calibration and learning features depend on.

## Stories

- Story 10.1: Record Actuals per Estimate line
- Story 10.2: Import Actuals from a file
- Story 10.3: Variance reporting views and the Reports table
- Story 10.4: Drill down from variance to the failed Assumption
- Story 10.5: Record the Opportunity outcome and retention dates
- Story 10.6: Controlled retention purge
- Story 10.7: Pipeline report

## Requirements & Constraints

- Actuals are recorded per Baseline Estimate line (or as unplanned work tagged with an Integration Type or Work Package), with a variance cause from a fixed set: `unknown_requirement, integration_complexity, customer_delay, scope_change, estimation_error, other`. A final Actual that differs from the estimate needs a cause, and `other` also needs a note. Actuals can link failed Assumptions from the same Baseline version only.
- Actuals and Estimate lines reference the versioned Integration Type / Work Package catalogue IDs.
- Estimate-vs-actual reporting groups and filters by Opportunity, product, Integration Type, Work Package and cause, and drills down to failed Assumptions and their Decision Trace chain.
- Pipeline report: Opportunities by derived status plus a "due soon" list, from platform data only. It never reads or writes CRM pipeline stages (the product is not a CRM).
- Roles: delivery managers write Actuals. Presales engineers, reviewers and sales reps get read-only access, and the API returns 403 on their writes. Reports (all sub-tabs) is visible only to the Head of Delivery and the platform administrator, and other roles get 403. The Head of Delivery has read-only policy access to the Actuals, Estimate and Trace tabs of Opportunities they don't collaborate on.
- Retention: lost Opportunities are kept for 3 years after the outcome is recorded, and won ones until contract end plus 7 years. Open Opportunities are never purged. The trace stays append-only, and only the purge job deletes.
- Performance: Reports and Pipeline APIs respond within 500 ms P95 (Reports on 200 delivered Opportunities, Pipeline on 500).
- Privacy: no customer content in purge audit events or logs, and file exports are audited with `opportunity_id` set.
- Accessibility: WCAG 2.1 AA with axe in CI. Variance and status are never shown by colour alone: use a `+`/`−` sign and a label, with counts as text.

## Technical Decisions

- **Ownership:** the `actuals` module owns `actuals_actuals` (versioned, where only `is_current` changes) and `actuals_deliveries` (insert-only Close delivery). The `opportunities` module owns outcome, `outcome_recorded_at` and `contract_end_date`. Other modules' data is read only through their `public.py`.
- **Mutation path:** every change is a command inside a Unit of Work: `identity.authorize`, then domain rules, then the `row_version`/If-Match check (412 on stale), then the write, then `platform.trace.append`, all in the same transaction. Action names follow `<module>.<entity>.<verb>` (e.g. `actuals.actual.record`). Corrections create a new version with a required reason.
- **Trace events:** `actuals.actual.recorded`, `actuals.actual.corrected`, `actuals.delivery.closed`, `actuals.import.completed`, `opportunities.opportunity.closed`, and `platform.purge.completed` (with `opportunity_id = null` and no customer content).
- **Deterministic code:** all variance arithmetic and retention-date computation live in SQL or pure domain code with unit tests, never in the browser or an LLM.
- **Money and figures:** effort is in person-hours `numeric(10,1)`, cost in integer minor units plus an ISO-4217 currency, and duration in working days.
- **Evidence:** failed-Assumption references are stored with the Assumption version.
- **Import:** uploads go through `platform.storage` (size limit, extension allowlist, magic bytes, content-addressed by SHA-256, reference-counted). Parsing runs as an `actuals.import_file` worker job in the sandbox, never in the API. A preview is shown before anything is written. The apply step writes in one Unit of Work and is all-or-nothing, and a re-uploaded file is detected by its hash. Templates and exports use short-lived signed URLs.
- **Reporting:** read-only `reporting_*` views (`reporting_estimate_vs_actual`, `reporting_failed_assumptions`) may join across modules. The app DB role has SELECT only on them, with a test proving writes fail. Queries filter through `identity.public` before aggregating. Reports, Pipeline and Cost and usage are derived read models.
- **Pipeline:** reuses the single Opportunity status query via `opportunities.public.status_summary()` and never duplicates the status derivation (a test proves the list and the report agree).
- **Purge:** a separate `psa_purge` DB role with DELETE rights, with credentials in their own sops-encrypted secret available only to the worker's purge job. The daily `platform.purge` schedule purges each Opportunity in its own transaction by running each module's `<module>/adapters/purge.py` in dependency order. This covers module rows, trace rows, `workflows_progress`, `platform_model_calls` and the LangGraph checkpoints in `orchestration_checkpoints`. Shared data is never touched, blobs are deleted only when their reference count reaches 0, the job retries with backoff and becomes dead with an email alert, and it is safe to rerun. The restore runbook must say to run the purge after any restore.
- **API:** REST under `/api/v1` with problem+json errors. Regenerate the TS client (`npm run gen:api`) after adding endpoints, especially for 10.7.

## UX & Interaction Patterns

- **Design source:** the visual reference is the 2026-10-21 redesign prototype in `ux-designs/.../new-mockups/Presales Agent Design Spec (standalone).html`, which is identical to `imports/presales-agent-design-spec-standalone-v2.html`. It includes the Actuals entry screen and the Reports sub-tabs. The older `mockups/` HTML files are superseded and kept for layout history only. DESIGN.md and EXPERIENCE.md win on conflict. Build on the Epic 17 tokens and primitives (Inter 14px, tint-filled pills, KPI tiles, empty-tab cards).
- **Actuals tab (`9`):** header "Actuals" with the subline "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line." plus **Import from file** and **Save Actuals**. The table columns are Line, Estimate h, Actual h (editable), Variance (e.g. "+5.0 h (13.9%)": amber when over, green when under) and Variance cause, using tabular figures. Unrecorded lines read "—" / "Not recorded" and are excluded from variance. The table is sortable by variance. Footnote: "Empty lines are not counted in variance. Each change is added to the Trace." Version history and failed Assumptions appear in the Inspector.
- **States:** with no Baseline the tab reads "No Baseline yet. Actuals are recorded against the Baseline." With no Actuals it shows the empty-tab card "No Actuals recorded" / "Record hours per Estimate line with a variance cause once delivery starts." / **Record Actuals**. Also cover the 412 concurrent-edit alert, the Parse failed upload row with **Retry**, the version-mismatch note ("Actuals recorded against v3; the current Baseline is v5") and Close delivery disabled with a count of lines missing a final Actual.
- **Reports (`g r`):** sub-tabs Estimate vs actual, Pipeline and Cost and usage. Estimate vs actual shows KPIs (closed Opportunities, total variance, failed Assumptions) and a table grouped by Integration Type with a diverging variance bar plus percent (red above +10%), a main-cause link drilling into the Actuals tab, a failed-Assumption count, and expandable groups. It has group-by and filter controls, a final-only / include-milestones toggle and the Baseline marker. Charts are bars only, with values as text. Empty state: "No Actuals recorded yet. Delivery managers record them in an Opportunity's Actuals tab."
- **Two colour rules, on purpose:** Actuals is amber whenever a line is over, because it is an entry screen. Reports is red only above +10%, because it is an aggregate view.
- **Drill-down:** from a Reports row to the Actuals tab (sorted by variance, filter kept), to the Inspector's failed Assumptions (Condition or Contingency icon, accepted-by, Evidence chips), to **Open in Trace** filtered to that Assumption. This should take three navigations.
- **Overview:** shows the outcome lines "Lost — data kept until {date}" and "Won — data kept until contract end plus 7 years ({date})".
- **Admin → Retention:** a read-only list of Opportunities due for purge in the next 30 days and recent purge events, with no on-demand delete.

## Cross-Story Dependencies

- Requires Baselines and the Assumptions Register (Epics 8–9), the catalogue (Epic 3) and the Trace chain (Story 9.9). The 10.4 end-to-end test extends the Story 9.10 fixture.
- Epic 17 Story 17.1 (tokens and primitives) must precede any new UI in this epic.
- Order within the epic: 10.1 comes before 10.2–10.4, 10.3 before 10.4, and 10.5 before 10.6. The Cost and usage sub-tab comes from Story 7.5.
- Story 10.7 depends on Story 8.6 and the single status query. It is sequenced last in Release 1, after 8.6, the 9.x stories and 10.1.
