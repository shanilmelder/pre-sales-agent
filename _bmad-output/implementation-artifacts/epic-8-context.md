# Epic 8 Context: Estimate and Assumptions Register

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the presales engineer one standard, structured Estimate whose numbers are always calculated by the platform, never by a model. Every open Gap, Unknown or Finding is turned into an explicit Condition, Contingency or Risk with a named accepting person, so nothing is quietly assumed away. A single live Submission Blockers gate counts down to zero before an Estimate Version can be submitted. Versions are immutable once submitted and can be compared, and the Estimate, Assumptions Register and Clarification Questions export to .xlsx and .docx for today's proposal process. This is the core of the "estimate he can defend" journey and the input to Review, Baseline (Epic 9) and Actuals (Epic 10).

## Stories

- Story 8.1: Estimate Versions, lines and deterministic arithmetic
- Story 8.2: Estimate grid with inline editing
- Story 8.3: Draft an Estimate from Assessments
- Story 8.4: Convert Gaps and Unknowns into Assumptions or Risks
- Story 8.5: Assumptions Register and Risks
- Story 8.6: Submission blockers gate and Estimate submission
- Story 8.7: New Estimate Versions and version comparison
- Story 8.8: Export the Estimate, Assumptions Register and Clarification Questions

## Requirements & Constraints

- **Standard structure:** lines grouped by Integration Type and Work Package. Each line shows effort, role mix, duration, Contingency and its source Assessments. Every line must reference an active catalogue entry. Retired entries stay valid on existing lines but can't be picked for new ones. All Estimates use one versioned, configurable template (sections, columns, roles), agreed with the Head of Delivery. The template version is recorded on each Estimate Version.
- **Assumptions Register:** each Assumption is a Condition (with proposal-ready wording) or a Contingency (with an effort or money amount). Each has exactly one origin (Gap, Unknown, or Finding plus its Assessment version) and records who accepted it and when. A version can't be submitted while any Assumption has no accepting person. The accepting person must be an Opportunity member with the presales engineer or commercial role.
- **Unknowns cannot vanish:** submission is blocked while any Gap or Unknown is open. It must be answered, or converted to an Assumption or Risk. Converting a Finding leaves the Finding's own status unchanged, so a critical Finding still needs to be resolved or overridden.
- **Edits need a reason** and are traced. Submitted versions are immutable, so any change means a new version, and earlier versions stay viewable and comparable.
- **Concurrent edits** are detected. A stale save gets a 412 and is never applied silently.
- **Access:** sales representatives can't write Estimates, Assumptions or exports (403). Users without access get the 404-equivalent.
- **Exports** carry no customer content in logs and are audited. Downloads use short-lived signed URLs issued only after authorization.
- **Accessibility:** WCAG 2.1 AA. The grid can be navigated with arrow keys and announces row and column headers. Blocker meaning never relies on colour alone. axe runs in CI.

## Technical Decisions

- **Ownership:** the `estimates` module owns Estimate, Estimate Version, Estimate Line, Assumption, Risk and (later) Baseline. Its tables are `estimates_*`. `gaps` owns Gaps and Unknowns, `conflicts` owns Conflicts, and `assessments` owns Findings and FindingOverride. Cross-module reads and calls go only through each module's `public.py`.
- **Single mutation path:** commands run in the shared Unit of Work, check `identity.authorize` (action names `estimates.<entity>.<verb>`), use `row_version` with If-Match, and call `platform.trace.append` in the same transaction. Trace events are `estimates.<entity>.<past_tense_verb>`, and every event type needs a payload model in the trace catalogue. Commits happen only at the edge. There is no external I/O inside a Unit of Work.
- **Deterministic arithmetic:** line totals, per-role effort, Contingency sums, section subtotals and overall totals come from pure domain functions. Back them with property-based tests. Effort is person-hours `numeric(10,1)`. Role mix must sum to 100. Per-role effort is rounded to 0.1 h using the largest-remainder method so it sums exactly to the line effort. Money is integer minor units plus an ISO-4217 currency. Overall duration is a version-level field and is not a sum of line durations. No endpoint accepts a total as input. A line's Contingency cell is derived only from its linked Contingency Assumptions.
- **Estimate Version status:** `draft, submitted, in_review, approved, rejected, superseded`. Epic 8 implements draft, submitted and superseded. Only one draft can exist per Estimate at a time. A new version copies lines and carries Assumptions and Risks forward explicitly. Submitting a newer version supersedes earlier non-Baseline submitted versions in the same Unit of Work. Mutating a non-draft version returns `estimates.version.immutable`.
- **Single blocker check:** `estimates.get_submission_blockers(version)` is the only place that decides whether a version can be submitted. It returns typed items: open Gaps/Unknowns, unaccepted Assumptions, open Conflicts, critical Findings with no override, and pending Review Requests (which return nothing until Epic 9).
- **Per-Opportunity serialisation:** `pg_advisory_xact_lock(opportunity_id)` is taken by conversion, accepting an Assumption, and submit. Submit re-runs the blocker check inside the lock and rejects with `estimates.version.blocked` when blockers remain.
- **Conversion** is one command (`convert_to_assumption` / `convert_to_risk`). It calls `gaps.mark_converted` in the same Unit of Work, so either both commit or neither does.
- **Drafting from Assessments** runs as the final workflow node and calls `estimates.draft_from_assessments` with a `node:` idempotency key, so replays create nothing. Mapping from Assessments to lines is deterministic and rule-based. Resolved Conflicts supply the chosen value. Open Conflicts are marked on the line.
- **Export** is a worker job (`estimates.export_version`) that writes through `platform.storage` (content-addressed and immutable) and appends an `estimates.estimate_version.exported` trace event. Clarification Questions are read through `gaps` public.
- **Errors** are problem+json with typed domain codes. Live updates are pushed over the per-Opportunity SSE stream.

## UX & Interaction Patterns

- **Estimate tab:** a dense grid built on shadcn Table. It has tabular figures, right-aligned numbers, a sticky header and sticky totals, and a left rule before the Contingency column. Inline editing is allowed only on drafts (`e`, `c` to add a line). A compact reason prompt appears on save. The version switcher is a segmented control for the two latest versions, plus a list under `v`, with a reserved Baseline marker slot. `d` toggles a diff that uses the diff-tint and `+`/`−` text markers (never semantic red or green) and shows a server-calculated summary line.
- **Assumptions Register** sits below the grid. It is grouped into Conditions (clipboard-check icon) and Contingencies (shield-plus icon), with origin chips and accepted-by. Unaccepted rows are blocker rows: blocker tint, a 2px blocker bar and a "not accepted" label, with an **Accept** action. Risks have their own section.
- **Submission Blockers card** on Overview: "N blockers before you can submit". Rows disappear live as blockers are resolved, and a polite aria-live region announces the new count. At zero it reads "0 blockers — ready to submit" and **Submit** becomes the primary action. A second "Blockers to Baseline" gate is laid out but stays empty until reviews exist.
- **Convert form** on the Gap card or in the inspector: a segmented Condition/Contingency control, with wording or amount and an "Accepted by" field that defaults to the current user.
- **States:** "No Estimate Version yet…" (Run assessment / Start blank), a submitted read-only banner with **New version**, a 412 message "Changed by [user] since you opened it" (Reload / View diff), and "Export failed: <reason>" with Retry. Copy uses glossary terms and specific reasons, with no emoji.
- The visual reference is `mockups/estimate.html`. Where the mockup and the spines differ, the spines win.

## Cross-Story Dependencies

- 8.1 (schema, template, arithmetic) underpins every other story. 8.3 adds the Assumption and Risk tables that 8.4, 8.5, 8.6 and 8.8 rely on.
- 8.6's blocker query reads Gaps and Unknowns (Epic 4), Conflicts and critical Findings or overrides (Epics 5–6), and later Review Requests (Epic 9). 8.7's supersede logic extends to Review Requests in Epic 9 (Story 9.4).
- 8.3 depends on accepted Assessments with per-integration and per-Work-Package effort (Epic 5), `workflows.start_run`, and resolved Conflicts (Epic 6). The catalogue comes from Epic 3. The Gap card Convert form builds on Epic 4.
- Baseline (`estimates_baselines`, `set_baseline`) and the in_review, approved and rejected transitions belong to Epic 9. Actuals per line belong to Epic 10.
