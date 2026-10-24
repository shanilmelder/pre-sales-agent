# Epic 8 Context: Estimate and Assumptions Register

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the presales engineer one standard Estimate whose numbers are always calculated by the platform, never by a model. Every open Gap, Unknown or Finding becomes an explicit Condition, Contingency or Risk with a named accepting person, so nothing is quietly assumed away. One live Submission Blockers gate counts down to zero before an Estimate Version can be submitted, and the Overview shows where the submission stands. Submitted versions are immutable and can be compared. The Estimate, Assumptions Register and Clarification Questions export to .xlsx and .docx for today's proposal process. This epic feeds Review and Baseline (Epic 9) and Actuals (Epic 10).

## Stories

- Story 8.1: Estimate Versions, lines and deterministic arithmetic
- Story 8.2: Estimate grid with in-place draft edits
- Story 8.3: Draft an Estimate from Assessments
- Story 8.4: Convert Gaps and Unknowns into Assumptions or Risks
- Story 8.5: Assumptions Register and Risks
- Story 8.6: Submission blockers gate and Estimate submission
- Story 8.7: New Estimate Versions and version comparison
- Story 8.8: Export the Estimate, Assumptions Register and Clarification Questions
- Story 8.9: Overview recomposition

## Requirements & Constraints

- **Standard structure.** One versioned template (sections, columns, roles) agreed with the Head of Delivery, with its version recorded on each Estimate Version. Every line references an active catalogue Integration Type or Work Package. A retired entry stays valid on lines that already use it but can't be picked for a new one.
- **Assumptions Register.** Each Assumption is a Condition (proposal-ready wording) or a Contingency (an amount in hours or money). It has exactly one origin (Gap, Unknown, or Finding plus its Assessment version) and records who accepted it and when. The accepting person must be an Opportunity member with the presales engineer or commercial role. Editing an accepted Assumption clears the acceptance.
- **Unknowns cannot vanish.** A version can't be submitted while any Gap or Unknown is open, any Assumption is unaccepted, any Conflict is open, or any critical Finding has no override. Converting a Finding leaves the Finding's status unchanged.
- **Versioning.** A draft is edited in place: each edit needs a reason, saves with `row_version` and is traced with before and after values. Labels are whole numbers (v1, v2, v3). Submitted, Baseline and superseded versions are read-only. A new version comes from an assessment rerun, a Challenge, or an explicit **New version** with a reason. Only one draft exists at a time.
- **Concurrency.** A stale save returns 412 and is never applied silently.
- **Access.** Sales representatives get 403 on every Estimate, Assumption and export write. Users without access get the 404-equivalent.
- **Exports** are audited, put no customer content in logs, and download through short-lived signed URLs issued after authorization.
- **Accessibility.** WCAG 2.1 AA with axe in CI. The grid supports arrow keys with announced headers. Status never relies on colour alone. Blocker count changes are announced politely.

## Technical Decisions

- **Ownership.** `estimates` owns Estimate, Estimate Version, line, Assumption, Risk and later Baseline (`estimates_*` tables). `gaps` owns Gaps and Unknowns, `conflicts` owns Conflicts, and `assessments` owns Findings and FindingOverride. Cross-module access goes only through each module's `public.py`.
- **Mutation path.** Commands run in the Unit of Work, authorize with `estimates.<entity>.<verb>` actions (seeded as Auth0 permissions; authorization reads only the token claims plus Opportunity membership), use If-Match/`row_version`, and append `estimates.<entity>.<past_tense_verb>` trace events with catalogued payloads in the same transaction. Errors are problem+json with typed codes (`estimates.line.catalogue_required`, `estimates.version.blocked`, `estimates.version.immutable`).
- **Deterministic arithmetic.** Pure domain functions calculate line totals, per-role effort, Contingency sums, subtotals and grand totals, backed by property-based tests. Effort is `numeric(10,1)` person-hours. Role mix sums to 100, and per-role hours use largest-remainder rounding to 0.1 h. Money is integer minor units plus ISO-4217. Overall duration is a version field and is never a sum. No endpoint accepts a total. A line's Contingency cell is derived only from its linked Contingencies.
- **Status.** `draft, submitted, in_review, approved, rejected, superseded`. Epic 8 implements draft, submitted and superseded. Submitting a newer version supersedes earlier non-Baseline submitted versions in the same Unit of Work.
- **Single blocker check.** `estimates.get_submission_blockers(version)` is the only code that decides submittability. It returns typed items with subject links: open Gaps and Unknowns, unaccepted Assumptions, open Conflicts, critical Findings without an override, and pending Review Requests (always empty until Epic 9). The Overview card, header buttons, tab badge, pipeline steps and opportunity-list blocker count all read from it.
- **Serialisation.** `pg_advisory_xact_lock(opportunity_id)` is taken by conversion, Accept and submit. Submit re-runs the blocker check inside the lock and rejects with `estimates.version.blocked` if anything appeared.
- **Conversion** (`convert_to_assumption` / `convert_to_risk`) calls `gaps.mark_converted` in the same Unit of Work: both commit or neither does.
- **Drafting** runs as the final workflow node through `estimates.draft_from_assessments` with a `node:` idempotency key. Mapping is rule-based. Resolved Conflicts supply the chosen value, and open ones mark the line.
- **Export** is a worker job (`estimates.export_version`) that writes through `platform.storage`. It reads Clarification Questions through `gaps` public.
- **Live updates** go over the per-Opportunity SSE stream. A resolved blocker's trace event drives the card, badge and count refresh.

## UX & Interaction Patterns

The visual reference is the redesign v2 prototype (`imports/presales-agent-design-spec-standalone-v2.html`, identical to `new-mockups/`). Where it and the spines differ, the spines win, and the older `mockups/` are superseded. Since 2026-10-23 the shell has no top bar. Pages use a header band, and control borders (`border-strong`) use the mockup's lighter values. Build on the existing tokens and primitives from Epic 17. Use one primary action per view.

- **Opportunity header (Story 8.6 adds these; Story 17.4b deliberately left them out).** **Submit** is a secondary button with `aria-disabled` and its reason stated nearby while blockers exist. At zero it becomes the primary button and opens a confirm dialog ("Submitted versions can't be edited"). A primary **Resolve N blockers** button jumps to the Overview and is hidden when ready.
- **Submission Blockers card (Overview).** The card header is titled "Submission blockers" and has a count pill: blocker tint "N to submit · M to Baseline", or resolved tint "0 blockers" when ready. Two eyebrow groups follow:
  - **"Blockers to submit · N".** Rows sit on the blocker tint with an alert icon, a bold title, a meta line and a link-style action on the right (Open Gaps, Resolve, Open Estimate).
  - **"Blockers to Baseline · M".** Rows have a plain surface, an amber clock icon and no action. Until Epic 9 this group reads "No Review Requests yet".

  When both groups are empty, the card shows a centred resolved check-circle with "0 blockers — ready to submit" and "Both gates are clear. Submit is now the primary action." Rows leave live over SSE, the Estimate tab badge updates, and the polite live region announces the new count. Copy is specific ("3 blockers before you can submit").
- **Estimate tab.**
  - **Grid.** Tabular figures, right-aligned numbers, sticky header and totals, and a left rule before Contingency. Cells are read-only. A draft line is edited in the Inspector's **Edit line** section (Engineer effort and a required reason). **Save change** stays disabled until a reason is typed, with the hint "Recorded in the Decision Trace. Earlier versions are unchanged." The section is hidden on read-only versions.
  - **Toolbar.** A segmented version switcher with a state pill per segment (Superseded, Baseline, Draft), a `v` list, a `d` diff using primary-tint plus `+`/`−` markers (never red or green) with a server-calculated summary, and **Export**.
  - **Version lifecycle card.** A read-only stepper (Draft, In review, Approved, Baseline) derived from status and the Baseline pointer, so `submitted` shows as Draft complete. It carries the sentence for the selected version.
- **Assumptions Register** sits below the grid. It groups Conditions (clipboard-check) and Contingencies (shield-plus, with the server-calculated total) and shows origin chips and accepted-by. Unaccepted rows use the blocker row treatment with a "not accepted" label and **Accept**. Risks have their own section. Everything is read-only on submitted versions.
- **Convert form** (Gap Inspector). A Condition/Contingency segmented control with help text and "Accepted by" defaulting to me. The button reads "Convert to Condition" or "Convert to Contingency".
- **States.**
  - Empty Estimate: the card "No Estimate yet" with only **Run assessment** (no Start blank).
  - Submitted: the "Submitted v3, 14 Oct" banner with **New version**.
  - Concurrent edit: the 412 inline alert "Not saved: this line changed (412)" with Reload and View diff.
  - Export failure: "Export failed: <reason>" with Retry.
- **Overview (Story 8.9).** The Overview runs top to bottom:
  1. Four KPI tiles: Requirements confirmed (n of total with a bar), Open Gaps by impact, Open Conflicts, and the current Estimate (hours, role split, source run).
  2. An 8-step vertical Submission pipeline card with resolved, blocker, agent and neutral nodes, one-line state and status pill per step, and the footer "2 of 8 steps complete · 3 steps blocked".
  3. Needs you.
  4. Submission Blockers.
  5. Recent activity with Open Trace.
  6. Latest agent decision.
  7. Agent run.

  The pipeline is a status tracker, never a forced order. Each step links to its tab, updates live and uses the blocker check's data. Requirement confirmation never blocks submission.
- **Divergences to respect.**
  - The prototype aggregates blocker rows per type ("3 open Gaps"). The stories ask for rows that name the type and subject and link straight to it. Agree on the shape in the 8.6 spec.
  - The prototype shows "1 Requirement not covered" with **Add line**, and Baseline rows that repeat draft Conflicts. Uncovered Requirements are not in the blocker check, and this is still an open question, so don't add that blocker type.
  - The spine's grid groups lines by category with a "Covers" column, while the stories use Integration Types and Work Packages. Follow the stories and template.

## Cross-Story Dependencies

- 8.1 (schema, template, arithmetic) underpins all stories. 8.3 adds the Assumption and Risk tables used by 8.4, 8.5, 8.6 and 8.8.
- 8.6 reads Gaps and Unknowns (Epic 4), Conflicts and critical Findings or overrides (Epics 5 and 6), and later Review Requests (Epic 9). 8.9 depends on 8.6 and ships after it. The header Submit and Resolve buttons from 17.4b wait on 8.6.
- 8.3 needs accepted Assessments with per-integration and Work Package effort (Epic 5), `workflows.start_run`, and resolved Conflicts (Epic 6). The catalogue comes from Epic 3, and the Convert form builds on the Epic 4 Gap Inspector.
- 8.7's supersede extends to Review Requests in Story 9.4. Baseline, `set_baseline`, Set Baseline and the in_review, approved and rejected transitions belong to Epic 9. Actuals belong to Epic 10.
