# Epic 9 Context: Review, Challenge, Baseline and Decision Trace

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Put a qualified human between agent output and any committed figure. Named reviewers approve, reject or challenge a submitted Estimate Version (or specific Assessments). A Challenge reruns only the affected Assessments through a Workflow Run and produces a new Estimate Version that shows the delta. Once every review is approved and nothing blocks it, the presales engineer sets the Baseline, which only a newer approved version can replace. Anyone with access can trace any Estimate line or Assumption back to its Findings, Evidence and human decisions, using an append-only Decision Trace whose completeness is checked by tests. This epic closes the R1 estimation loop: it turns "submitted" into "baselined", and "how did we get this number?" gets an answer that can't be tampered with.

## Stories

- Story 9.1: Send Review Requests to named reviewers
- Story 9.2: Inbox with in-app notifications and review reminders
- Story 9.3: Reviewers record decisions in the review panel
- Story 9.4: Author-side review outcomes and superseded requests
- Story 9.5: Raise a Challenge and confirm reassessment
- Story 9.6: Challenge reassessment run creates a new Estimate Version
- Story 9.7: Set the Baseline
- Story 9.8: Decision Trace tab
- Story 9.9: Trace any number to its Evidence and compare versions
- Story 9.10: Decision Trace completeness test

## Requirements & Constraints

- **Review Requests:** go to named reviewers by review type (engineering, PM, security). Only users who hold the matching role can be picked. The author of the target can never review or approve it, and the API enforces this whatever the UI shows. Reviewer actions are approve, reject, challenge, request evidence, request alternative and escalate. Every action except Approve needs a reason.
- **Reminders:** overdue pending requests trigger reminders (in-app only in R1, with a default interval of 3 days, configurable). Reminders must be idempotent, so a rerun of the job sends no duplicates.
- **Superseding:** a new submitted Estimate Version supersedes open requests on older versions. Approvals never carry over to a changed version.
- **Challenge (R1):** the challenger gives a reason. The platform suggests affected Assessments by deterministic rules. The owning presales engineer confirms which to rerun or declines with a reason. Conflict detection, Critic and Red Team always rerun. The challenged version stays unchanged, and the result is a new version with a delta. Automatic reassessment arrives only in R3.
- **Baseline:** allowed only when the version is approved, at least one Review Request was sent and every non-cancelled request is approved, and there are no submission blockers. It is recorded in the trace and can't be undone. Only a newer approved version can replace it. No agent or system actor may set it.
- **Decision Trace:** records decision events and Evidence, never model chain-of-thought or prompt text. Rows cannot be edited or deleted by anyone, admins included. Every line or Assumption can be navigated to the Findings, Evidence and decisions behind it, and any two versions can be compared.
- **Performance:** status reads and the first Trace page take under 500 ms at P95, including an Opportunity with 5,000 trace events.
- **Access:** access is scoped to the Opportunity. Sales representatives can't request reviews or decide on them, but can view lineage read-only. Reviewers get read access through Opportunity collaboration while their request is open.
- **Retention:** trace rows are kept for the contract lifetime plus 7 years. Only the privileged purge job deletes them.

## Technical Decisions

- **Ownership:** `reviews` owns Review Requests, Review Decisions and Challenges (tables prefixed `reviews_`). `estimates` owns the Baseline (`estimates_baselines`, with full history, written only by `estimates.set_baseline`). `notifications` owns Inbox items. Cross-module calls go only through each module's `application/public.py`.
- **Mutation path:** every command runs `identity.authorize` with a `<module>.<entity>.<verb>` action, checks domain rules and state-machine transitions, checks `row_version` (If-Match, 412 when stale), writes, and calls `platform.trace.append(uow, …)`, all in one Unit of Work. Commits happen only at the edge (the API handler or job step). Cross-module side effects, such as notifications, superseding requests and starting runs, take the caller's Unit of Work.
- **State machines (domain-enforced, with transition tests):**
  - Review Request: `pending, approved, rejected, challenged, superseded, cancelled`.
  - Challenge: `awaiting_confirmation, reassessing, completed, declined, failed`.
  - Estimate Version: `draft, submitted, in_review, approved, rejected, superseded`.
- **Decisions:** append-only rows. A request's status is derived from its latest decision. Targets are typed and versioned: `{kind, id, version}`.
- **Serialisation:** the Baseline and every command that affects Baseline checks take a per-Opportunity advisory lock through the shared `platform.locks.opportunity_lock(uow, opportunity_id)` helper. This replaces earlier direct `pg_advisory_xact_lock` calls. A Postgres test must prove that a concurrent rejection can never leave a Baseline on a rejected version.
- **One blocker check:** `estimates.get_submission_blockers(version)` is the only check before submit or Baseline. Its Review Request category reads from `reviews.public`.
- **Challenge runs:** start only through `workflows.start_run(run_type=challenge, trigger_ref=challenge_id, idempotency_key=run:<opportunity_id>:challenge:<challenge_id>)`. Only that run's final node creates the new version, using the `node:<run>:<task>:<attempt>` idempotency key. Assumptions and Risks are carried forward explicitly. An optimistic parent-version check (`expected_parent_version_id`) fails the run if the Estimate changed meanwhile. The Challenge reason goes to agents inside a delimited data block. No LLM call is made inside an open Unit of Work.
- **Trace:** `platform_trace_events` is the single writer path. Every `event_type` needs a Pydantic payload model in `platform/trace/catalogue.py`, and CI asserts this. The app DB role has no UPDATE or DELETE grant. Agent actors are recorded as `<agent_id>@<semver>`. Events with no Opportunity use a null `opportunity_id`.
- **Lineage:** built by `estimates.get_line_lineage` and `get_assumption_lineage`, which compose `public.py` queries from `assessments`, `conflicts`, `intake`, `gaps` and `reviews`. Findings are always referenced together with their Assessment version.
- **API conventions:** REST under `/api/v1` with problem+json codes (`reviewer_not_authorized_for_type`, `reviewer_not_authorized`, `self_approval_forbidden`, `baseline_blocked`), 409 for invalid state and a generated TS client. There is one SSE stream per Opportunity and no per-user stream, so the Inbox polls every 30 s and refreshes on window focus.
- **Scheduled jobs:** run through the typed job registry and `platform_schedules`, for example the daily `reviews.send_reminders`.
- **Tests:** integration tests run against real Postgres with a fake ModelGateway.

## UX & Interaction Patterns

- **Review panel (inspector):** shows the target in full. For an Estimate Version that means lines, totals, the Assumptions Register, Risks and the diff. For an Assessment it means Findings with Evidence chips. **Approve** and **Reject** are visible, and the other actions sit under **More**. Approve is disabled for the author, with a tooltip. **Open in tab** shows the same view full width.
- **Inbox (`g i`):** groups Review Requests, Challenges on my work, runs waiting for me and decision updates. It uses 32px rows with `j`/`k`/Enter navigation and pagination, never infinite scroll. The empty state reads "Nothing waiting for you." with no illustration.
- **Superseded items:** greyed out, with a "Superseded by v4" link and no actions.
- **Author outcomes:** each decision produces an Inbox item with the reviewer's reason. Responses are **New version** (after a reject), **Reply** with Evidence (after evidence is requested) and **Link as alternative** (after an alternative is requested).
- **Challenge form:** asks for a required reason. The owner then gets a **Confirm reassessment** item with pre-ticked checkboxes, and progress appears in the activity rail.
- **Blockers to Baseline gate (Overview):** lists pending, rejected and challenged requests, or "No Review Request sent yet". It updates live. When empty it reads "0 blockers to Baseline" and **Set Baseline** becomes the primary action.
- **Set Baseline confirm dialog:** lists the approvers and warns that the action can't be undone. The Baseline marker (anchor icon) appears everywhere, and the version switcher lists the Baseline first. The polite live region announces the change.
- **Trace tab (`8`):** a reverse-chronological timeline. Actors are shown by name, or agents by role such as "PM Agent". Filters cover version, subject, actor type and event type, and live in the URL. The inspector renders the payload field by field with Evidence chips, and superseded references are struck through.
- **Compare:** any two versions, using the diff tint with `+`/`−` markers and a "Why it changed" list of trace events.
- **Stale edits:** a 412 shows "Changed by [user] since you opened it" with **Reload** and **View diff**.
- **Copy and accessibility:** use glossary terms, specific reasons and no emoji. WCAG 2.1 AA applies, with no colour-only meaning.

## Cross-Story Dependencies

- **Builds on Epic 8:** Estimate Versions, `estimates.create_version`, `submit_version`, `get_submission_blockers`, the Assumptions Register, version comparison (8.7) and the diff view.
- **Builds on Epic 5:** `workflows.start_run`, durable runs, the activity rail, waiting-for-human runs (5.5) and budgets and cancellation.
- **Builds on Epic 6:** Conflicts, Critic, Red Team, Finding overrides (6.6) and Conflict escalation (6.3).
- **Builds on Epic 1:** the trace writer, roles and Opportunity collaboration.
- **Order within the epic:**
  - 9.1 comes before 9.2 through 9.5.
  - 9.2 (`notifications.public.notify`) is used by 9.3, 9.4, 9.5 and 9.6.
  - 9.3 decisions feed 9.4 outcomes and 9.7's approval check.
  - 9.5 comes before 9.6.
  - 9.7 introduces the shared lock helper that 9.3 also uses, and retrofits Stories 4.4, 4.7, 6.6, 8.4, 8.5 and 8.6.
  - 9.8 and 9.9 come before 9.10, which reuses 9.9's lineage test on a full end-to-end fixture.
- **Superseding:** 9.4 hooks `reviews.public.supersede_open_requests` into `estimates.submit_version` in the same Unit of Work.
- **Extension points:** Epic 11 adds Teams and email channels behind 9.2's channel port, plus approval policies and escalation. Epic 15 makes Challenge reassessment automatic and adds Scenario promotion through `set_baseline`.
