# Epic 10 Context: Actuals and delivery reporting

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Close the loop between estimating and delivery. Delivery managers record Actuals (hours, duration, cost) against each Baseline Estimate line with a variance cause, by hand or by file import. The Head of Delivery sees in Reports where estimates are consistently wrong and drills from an overrun to the Assumption that failed and its decision chain. The epic also records each Opportunity's outcome (won/lost), which fixes its retention date, and adds the controlled, privileged purge job that is the only thing allowed to delete Opportunity data once retention ends. It finishes with the Pipeline report. The result is a reliable estimate-vs-delivery history that later calibration depends on, while meeting deletion duties without weakening the append-only audit trail.

## Stories

- Story 10.1: Record Actuals per Estimate line
- Story 10.2: Import Actuals from a file
- Story 10.3: Variance reporting views and the Reports table
- Story 10.4: Drill down from variance to the failed Assumption
- Story 10.5: Record the Opportunity outcome and retention dates
- Story 10.6: Controlled retention purge
- Story 10.7: Pipeline report

## Requirements & Constraints

- Actuals are per Baseline Estimate line (or unplanned work tagged with an Integration Type or Work Package), with a variance cause from `unknown_requirement, integration_complexity, customer_delay, scope_change, estimation_error, other`. A final Actual differing from the estimate needs a cause; `other` also needs a note. Failed-Assumption links come only from the same Baseline version. Actuals reference versioned catalogue IDs.
- Reporting groups/filters by Opportunity, product, Integration Type, Work Package and cause, and drills to failed Assumptions and their Decision Trace chain. Pipeline uses platform data only and never touches CRM stages.
- Roles: delivery managers write Actuals; presales engineers, reviewers and sales reps are read-only (403 on writes). Reports (all sub-tabs) is for Head of Delivery and platform administrator only (others 403). Head of Delivery gets read-only policy access to Actuals, Estimate and Trace on Opportunities they don't collaborate on.
- Retention: lost = `outcome_recorded_at` + 3 years; won = `contract_end_date` + 7 years; open Opportunities have no retention date and are never purged.
- Purge: only the scheduled purge job deletes; purge audit events and logs carry no customer name or content; one Opportunity's failure never blocks the others; reruns are safe. Shared data (Knowledge Sources, catalogue, registry, users) is never touched.
- Backups have 35-day retention; purged data ages out of them. After any restore, the purge must run before users are let back in.
- Performance: Reports and Pipeline APIs ≤ 500 ms P95 (200 delivered / 500 Opportunities). File exports are audited with `opportunity_id` set.
- Accessibility: WCAG 2.1 AA with axe in CI; variance/status never by colour alone (`+`/`−` sign, label, counts as text).

## Technical Decisions

- **Ownership:** `actuals` owns `actuals_actuals` (versioned; only `is_current` changes) and `actuals_deliveries` (insert-only). `opportunities` owns `outcome`, `outcome_recorded_at`, `contract_end_date`. `platform` owns trace events, jobs, schedules, model calls and file metadata. Cross-module access only via `application/public.py`.
- **Mutation path:** command inside one Unit of Work: `identity.authorize` → domain rules → `row_version`/If-Match (412) → write → `platform.trace.append`. Actions `<module>.<entity>.<verb>`, trace events `<module>.<entity>.<past_tense_verb>`, job types `<module>.<verb>`. Each event type needs a Pydantic payload model in `platform/trace/catalogue.py`. The purge job is the single sanctioned exception to "no direct DELETE on business tables".
- **Authorization:** roles and permissions live in Auth0 RBAC; the API authorizes from the token's `permissions` and roles claims only (missing claim grants nothing). Every new action name must also exist as an Auth0 permission. Opportunity membership and owner/collaborator grants stay in `identity/domain/policy.py`. `identity_user_roles` is a display cache, never used for authorization.
- **Trace events:** `actuals.actual.recorded`, `actuals.actual.corrected`, `actuals.delivery.closed`, `actuals.import.completed`, `opportunities.opportunity.closed`, `platform.purge.completed`.
- **Deterministic code:** variance arithmetic and retention-date computation are SQL or pure domain code with unit tests, never browser or LLM.
- **Figures:** effort person-hours `numeric(10,1)`; cost integer minor units + ISO-4217; duration in working days. Failed-Assumption references store the Assumption version.
- **Files/import:** `platform.storage` (size limit enforced in the API, extension allowlist, magic bytes), stored by SHA-256, immutable and reference-counted. Parsing is an `actuals.import_file` worker job in the sandbox; preview first; apply is all-or-nothing in one Unit of Work; duplicate files detected by hash. Downloads use short-lived HMAC-signed URLs.
- **Reporting:** read-only `reporting_estimate_vs_actual` and `reporting_failed_assumptions` views may join across modules; app role has SELECT only (test proves writes fail); queries filter through `identity.public` before aggregating. Pipeline reuses `opportunities.public.status_summary()` and never re-derives status (test proves list and report agree).
- **Purge (10.6):**
  - Separate `psa_purge` DB role with DELETE rights; credentials in their own sops/age-encrypted secret, exposed only to the worker's purge job (config via `PSA_`-prefixed settings in `platform.config`). The `api` process and other jobs cannot use it. A test proves the app role still cannot DELETE (or UPDATE) `platform_trace_events`.
  - Daily `platform.purge` job from `platform_schedules`, registered in `platform/jobs/registry.py` with retry policy and backoff; exhausted retries → `dead` → email alert.
  - Selects Opportunities whose retention date has passed; purges each in its own transaction on the privileged connection by running every module's registered `<module>/adapters/purge.py` step in dependency order. Covers module rows, that Opportunity's trace rows, `workflows_progress`, its `platform_model_calls` rows (linked via run/task), and its LangGraph checkpoint threads in the `orchestration_checkpoints` schema (`thread_id` = `workflow_run_id`).
  - File refcounts are decremented; a blob is deleted only at zero, so blobs shared with another Opportunity stay.
  - On commit, append `platform.purge.completed` with `opportunity_id = null`, the purged Opportunity UUID, retention rule applied, per-module row counts and files deleted; no customer content.
  - `ops/runbooks/restore.md` must state the 35-day backup age-out and that purge runs after any restore, before users return.
- **API:** REST `/api/v1`, problem+json with stable `code`. Regenerate the TS client (`npm run gen:api`) after adding endpoints.

## UX & Interaction Patterns

- Visual reference: the 2026-10-21 redesign prototype (`imports/presales-agent-design-spec-standalone-v2.html`); DESIGN.md and EXPERIENCE.md win on conflict; older `mockups/` are superseded. Build on Epic 17 tokens and primitives (KPI tiles, tint-filled pills, empty-tab cards).
- **Actuals tab (`9`):** "Actuals" header with subline, **Import from file** and **Save Actuals**; columns Line, Estimate h, Actual h (editable), Variance (amber over, green under, e.g. "+5.0 h (13.9%)"), Variance cause; tabular figures; unrecorded lines "—" / "Not recorded", excluded from variance. States: no Baseline, empty-tab card "No Actuals recorded" / **Record Actuals**, 412 alert, Parse failed + **Retry**, version-mismatch note, Close delivery disabled with missing-final count.
- **Reports (`g r`):** sub-tabs Estimate vs actual, Pipeline, Cost and usage. Variance table grouped by Integration Type with diverging bar + percent (red only above +10%), main-cause link, failed-Assumption count, expandable groups, group-by/filters, final-only toggle, Baseline marker. Bars only, values as text.
- **Drill-down:** Reports row → Actuals tab (sorted by variance, filter kept) → Inspector failed Assumptions → **Open in Trace** filtered to the Assumption: three navigations.
- **Overview outcome lines:** "Lost — data kept until {date}" and "Won — data kept until contract end plus 7 years ({date})".
- **Admin → Retention (new Admin sub-tab):** read-only list of Opportunities due for purge in the next 30 days (UUID, outcome, retention date) and recent purge events. No on-demand delete action.

## Cross-Story Dependencies

- Requires Baselines and the Assumptions Register (Epics 8–9), the catalogue (Epic 3) and the Trace chain (Story 9.9); the 10.4 end-to-end test extends the Story 9.10 fixture.
- Epic 17 Story 17.1 (tokens and primitives) precedes any new UI here.
- Order: 10.1 before 10.2–10.4; 10.3 before 10.4; 10.5 (retention date) before 10.6. The Cost and usage sub-tab comes from Story 7.5.
- 10.6 needs a purge step from every module that holds Opportunity data, plus the job/schedule contract, storage refcounts and the email alert channel.
- 10.7 depends on Story 8.6 and the single status query; sequenced last in Release 1.
