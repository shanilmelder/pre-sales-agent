# Epic 9 Context: Review, Challenge, Baseline and Decision Trace

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Put a qualified human between agent output and any committed figure. Named reviewers approve, reject or challenge a submitted Estimate Version (or specific Assessments). A Challenge reruns only the affected Assessments in a Workflow Run and produces a new Estimate Version with the delta, leaving the challenged version unchanged. Once every requested review is approved and nothing blocks it, the presales engineer sets the Baseline, and only a newer approved version can replace it. Anyone with access can trace any Estimate line or Assumption back to its Findings, Evidence and human decisions through an append-only Decision Trace whose completeness is tested. This closes the R1 loop from "submitted" to "baselined". Status: Story 9.8 is done (demo slice) and 9.1 is in review. Everything else is in the backlog and is built on the Epic 17 redesign.

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

- **Review types:** engineering, PM and security. A reviewer must hold the matching role. The target's author can never review or approve it, and the API enforces this whatever the UI shows. Every decision except Approve needs a reason.
- **Reminders:** in-app only in R1, with a configurable interval (default 3 days). They are idempotent, and decided, superseded or cancelled requests get none.
- **Superseding:** a newer submitted version supersedes the open requests on older versions. Approvals never carry over.
- **Challenge:** needs a reason. The platform suggests the affected Assessments with deterministic rules, and the owning presales engineer confirms or declines them. Conflict detection, the Critic and the Red Team always rerun.
- **Baseline:** the version must be approved, at least one Review Request must have been sent, every non-cancelled request must be approved, and there must be no submission blockers. Setting it is traced and can't be undone. No agent or system actor may set it.
- **Trace:** records decisions and Evidence, never prompt text or model reasoning. Nobody can edit or delete a row, admins included.
- **Performance:** the first Trace page loads in under 500 ms at P95 on an Opportunity with 5,000 events.
- **Access:** scoped to the Opportunity. Sales representatives can't request or decide reviews but can view lineage read-only. Reviewers get read-only collaboration while their request is open.

## Technical Decisions

- **Ownership:** `reviews` owns Review Requests, Review Decisions and Challenges (`reviews_*`). `estimates` owns the Baseline (`estimates_baselines` with full history, written only by `estimates.set_baseline`). `notifications` owns Inbox items. Reviewer collaboration is written by `opportunities`. Modules call each other only through `application/public.py`.
- **Mutation path:** each command runs in one Unit of Work: `identity.authorize` with a `<module>.<entity>.<verb>` action, then domain and state-machine rules, then the `row_version`/`If-Match` check (412), then the write, then `platform.trace.append`. Cross-module effects (notify, supersede, start a run, enqueue a job) join the caller's Unit of Work. Commits happen only at the edge. No LLM or HTTP call runs inside an open Unit of Work.
- **Authorization (changed: roles now live in Auth0 RBAC):** permission names equal action names and arrive in the access token's `permissions` claim. Roles arrive in a namespaced roles claim. The API authorizes from the token alone. Opportunity membership and the sales-representative exclusions stay in platform code (`identity/domain/policy.py`). `identity_user_roles` is only a display cache and must never be read for authorization. The Management API is used only to invite users. Note: role checks on *other* users (the reviewer picker, escalation targets, "still holds the role") can't come from the actor's token. Settle how each story makes those checks within this rule.
- **State machines (enforced in the domain, with transition tests):** Review Request `pending, approved, rejected, challenged, superseded, cancelled`. Challenge `awaiting_confirmation, reassessing, completed, declined, failed`. Estimate Version `draft, submitted, in_review, approved, rejected, superseded`. Decisions are append-only, and a request's status is derived from its latest decision. Targets are typed and versioned `{kind, id, version}`.
- **Serialisation:** review decisions, `set_baseline` and every other command that affects the Baseline checks take one per-Opportunity advisory lock. Story 9.7 consolidates the lock calls onto one shared helper.
- **One blocker check:** `estimates.get_submission_blockers(version)` is the only gate before submit and before Baseline. Its Review Request part reads `reviews.public.list_open_requests`.
- **Challenge runs:** a run starts only through `workflows.start_run(run_type=challenge, idempotency_key=run:<opp>:challenge:<challenge_id>)`. Only the run's final node creates the new version (`node:` idempotency key), carrying Assumptions and Risks forward explicitly. The run fails if the Estimate changed since it started. The Challenge reason reaches agents only inside a delimited data block.
- **Trace:** there is one writer. Every `event_type` has a Pydantic payload model in the catalogue, and CI checks this. The app DB role has no UPDATE or DELETE. Agents are recorded as `<agent_id>@<semver>`. Lineage queries compose `public.py` queries from the other modules, and a Finding is always cited with its Assessment version.
- **API:** REST under `/api/v1` with problem+json codes and 409 for invalid states. The TS client is generated, so regenerate it after new endpoints. There is one SSE stream per Opportunity and no per-user stream, so the Inbox polls (30 s, plus a refresh on window focus).
- **Jobs:** reminders run from `platform_schedules` through the typed job registry, with idempotency keys.
- **Tests:** domain tests run without a DB. Commands and graphs get Postgres integration tests with a fake ModelGateway.

## UX & Interaction Patterns

- **Visual source of truth:** the standalone design spec at `ux-designs/ux-pre-sales-agent-2026-10-01/new-mockups/Presales Agent Design Spec (standalone).html` (the v2 redesign). It supersedes the older `mockups/` folder. Read only the sections you need, because the file is large. Use the Epic 17 primitives: Card, Dialog, Status pill, InlineAlert and the empty-tab card.
- **Right pane:** one 420px pane with Inspector and Activity tabs. Single-key shortcuts default to Off, so every shortcut needs a visible control.
- **Review panel (Inspector):** shows the target with its Evidence. **Approve**, **Reject** and **Challenge** sit on the first row, and **Request evidence**, **Request alternative** and **Escalate** on a second row. **Open in tab** shows it full width. Superseded requests are greyed out with a "Superseded by v4" link and no actions.
- **Inbox:** two panes. List rows have an unread dot, a title, meta and a kind pill (Review or Update), with `j`/`k`/Enter navigation and pagination (no infinite scroll). The empty-state copy differs between the story and the UX doc, so confirm it in the story spec.
- **Challenge dialog:** one 520px dialog with a required reason and `aria-pressed` toggle cards for the Assessments to rerun. A reviewer sees **Raise Challenge**. The owner sees **Rerun N Assessments** or **Decline**.
- **Baseline:** Set Baseline is enabled only when the "Blockers to Baseline" group is empty. When disabled, it is `aria-disabled` and states the reason. It uses a confirm dialog that lists the approvers. The Baseline marker (anchor icon) appears everywhere, and the version switcher lists the Baseline first.
- **Trace tab:** a reverse-chronological list. Filters live in the URL. Selecting a row opens the Trace event inspector, which shows the payload, a version comparison, Evidence chips (superseded ones struck through) and the append-only note.
- **Accessibility and copy:** WCAG 2.1 AA with axe in CI. Use glossary terms and no emoji.

## Cross-Story Dependencies

- **Other epics:**
  - Epic 17 (redesign, 17.1–17.4 in review) comes before any new UI.
  - Epic 8 provides versions, `create_version`, `submit_version`, the blocker check and version compare. Story 8.6 (submit gate) is in review.
  - Epic 5 provides `workflows.start_run`, the Activity tab and waiting-for-human runs.
  - Epic 6 provides Conflicts, the Critic, the Red Team, overrides and escalations.
  - Epic 1 provides the trace writer, Auth0 RBAC and collaboration.
- **Order within the epic:** 9.1 comes before 9.2–9.5. Story 9.2's `notifications.public.notify` feeds 9.3–9.6. Story 9.3 feeds 9.4 and the approval check in 9.7. 9.5 comes before 9.6. 9.8 and 9.9 come before 9.10, which reuses the 9.9 lineage test.
- **Hooks:** Story 9.4 hooks `reviews.public.supersede_open_requests` into `estimates.submit_version` in the same Unit of Work.
- **Extension points:** Epic 11 adds Teams and email through the 9.2 channel port. Epic 15 makes Challenges automatic and promotes Scenarios through `set_baseline`.
