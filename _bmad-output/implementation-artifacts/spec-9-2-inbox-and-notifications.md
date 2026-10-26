---
title: 'Story 9.2: Inbox with in-app notifications and review reminders'
type: 'feature'
created: '2026-10-25'
status: 'done'
baseline_commit: '459cfa27d7547e73dc78a7dabebd38004352e34b'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-1-review-requests.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Review Requests (9.1), runs waiting for a decision (5.5) and escalated Conflicts (6.3) reach nobody. A reviewer only finds out by opening the Opportunity, and pending reviews stall.

**Approach:**
- A new `notifications` module owns Inbox items. They are created via `notifications.public.notify(uow, …)` inside the producer's Unit of Work, behind a channel port that has one in-app adapter.
- The `/inbox` page follows the new mockup, and the sidebar shows an unread count.
- A daily `reviews.send_reminders` job nudges reviewers about overdue requests.

## Boundaries & Constraints

**Always:**
- **Table `notifications_notifications`:**
  - Columns: `id`, `recipient_id`, `kind`, `opportunity_id`, `subject_type`, `subject_id`, `subject_version`, `summary` (≤300 chars), `dedupe_key` (unique), `channel` (`in_app` only), `read_at`, `created_at`.
  - Kinds: `review_requested`, `review_reminder`, `review_cancelled`, `run_waiting`, `conflict_escalated`.
  - Grants: `SELECT, INSERT, UPDATE` to `psa_app`, with DELETE revoked. Add the table to the Entity ownership row in `ARCHITECTURE-SPINE.md`.
- **`notify(uow, *, recipient_id, kind, opportunity_id, subject_type, subject_id, subject_version, summary, dedupe_key) -> bool`:**
  - It inserts with `ON CONFLICT (dedupe_key) DO NOTHING` and returns whether a row was written.
  - Summaries are built only from IDs and glossary terms, e.g. "Review: Estimate v3 — {Opportunity}". No message text, no model output.
  - Domain `Channel` protocol plus an `InAppChannel` adapter, so Epic 11 can add channels without changing callers.
- **Producers, in the same Unit of Work:**
  - **Review Request created** → `review_requested` to each reviewer. Key: `review:{id}:requested`.
  - **Review Request cancelled** → `review_cancelled` to the reviewer, with summary "Review cancelled: Estimate v3 — {Opportunity}". Key: `review:{id}:cancelled`.
  - **Run decision recorded** (`runs.py` `_waiting_on`) → `run_waiting` to the run starter (`workflows.public.run_starter`), or, when the system started the run (e.g. after Gap detection), to the Opportunity's owner (decided 2026-10-25). Key: `decision:{id}`.
  - **Conflict escalated** → `conflict_escalated` to `escalated_to`. Key: `conflict:{id}:escalated:{escalated_at epoch}`.
- **Back-fill:** the migration inserts items for state that already exists, using the same dedupe keys, so a rerun or a later live insert is a no-op. It covers:
  - every pending Review Request;
  - every open decision on a `waiting_for_human` run, sent to its starter, resolved the same way as `run_starter`, else to the Opportunity's owner;
  - every Conflict with status `escalated`.
- **API** (under `/api/v1`):
  - **`GET /inbox?page=`:** 25 per page, ordered by group then `created_at` desc. Each item carries `group`, `read`, `href` and `subject_status`.
    - Groups: `reviews` (requested and reminder), `challenges` (no producer until 9.5), `waiting` (run waiting and conflict escalated), `updates` (cancelled).
    - `subject_status` is read live through `reviews.public` / `workflows.public` / `conflicts.public` (lazy imports, as in 9.1). When the subject is no longer open, `href` is null and the item shows its status.
  - `GET /inbox/unread-count`.
  - `POST /inbox/{id}/read`.
  - `POST /inbox/read-all`.
  - **Access:** a new action `notifications.notification.read` in `ANY_ROLE_GRANTS`, and it is added to `seed_auth0.py`. A user only ever sees or marks their own items; another user's id returns 404.
- **Reminders:**
  - `PSA_REVIEW_REMINDER_DAYS` (int, default 3) in `Settings`.
  - The `reviews.send_reminders` job runs daily from a `platform_schedules` row seeded by the migration.
  - For each `pending` request with age ≥ N×interval (N ≥ 1), it calls `notify` with kind `review_reminder` and key `review:{id}:reminder:{N}`. Only when a row was written does it append `reviews.review_request.reminded` (payload: request id, reviewer id, interval number). A rerun on the same day therefore sends nothing.
  - Decided, superseded and cancelled requests get no reminder.
- **Web (follow the new mockup's INBOX section):**
  - **Page header:** "Inbox", subtitle "Review requests and notifications.", action **Mark all read** (outline, disabled when nothing is unread).
  - **Layout:** two-column grid (`minmax(0,1fr) minmax(0,1.4fr)`).
  - **List card:**
    - Small uppercase group labels ("Review Requests", "Challenges", "Waiting for your input", "Updates"); only non-empty groups are shown.
    - Each row has: an unread dot (primary for review kinds, `border-2` otherwise; transparent once read), a title (600 weight when unread), meta (12px, text-2: "From {sender} · {date}" or "{Opportunity} · {date}") and the kind label on the right ("Review" in primary, "Update" in text-2).
    - The selected row uses `bg-primary-tint`.
  - **Detail card:** "{kind} · {meta}", the title (16px/600), the body sentence, the subject status pill when closed, and **Open** (primary) linking to `href`.
    - Review → `/opportunities/{id}/estimate?review={rid}`.
    - Waiting run → the Assessments tab.
    - Conflict → the Conflicts tab.
  - **Interaction:**
    - Selecting a row (click, Enter, or ArrowUp/Down, plus `j`/`k` when single-key shortcuts are on) shows its detail and marks it read.
    - Pagination is Previous/Next; there is no infinite scroll.
    - Skeleton rows show for ≥150 ms on first load.
    - When there are no items: "Inbox is empty" / "Review requests and notifications for your Opportunities appear here." with no illustration.
  - **Sidebar:** the Inbox item shows a count badge (hidden at 0, "99+" cap, accessible name "Inbox, 3 unread").
    - It refreshes on window focus and every 30 s.
    - Inside an Opportunity it also refreshes on that stream's review, `conflicts.conflict.escalated` and `workflows.run.waiting_for_human` frames.
    - The Inbox page refreshes the same way.

**Never:**
- No review panel or Approve/Reject/Challenge actions (9.3). The mockup's decision buttons are out of scope. No Challenge producer (9.5).
- No Teams or email delivery, no per-user SSE stream, and no notification deletion.
- No role checks in the browser. Don't run Prettier on `web/`. Don't run tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New request | owner sends v3 to Ana and Ben | 2 unread `review_requested` items; badge 1 for each | N/A |
| Cancelled | sender cancels Ana's request | Ana gets an Updates item; her review item shows "Cancelled" with no Open | N/A |
| Reminder | pending 7 days, interval 3 | one reminder (N=2), one trace event; rerun the same day → none | N/A |
| Decided | request superseded / cancelled | no reminder | N/A |
| Back-fill | escalated Conflict and waiting run before migration | items exist after upgrade; a later live insert is a no-op | N/A |
| Other user's item | `POST /inbox/{id}/read` for someone else's id | nothing changes | 404 |
| Empty | no items | empty card copy above | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/reviews/` -- the module skeleton to copy. `application/requests.py:202` create (notify inside the per-candidate loop at :267-284), :323 cancel (notify after the trace at :366). `domain/requests.py:36,73` statuses / `OPEN_STATUSES`.
- `backend/app/platform/uow.py:20` UnitOfWork. `platform/trace/writer.py:22` `append` (pushes to SSE only when `opportunity_id` is set). `platform/trace/catalogue.py:1461` add `ReviewsReviewRequestReminded`; `tests/test_trace_catalogue.py:149,156`.
- `backend/app/modules/workflows/application/runs.py:709` `_waiting_on` (deduped by `repository.py:579`), `public.py:93` `run_starter`. `workflows_decisions` is at `adapters/models.py:145-183`; add a public `decision_status(uow, decision_id)` for `subject_status`.
- `backend/app/modules/conflicts/application/decisions.py:295` `escalate_conflict` (repo `escalate` :408; re-raise keeps the escalation at `conflicts.py:164`, so no new item). Conflict columns are at `adapters/models.py:90-94`; add a public status read.
- `backend/app/platform/schedules/{models.py:16,due.py:25}` (the payload has no fields). Job pattern: `workflows/application/progress.py:101-124`. Schedule seed pattern: `migrations/versions/20261014_0028_workflows.py:166-169`. `app/main_worker.py:47-60` `_JOB_MODULES`. `app/platform/config.py:16,61` Settings.
- The migration goes after `20261025_0047_reviews_review_requests.py` (revision `0047_reviews_review_requests`; grants at :100-101). Also: `migrations/env.py:14-30`, `app/main_api.py:17-38,133-155`.
- `backend/pyproject.toml`: add a notifications contract. Add `notifications.domain/adapters/api` to every forbidden list. The conflicts contract (:267-293) and the knowledge/registry contracts forbid whole modules, so let conflicts import `notifications.public`. `tests/test_architecture.py`.
- `identity/actions.py:22,112` Action + `ACTION_CATEGORIES`; `domain/policy.py:185` `ANY_ROLE_GRANTS`; `scripts/seed_auth0.py:46-84`.
- Tests to imitate: `tests/test_reviews_requests.py` (`_setup` :231, `_send` :186, `_cancel` :209, `_version` :93), `tests/test_opportunities.py:45` `_user`, `tests/test_workflows_decisions.py`, `tests/test_conflicts_resolution.py`.
- Web:
  - **Inbox page:** `app/inbox/page.tsx` is the stub to replace; copy `app/opportunities/list-page.tsx:46-150` (server read, `Pagination`, past-last redirect), `data.ts:51` `parsePage`. Page header pieces are in `components/shell/page-header.tsx:7,39,51`.
  - **Primitives:** `ui/{card,pill,skeleton,empty-tab-card,button}.tsx`, `lib/use-skeleton-done.ts`, `lib/opportunities.ts:42`.
  - **Sidebar badge:** `lib/navigation.ts:22-34` NavItem, `components/shell/sidebar.tsx:33,82-107` (add the badge via a polling client hook backed by a server action).
  - **Row navigation:** the inline pattern from `components/admin/users-table.tsx:44-56`, with `useShell().singleKeyShortcuts`. `g i` and the palette entry already exist.
  - **Actions and API client:** server actions in a new `app/inbox/actions.ts`, following `app/opportunities/actions.ts:268` (`createServerApiClient`). `lib/api/schema.d.ts` is regenerated against a fresh local uvicorn.
  - **SSE:** `lib/opportunity-events.ts:176,354` (`useReviewEvents`) for live refresh.
  - **Deep links:** `lib/workspace.ts:30` `tabHref`, `lib/reviews.ts:112`.
  - **Tests:** `components/admin/users-table.test.tsx`, `test/axe.ts`, `app/opportunities/pages.test.tsx:17-59` mocks. `components/shell/app-shell.test.tsx:13,58,136` uses the stub text, so update it.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261025_0048_notifications.py` -- table, grants, unique `dedupe_key`, index `(recipient_id, read_at, created_at)`, reminder schedule row, back-fill inserts -- reversible downgrade.
- [x] `backend/app/modules/notifications/{domain,application,adapters,api}/` -- Channel port and in-app adapter, `notify`, inbox query with grouping and subject status, mark read / read all, unread count, routes.
- [x] `backend/app/modules/reviews/application/{requests.py,reminders.py,public.py}` -- notify on create/cancel; `send_reminders` job; `request_status` read.
- [x] `backend/app/modules/{workflows,conflicts}/application/...` -- notify at `_waiting_on` and `escalate_conflict`; public status reads.
- [x] `backend/app/platform/{config.py,trace/catalogue.py}`, `app/main_api.py`, `app/main_worker.py`, `migrations/env.py`, `pyproject.toml`, `identity/{actions.py,domain/policy.py}`, `scripts/seed_auth0.py`, `ARCHITECTURE-SPINE.md` -- wiring.
- [x] `backend/tests/test_notifications_inbox.py` -- matrix rows, idempotent notify, reminder N-interval and rerun, back-fill via a migration down/up, grouping order, 404 on another user's item, catalogue and errors updates.
- [x] `web/src/lib/api/schema.d.ts` -- regenerate.
- [x] `web/src/app/inbox/{page.tsx,actions.ts}`, `web/src/components/inbox/{inbox-view.tsx,inbox-view.test.tsx}`, `web/src/lib/inbox.ts` -- page, list/detail, labels, hrefs (tests with axe).
- [x] `web/src/components/shell/sidebar.tsx`, `lib/navigation.ts`, `lib/use-inbox-count.ts` (+ tests), `app-shell.test.tsx` -- badge and polling.

**Acceptance Criteria:**
- Given an Inbox item, when it is selected, then it shows its detail, becomes read, and the sidebar count drops without a reload.
- Given the Inbox open in a window, when it regains focus or 30 s pass, then items and count refetch; inside an Opportunity a new Review Request frame refreshes the badge live.
- Given the Inbox and the badge, when axe runs, then there are no violations, and every status shows icon + text.
- Given the architecture tests, when they run, then no module imports `notifications` internals.

## Review Triage Log

Pass 1 (blind = Blind Hunter, edge = Edge Case Hunter, gap = Verification Gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | blind: system-started runs notify no one | high | `gaps/application/detection.py:340` → `enqueue_run` → `queue_run(..., SYSTEM)`; plan v1 is system-created, so `run_starter` is None and `_notify_starter` returns. The Gap-triggered run is the main automatic path; the back-fill skips the same runs | intent_gap |
| 2 | blind: group-first ordering pushes fresh waiting items behind old read reviews | medium | real, but the frozen intent says "ordered by group then `created_at` desc"; the fix would edit the intent | rejected (spec-mandated) |
| 3 | blind: live Opportunity title shown after reviewer access revoked | low | the stored summary already carries the title per intent; extra auth checks add complexity | rejected |
| 4 | blind: unread count includes closed-subject items | low | intent defines unread as `read_at IS NULL`; changing it adds rules | rejected |
| 5 | blind+edge: changing `PSA_REVIEW_REMINDER_DAYS` mis-numbers reminders | low | real but rare config change; the key format `review:{id}:reminder:{N}` is frozen | rejected (spec-mandated) |
| 6 | blind: arrow keys / j/k mark rows read | low | the frozen intent lists ArrowUp/Down and j/k as selecting, and selecting marks read | rejected (spec-mandated) |
| 7 | blind+edge: after a failed first load, reload fetches page 1 | low | `pageNumber = initial?.page ?? 1` in `inbox-view.tsx`; fix: pass the parsed page as a prop | patch |
| 8 | blind+edge: optimistic mark-read never rolls back | low | `select` keeps `read: true` when `markInboxItemRead` is not ok; fix: restore the item and count | patch |
| 9 | edge: sidebar count doesn't drop on select; an in-flight refresh can return the pre-read count | medium | `select` never calls `setInboxUnread`, and `refreshInboxUnread` reuses an in-flight request started before mark-read (AC1) | patch |
| 10 | edge: Mark all read sets the page's unread to 0 even when `result.unread > 0` | low | `markAll` sets `unread: 0`; fix: use `result.unread` | patch |
| 11 | edge: a back-filled summary can end in a space when the title ends in a newline | low | `trim()` runs before `regexp_replace`; fix: btrim after collapsing | patch |
| 12 | blind+edge: live vs back-filled label differs for non-current Assessment targets | low | cosmetic; dedupe uses the key | rejected |
| 13 | blind: polling hidden tabs; sequential subject lookups | low | 25 items a page, 30 s interval as the intent requires; batching adds complexity | rejected |
| 14 | blind: reminder job is one unbounded transaction | low | R1 volumes are small; intent asks for one daily job | rejected |
| 15 | blind: status vocabularies duplicated in notifications | low | no named failing caller today | rejected |
| 16 | gap: re-raised escalated Conflict Inbox status untested | gap | pre-verified: no test reads the Inbox after a re-raise | patch |
| 17 | gap: reminder job handler and setting never run | gap | pre-verified: tests call `send_due_reminders` directly | patch |
| 18 | gap: Assessment-target summaries (live, back-fill, multi-Opportunity reminders) untested | gap | pre-verified | patch |
| 19 | gap+blind: `/inbox?page=` and the past-the-end redirect untested | gap | pre-verified | patch |

#1 was resolved by the human (recipient: starter, else the Opportunity's owner; written into the intent) and applied as a targeted fix rather than a full revert, at the human's choice.

Pass 2 (a focused review of the fix round):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 20 | the page's unread count moves by a fixed delta, so a poll landing mid-select leaves it wrong and the rollback restores a stale row | low | `patch(item, ±1)` in `inbox-view.tsx`; the poll can come back between the optimistic update and the reply | patch |
| 21 | `refreshInboxUnread` loses a refresh requested in the microtask after its last `again` check | low | `inFlight` is cleared in `.finally` after the loop | patch |
| 22 | tests can't tell starter from owner; `_summary` whitespace untested; three web assertions pass without the code they target | gap | starter == owner in both tests; the rollback test starts at unread 2; markAll and in-flight assertions are confounded by the mount read | patch |
| 23 | an empty-string title gives "head —" in SQL vs "head" in Python | low | titles are required and non-empty at creation | rejected |

## Design Notes

- **Detail pane instead of the inspector:** the mockup puts the detail pane in the page, not the inspector. The review panel arrives in 9.3, so here **Open** deep-links to the subject. 9.3 can replace the detail body with the review panel.
- **Group labels:** the mockup list is flat, but the story asks for groups. Light group labels inside the one list card satisfy both.
- **Recipient of waiting runs:** decisions have no assignee. The run starter is the user who is "owed" the decision, and the other resolvers still see it on the Opportunity.
- **Dedupe key:** the dedupe key is the general idempotency tool for back-fill, reruns and reminders alike, so there is no extra table.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-92`. Work, read and run commands only there; the main checkout belongs to other sessions. Do not commit or push. The test DB is `psa_test92`: create it if missing, and take only the two DB URLs from `.env`, with the host swapped to `127.0.0.1`.

**Commands:**
- `cd backend && uv run pytest tests/test_notifications_inbox.py tests/test_reviews_requests.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_errors.py tests/test_authorize.py` on `psa_test92` -- expected: pass.
- Full backend suite on `psa_test92` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
