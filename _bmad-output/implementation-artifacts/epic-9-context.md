# Epic 9 Context: Review, Challenge, Baseline and Decision Trace

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Put a qualified human between agent output and any committed figure. Named reviewers approve, reject or challenge a submitted Estimate Version (or specific Assessments). A Challenge reruns only the affected Assessments through a Workflow Run and produces a new Estimate Version that shows the delta. Once every requested review is approved and nothing blocks it, the presales engineer sets the Baseline, which only a newer approved version can replace. Anyone with access can trace any Estimate line or Assumption back to its Findings, Evidence and human decisions through an append-only Decision Trace whose completeness is tested. This closes the R1 estimation loop: "submitted" becomes "baselined", and "how did we get this number?" has a tamper-proof answer. Status: only Story 9.8 is done, as a demo slice. Its version filter, Evidence chips, live updates and the 5,000-event performance gate are still to do. Every remaining story is built on the 2026-10-21 redesign (Epic 17 tokens and primitives), not on the old dense identity.

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

- **Review Requests:** sent to named reviewers by review type (engineering, PM or security). Only users who hold the matching role can be picked. The author of the target can never review or approve it, and the API enforces this whatever the UI shows. Reviewers can approve, reject, challenge, request evidence, request an alternative or escalate. Every action except Approve needs a reason.
- **Reminders:** overdue pending requests get reminders, in-app only in R1. The default interval is 3 days and is configurable. Reminders are idempotent, so rerunning the job sends no duplicates. Decided, superseded and cancelled requests get no reminder.
- **Superseding:** a newly submitted Estimate Version supersedes the open requests on older versions. Approvals never carry over to a changed version.
- **Challenge (R1):** the challenger must give a reason. The platform suggests the affected Assessments using deterministic rules. The owning presales engineer confirms which ones to rerun, or declines with a reason. Conflict detection, the Critic and the Red Team always rerun. The challenged version stays unchanged, and the result is a new version with a delta. Automatic reassessment only arrives in R3.
- **Baseline:** allowed only when all of these hold:
  - the version is approved;
  - at least one Review Request was sent, and every non-cancelled request is approved;
  - there are no submission blockers.

  Setting it is traced and can't be undone. Only a newer approved version can replace it. No agent or system actor may set it.
- **Decision Trace:** records decision events and Evidence, never model chain-of-thought or prompt text. Nobody can edit or delete a row, admins included. From any line or Assumption you can navigate to the Findings, Evidence and decisions behind it, and you can compare any two versions.
- **Performance:** status reads and the first Trace page take under 500 ms at P95, including on an Opportunity with 5,000 trace events.
- **Access:** scoped to the Opportunity. Sales representatives can't request or decide reviews, but can view lineage read-only. Reviewers get read access through Opportunity collaboration while their request is open.
- **Retention:** trace rows are kept for the contract lifetime plus 7 years. Only the privileged purge job deletes them.

## Technical Decisions

- **Ownership:**
  - `reviews` owns Review Requests, decisions and Challenges (`reviews_` tables).
  - `estimates` owns the Baseline (`estimates_baselines`, full history, written only by `estimates.set_baseline`).
  - `notifications` owns Inbox items.
  - Reviewer collaboration is written by `opportunities`, not `identity`.
  - Modules call each other only through `application/public.py`.
- **Mutation path:** every command runs these steps in one Unit of Work:
  1. `identity.authorize` with a `<module>.<entity>.<verb>` action.
  2. Domain rules and state-machine transitions.
  3. `row_version` check (If-Match, 412 when stale).
  4. The write.
  5. `platform.trace.append(uow, …)`.

  Commits happen only at the edge. Cross-module side effects (notify, supersede, start a run) take the caller's Unit of Work.
- **State machines (domain-enforced, with transition tests):**
  - Review Request: `pending, approved, rejected, challenged, superseded, cancelled`.
  - Challenge: `awaiting_confirmation, reassessing, completed, declined, failed`.
  - Estimate Version: `draft, submitted, in_review, approved, rejected, superseded`.

  The UI lifecycle stepper (Draft, In review, Approved, Baseline) is derived from the version status plus the Baseline pointer. It is never a control. Version labels are whole numbers.
- **Decisions:** stored as append-only rows. A request's status is derived from its latest decision. Targets are typed and versioned: `{kind, id, version}`.
- **Serialisation:** Baseline setting and every command that affects the Baseline checks take one per-Opportunity advisory lock through `platform.locks.opportunity_lock(uow, opportunity_id)`. Story 9.7 introduces this helper and moves the direct `pg_advisory_xact_lock` calls in Stories 4.4, 4.7, 6.6, 8.4, 8.5 and 8.6 onto it. Story 9.3's wording predates the helper, but 9.3 uses it too. A Postgres test proves that a concurrent rejection can never leave a Baseline on a rejected version.
- **One blocker check:** `estimates.get_submission_blockers(version)` is the only check run before submit or Baseline. Its Review Request category reads `reviews.public.list_open_requests(version)`.
- **Challenge runs:**
  - Started only through `workflows.start_run(run_type=challenge, trigger_ref=challenge_id, idempotency_key=run:<opp>:challenge:<challenge_id>)`.
  - Only the run's final node creates the new version, using the `node:<run>:<task>:<attempt>` key.
  - Assumptions and Risks are carried forward explicitly.
  - `expected_parent_version_id` fails the run if the Estimate changed in the meantime.
  - The reason goes to agents in a delimited data block.
  - No LLM call is made inside an open Unit of Work.
- **Trace:**
  - `platform_trace_events` has a single writer.
  - Every `event_type` has a Pydantic payload model in `platform/trace/catalogue.py`, and CI asserts this.
  - The app DB role has no UPDATE or DELETE grant.
  - Agents are recorded as `<agent_id>@<semver>`.
  - Read endpoints live in a module (`opportunities`), because the platform can't import modules.
- **Lineage:** `estimates.get_line_lineage` and `get_assumption_lineage` compose `public.py` queries from `assessments`, `conflicts`, `intake`, `gaps` and `reviews`. A Finding is always referenced together with its Assessment version.
- **API:**
  - REST under `/api/v1`, with problem+json codes `reviewer_not_authorized_for_type`, `reviewer_not_authorized`, `self_approval_forbidden` and `baseline_blocked`.
  - 409 for an invalid state.
  - The TS client is regenerated after new endpoints.
  - There is one SSE stream per Opportunity and no per-user stream. The Inbox therefore polls every 30 s and refreshes on window focus.
- **Jobs:** use the typed job registry and `platform_schedules`, for example the daily `reviews.send_reminders`.
- **Tests:** integration tests run against real Postgres with a fake ModelGateway.

## UX & Interaction Patterns

- **Visual base:** roomy, card-based layout with padded list rows, tint-filled status pills (icon plus label, never colour alone) and a static loader icon for Running (no pulse). Stale saves (412) use the inline alert "Not saved: … (412)" with **Reload** and **View diff**. Reuse the Epic 17 primitives (Card, Dialog, Status pill, InlineAlert, empty-tab card).
- **Right pane:** one 420px pane with Inspector and Activity tabs; `]` cycles it. Single-key shortcuts default to Off, so every shortcut needs a visible control.
- **Review panel (Inspector):** shows the target in full.
  - For an Estimate Version: lines, totals, the Assumptions Register, Risks and the diff.
  - For an Assessment: Findings with Evidence chips.
  - Actions: **Approve**, **Reject** and **Challenge** are visible, with a second row of **Request evidence**, **Request alternative** and **Escalate**. The old More menu is gone.
  - Approve is disabled for the author, with an explanation. The story and the UX spine word this message differently; confirm the copy in the story spec.
  - When all reviews are approved, the panel reads "All requested reviews approved. Baseline can be set." and shows **Set Baseline**.
  - **Open in tab** opens the panel full width.
- **Inbox (`g i`):** two panes. The list shows an unread dot, a bold title, meta and a kind pill (Review in agent tint, Update in neutral). The detail pane shows the review panel. Items are grouped into Review Requests, Challenges on my work, runs waiting for me, and decision updates.
  - Navigation: `j`/`k`/Enter, with pagination and no infinite scroll.
  - Skeleton rows show for at least 150 ms.
  - The page action is **Mark all read**.
  - The empty-state copy differs between sources: "Nothing waiting for you." (story) versus "Inbox is empty…" (spine and Story 17.5). Confirm in the story spec.
- **Superseded items:** greyed out, with a "Superseded by v4" link and no actions.
- **Review outcomes:** the author's own request shows one row per event with an icon, who, what, time and note: green check for Approved, amber triangle for Challenged, indigo loader for a confirmed rerun, for example "New version v3 shows L1 +14.0 h". Author responses are **New version**, **Reply** with Evidence, and **Link as alternative**.
- **Challenge dialog:** one 520px dialog for every case.
  - It has a required reason ("State what looks wrong and why.") and, under "Assessments to rerun", `aria-pressed` toggle cards: Suggested cards are pre-ticked, Optional cards are unticked. A helper says the Critic and Red Team always rerun.
  - A reviewer sees the cards for information only and presses **Raise Challenge**.
  - The owning presales engineer opens the same dialog from an Inbox item, sees the reviewer's reason read-only, edits the cards, and presses **Rerun N Assessments** or **Decline** with a reason.
  - An owner raising their own Challenge raises and confirms it in one submit.
  - A superseded context offers **Raise on v3**.
  - Run progress shows in Activity.
- **Blockers to Baseline (Overview):** lists pending, rejected and challenged requests, or "No Review Request sent yet". The spine also shows carried-forward Conflicts and uncovered Requirements as information; this is an open question. The list updates live. When it is empty it reads "0 blockers to Baseline", and **Set Baseline** becomes primary. A disabled Set Baseline is `aria-disabled` and gives its reason.
- **Set Baseline:** a confirm dialog lists the approvers with their role and decision time, and warns that the action can't be undone. The two sources word this warning slightly differently. After confirming:
  - The Baseline marker (a resolved-tint tag with an anchor icon) appears everywhere.
  - The version switcher lists the Baseline first and shows state pills (Superseded, Baseline, Draft).
  - The Version lifecycle card updates.
  - The polite live region announces the change.
- **Trace tab (`8`):**
  - A reverse-chronological list showing time, actor (agents by role, such as "PM Agent"), event in plain words, and a subject link.
  - Filters cover version, subject, actor type and event type, and live in the URL.
  - With no events, the empty card reads "No trace events".
  - Selecting a row opens the Trace event Inspector automatically. It shows:
    - a header with event, time and actor chip;
    - Payload, with a 120px key column: Correlation ID and Model for an agent, or Reason and authorising action for a human;
    - a "Version comparison · v2 to v3" for a line edit, with `+`/`−` rows on green and red tints (the only place the diff uses semantic colours);
    - Evidence chips, with superseded references struck through;
    - the append-only note.
- **Compare:** any two versions can be compared. The diff tint is `primary-tint` with `+`/`−` markers, plus a "Why it changed" list of trace events.
- **Copy and accessibility:** use glossary terms, specific reasons and no emoji. WCAG 2.1 AA applies, with axe in CI.

## Cross-Story Dependencies

- **Epic 17:** must come first for any new UI. Stories 17.1 to 17.4 are in review; 17.5 is in backlog and refits the Inbox shell and Mark all read.
- **Epic 8:** provides Estimate Versions, `create_version`, `submit_version`, `get_submission_blockers`, the Assumptions Register, version comparison and state pills (8.7), and the diff. Story 8.6 (the submit gate) is in backlog and is needed before 9.1. Story 8.9 (the Overview recomposition) holds the Submission Blockers card.
- **Epic 5:** provides `workflows.start_run`, durable runs, the Activity tab, waiting-for-human runs (5.5), budgets and cancellation.
- **Epic 6:** provides Conflicts, the Critic, the Red Team, Finding overrides (6.6) and Conflict escalation (6.3).
- **Epic 1:** provides the trace writer, roles and Opportunity collaboration.
- **Order within the epic:**
  - 9.1 comes before 9.2 through 9.5.
  - 9.2 (`notifications.public.notify`, with Inbox back-fill of 5.5 waits and 6.3 escalations) feeds 9.3 through 9.6.
  - 9.3 feeds 9.4 and the approval check in 9.7.
  - 9.5 comes before 9.6.
  - 9.7 brings the lock helper that 9.3 also uses.
  - 9.8 and 9.9 come before 9.10, which reuses the 9.9 lineage test on an end-to-end fixture.
- **Hook:** 9.4 hooks `reviews.public.supersede_open_requests` into `estimates.submit_version` in the same Unit of Work.
- **Extension points:** Epic 11 adds Teams and email through the channel port from 9.2, plus approval policies and escalation. Epic 15 makes Challenges automatic and promotes Scenarios through `set_baseline`.
