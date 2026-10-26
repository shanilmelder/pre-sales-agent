---
title: 'Story 9.3: Reviewers record decisions in the review panel'
type: 'feature'
created: '2026-10-25'
status: 'done'
baseline_commit: '66423736674290630819bf8d11f60eab6c950aa3'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-1-review-requests.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A reviewer named in a Review Request (9.1) can see the request but can't record a judgement, so no Estimate Version can become `approved` and the Baseline (9.7) stays out of reach.

**Approach:** Add append-only Review Decisions to the `reviews` module and a `reviews.decide` command: approve, reject, request evidence, request an alternative, or escalate, each with a reason (Approve's is optional). Build a review panel that follows the new mockup's review block. It shows the target with its Evidence and the actions, and it opens in two places: the Inbox detail pane, as the mockup draws it, and the right-pane Inspector, with **Open in tab** for a full-width view.

**Sequencing (decision 2026-10-25, option b):** implement only after Story 9.2 (Inbox and `notifications.public.notify`) is merged to main. Rebase this branch onto main first, and number the migration after 9.2's.

**Version diff (decision 2026-10-25, option a):** build a minimal server-side line diff here, which Story 9.9 reuses and extends.

## Boundaries & Constraints

**Always:**
- **Table `reviews_review_decisions`:**
  - Columns: `id`, `review_request_id` (FK), `decision` (`approved | rejected | challenged | evidence_requested | alternative_requested | escalated`), `reason` (≤1,000 chars; required for every decision except `approved`, enforced by a DB check), `decided_by`, `target_version`, `escalated_to` (required iff the decision is `escalated`), `decided_at`.
  - Grants: `SELECT, INSERT` only to `psa_app`. Add the table to the Entity ownership row in `ARCHITECTURE-SPINE.md`.
  - A request's status is derived from its latest decision through the existing domain `transition()`. `challenged` is defined, but only 9.5 writes it.
- **Estimate Version statuses:** add `approved` and `rejected` to `VersionStatus`, the DB check and the repository's sent/current sets, so an approved or rejected version stays current and can still be superseded.
  - Add `estimates.public.mark_approved` and `mark_rejected` in `review_status.py`'s style, each with its trace event.
  - Version pills: approved → resolved, rejected → blocker. The lifecycle stepper shows Approved as current for `approved`.
- **`POST /opportunities/{id}/review-requests/{rid}/decisions`** (`If-Match` = the request's `row_version`, body `{decision, reason, escalated_to?}`). It calls `reviews.decide` with the new action `reviews.review_request.decide`, which runs these steps in one Unit of Work:
  1. `identity.authorize`. `REVIEWER_GRANTS` and `MEMBER_GRANTS` gain the action; a sales representative gets 403.
  2. Take the per-Opportunity lock (`estimates.lock_for_review`).
  3. Load the request `for_update`.
  4. Check the actor: the actor must be the current `reviewer_id` and still hold `ROLE_FOR_TYPE`, or they get 403 `reviewer_not_authorized`. When the decision is `approved` and the actor is the version's `created_by`, they get 403 `self_approval_forbidden`.
  5. Check the state: the request must be `pending`, or 409 `review_request_not_pending`.
  6. Check `If-Match`: a stale value gets 412.
  7. Insert the decision with `target_version` = the request's target version.
  8. Apply the effects:
     - **approved:** the request becomes `approved`. When every non-cancelled request for its `estimate_version_id` is approved and the version is `in_review`, the version becomes `approved`.
     - **rejected:** the request becomes `rejected`, and the version becomes `rejected` from `in_review`.
     - **evidence requested / alternative requested:** the request stays `pending`.
     - **escalated:** the request stays `pending` and its `reviewer_id` becomes `escalated_to`. That user must hold the type's role and must not be the author or the current reviewer, or 422 `reviewer_not_authorized_for_type` / `author_cannot_review`. Grant the new reviewer access, and revoke the old reviewer's access when they have no pending request left.
     - **Every decision** bumps the request's `row_version`.
     - **approved or rejected** also revokes the reviewer's access once they have nothing pending left.
  9. Append `reviews.review_decision.recorded` with request id, decision, reason, target kind/id/version and `escalated_to`.
- **Inbox item for escalation:** in the same Unit of Work, the escalation calls `notifications.public.notify` for the new reviewer (kind `review_requested`, key `review:{id}:escalated:{decision_id}`). That reviewer's Inbox item then reads as an open review.
  - The original reviewer's item gets `subject_status` from the live request read. Extend 9.2's status read so it treats the item as closed once that user is no longer the assigned reviewer, which hides **Open**.
- **`GET /opportunities/{id}/review-requests/{rid}/panel`:** returns the request (with message, sender, status, `row_version`), its decisions, the `superseded_by` version number, the flags `can_decide` / `can_approve` with `approve_blocked_reason`, the escalation candidates (`search_users_with_role` minus the author and the current reviewer), and the target:
  - **For an Estimate Version:** lines, server totals, Assumptions Register and Risks through a new `estimates.public.version_detail(uow, version_id)` wrapping `version_view`. Also a diff against the previous version number through a new `estimates.public.compare_versions`. The diff matches lines by catalogue item / line key and covers added, removed and changed lines with their hours delta, plus the total delta. With no previous version, it says "First version".
  - **For an Assessment:** the Assessment at that version (new `assessments.public.assessment_at(uow, id, version)` built on `_views`), showing status, confidence and basis, and Findings with severity and their cited-Requirement Evidence chips.
- **Web (follow the new mockup's review block):**
  - **Opening the panel:**
    - **From the Inbox:** selecting a Review item renders the panel in 9.2's detail card, replacing its body and the **Open** button. A superseded or closed subject renders the greyed panel.
    - **From the Estimate tab:** clicking a row in the Review requests card, or following a `?review={rid}` deep link, opens the panel in the right-pane Inspector (`RightPaneContent`, as in `trace-list.tsx`).
  - **Inspector header:** the mockup Inbox detail header, i.e. eyebrow "{Type} review · From {sender} · {date}", title "Review request: Estimate v3, {Opportunity}", the author's message, then the target.
  - **Open in tab:** a link at the Inspector's top right goes to `/opportunities/{id}/estimate/reviews/{rid}`, which renders the same panel full width inside the workspace.
  - **Action rows:**
    - **Row 1:** **Approve** (primary), **Reject** (outline, red text), **Challenge** (outline). Challenge shows only for a reviewer, as `aria-disabled` with the hint "Challenge arrives with Story 9.5"; 9.5 builds the dialog.
    - **Row 2:** **Request evidence**, **Request alternative**, **Escalate** (outline).
  - **Reason:** pressing a non-Approve action reveals the inline "Reason for {rejecting | requesting evidence | requesting an alternative | escalating} (required)" textarea (`ReasonInput`). Escalate also shows a "Choose a reviewer" `Select` of the candidates. A **Confirm {action}** button is disabled until the reason (and the reviewer, for Escalate) is given; **Cancel** collapses it.
  - **Author lock:** for the author, Approve is `aria-disabled` and the inline hint "You authored v3, so you can't approve it." shows.
  - **Decision history:** the latest decision shows on the request as a pill plus "{who} · {decision} · {when}" with its reason.
  - **Card status:** the Review requests card shows that decision as the status.
  - **Actions:** only when `can_decide`; otherwise the panel is read-only.
  - **412:** shows `InlineAlert` "Changed by {name} since you opened it." with **Reload**, and **View diff**, which expands the version diff. No decision is recorded.
  - **Superseded:** when the request is `superseded` or its version is, the panel is greyed (opacity), shows a "Superseded by v4" link to that version and has no actions.
  - **Live refresh:** add `reviews.review_decision.recorded` and the new version events to `REVIEW_TRACE_EVENTS`, so SSE refreshes the tab and the blockers.
  - **Announcements:** announce "Estimate v3 approved", "Review rejected", and so on through `useAnnounce()`.

**Never:**
- No Challenge dialog or `reviews_challenges` (9.5).
- No author-side Inbox items for decisions, no outcomes list, no supersede-on-submit hook (9.4), and no Baseline or `platform.locks` helper (9.7).
- No changes to the Inbox list, grouping, badge or reminders (9.2). Only the Review item's detail body changes.
- No role checks in the browser; use only the API flags.
- Don't run Prettier on `web/`. Don't run tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Last approval | v3 `in_review`, Ana's approve is the last pending | Ana's request `approved`, v3 `approved`, Ana's access revoked, trace event | N/A |
| Partial approval | Ben still pending | Ana `approved`, v3 stays `in_review` | N/A |
| Reject | Ana rejects with reason | request + v3 `rejected` | blank reason → 422 |
| Request evidence | reason given | request `pending`, decision shown in panel and card | N/A |
| Escalate | Ana → Cy (engineering reviewer) | `reviewer_id`=Cy, Cy gains access, Ana loses it if nothing pending | Cy lacks role → 422; Cy is author → 422 |
| Self-approval | author holds role, approves via API | nothing written | 403 `self_approval_forbidden` |
| Not the reviewer | Ben decides Ana's request | nothing written | 403 `reviewer_not_authorized` |
| Role revoked | Ana lost ENGINEERING_REVIEWER | nothing written | 403 `reviewer_not_authorized` |
| Stale | `If-Match` older than the request | nothing written | 412 inline alert |
| Already decided | request approved, rejected or cancelled | nothing written | 409 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/reviews/domain/requests.py:36,54-70,85,102` -- `RequestStatus`, `TRANSITIONS`, `transition`, `clean_reason`; add `Decision` enum + `status_after(decision)` in a new `domain/decisions.py`.
- `backend/app/modules/reviews/application/requests.py:95,138,148,195,323-410,413,498` -- `ROLE_FOR_TYPE`, `_check_reviewable` (drop its rejected `pragma: no cover`), `_check_if_match`, `cancel_review_request` is the template for `decide`; `_views` (add latest decision), `reviewer_candidates`. Put `decide` + `review_panel` in a new `application/decisions.py`; export from `public.py`.
- `backend/app/modules/reviews/adapters/{models.py,repository.py:94,160,175,187}` -- add `ReviewDecisionRow`; repo `insert_decision`, `latest_decisions(ids)`, `reassign(id, reviewer, expected_row_version)`, `bump`; `set_status` only writes status/cancel_reason.
- `backend/app/modules/reviews/api/routes.py:64-79,161,207` -- If-Match aliases, ETag pattern; add decisions POST + panel GET.
- `backend/app/modules/identity/application/user_search.py:68,88,96` -- `search_users_with_role`, `users_with_role`, `user_names`.
- `backend/app/modules/identity/{actions.py:75-79,domain/policy.py:99-100,133,161,166}` -- add `REVIEW_REQUEST_DECIDE`; RELATION_EXCLUDED (sales rep), MEMBER/REVIEWER grants (`REVIEWER_GRANTS` docstring already expects it); `tests/test_authorize.py`, `tests/test_estimates_api.py` policy expectations.
- `backend/app/modules/estimates/domain/estimates.py:83,95`, `adapters/models.py:78`, `adapters/repository.py:340-341,423,451` -- statuses, check, `_SENT_STATUSES`, `move_status`, `supersede_submitted`.
- `backend/app/modules/estimates/application/{review_status.py:33-140,estimates.py:355,418,528,blockers.py:141-183}` -- add `mark_approved`/`mark_rejected`; `version_view` for `version_detail`; new `compare.py` for `compare_versions`; `can_request_review` stays false for approved/rejected.
- `backend/app/modules/assessments/application/{assessments.py:80,155,models.py:296-340}` -- `_views`, `AssessmentView`; specialist Findings carry `requirements` (the Evidence) and severity; no per-Finding status.
- `backend/app/modules/opportunities/application/opportunities.py:497,524` -- `grant_reviewer_access`, `revoke_reviewer_access(has_pending=)`.
- `backend/migrations/versions/20261025_0047_reviews_review_requests.py:100-105,142-146` -- grants + version check swap pattern; the new migration goes after 9.2's (`20261025_0048_notifications.py`, revision `0048_notifications`; so this one is `0049`), downgrade maps approved/rejected → `in_review`.
- From 9.2 (merged, PR #89):
  - **Backend:** `backend/app/modules/notifications/application/notify.py:29` (exported from `public.py`) `notify(uow, *, recipient_id, kind, opportunity_id, subject_type, subject_id, subject_version, summary, dedupe_key)`. The Inbox `subject_status` live read is `reviews/application/requests.py:640` `request_status`, used by `notifications/application/inbox.py:134`.
  - **Web:** `web/src/components/inbox/inbox-view.tsx` (detail card), `web/src/app/inbox/actions.ts`, `web/src/lib/inbox.ts`.
- `backend/app/platform/trace/catalogue.py:771,782,1308-1340` -- add `ReviewsReviewDecisionRecorded`, `EstimatesEstimateVersionApproved/Rejected`. `backend/app/platform/errors.py:109,237-271,518-529` + `tests/test_errors.py:11-20,47-51` -- `ReviewerNotAuthorizedError`, `SelfApprovalForbiddenError` (403 subclasses).
- `backend/tests/test_reviews_requests.py:93,121,145-231` -- `_version`, `_assessment`, `_events`, `_send`, `_cancel`, `_setup` to reuse in `tests/test_reviews_decisions.py`.
- Web:
  - **Reviews:** `lib/reviews.ts:17-22,37,69-71,112,117` (types, pill tones, copy, `REVIEW_TRACE_EVENTS`). `components/opportunities/review-requests-card.tsx:42,188-224` (status pill, `?review=` handling; make rows open the panel).
  - **Estimate tab:** `estimate-grid.tsx:113` (`VERSION_TONES`), `:608` (`Selection` union, add `review`), `:638,980,995,1058,1101-1170` (`RightPaneContent` branches). `lib/estimates.ts:101-119,433-435` (lifecycle, "Changed by…").
  - **Server actions:** `app/opportunities/actions.ts:3257,3301-3363` (load/action/412 pattern). Escalate picker as in `conflict-inspector.tsx:257,456-471`.
  - **Primitives:** `reason-input.tsx:14`, `ui/inline-alert.tsx:22`, `assumptions-register.tsx:263`, `risks-card.tsx:50`, `requirement-inspector.tsx:67` (`EvidenceChip`).
  - **Right pane:** `shell/shell-context.tsx:67,263` and `trace-list.tsx:485-537` show how the right pane opens.
  - **Open in tab page:** new `app/opportunities/[id]/estimate/reviews/[rid]/page.tsx`, next to the existing estimate route.
- Mockup: `new-mockups/Presales Agent Design Spec (standalone).html` line 382. INBOX detail is about byte 87.8k, with the review row-2 buttons near byte 92.5k and the outline style `border:1px solid var(--border2);background:var(--surface);padding:7px 14px;font-size:13px;font-weight:500`. EXPERIENCE.md :96, :114, :151, :154.

## Tasks & Acceptance

**Execution:**
- [x] Rebase `task/story-9-3-review-decisions` onto main once 9.2 has merged -- prerequisite.
- [x] `backend/migrations/versions/<after 9.2>_reviews_review_decisions.py` -- decisions table + checks + grants; version status check adds approved/rejected -- reversible.
- [x] `backend/app/modules/reviews/{domain/decisions.py,application/decisions.py,application/public.py,adapters/*,api/routes.py}` -- decide, panel read, latest decision on list views.
- [x] `backend/app/modules/estimates/{domain/estimates.py,adapters/*,application/review_status.py,application/compare.py,application/public.py}` -- statuses, mark_approved/rejected, version_detail, compare_versions.
- [x] `backend/app/modules/assessments/application/{assessments.py,public.py}` -- `assessment_at`.
- [x] `backend/app/modules/identity/{actions.py,domain/policy.py}`, `backend/app/platform/{trace/catalogue.py,errors.py}`, `backend/migrations/env.py`, `ARCHITECTURE-SPINE.md` -- wiring.
- [x] `backend/tests/test_reviews_decisions.py` (+ errors/authorize/estimates_api updates) -- every matrix row, version roll-up across requests, append-only grants, trace payload, panel read for both target kinds, compare_versions.
- [x] `web/src/lib/api/schema.d.ts` -- regenerate from a fresh local uvicorn.
- [x] `web/src/components/opportunities/{review-panel.tsx,review-panel.test.tsx}`, `web/src/lib/reviews.ts`, `app/opportunities/actions.ts`, `estimate-grid.tsx`, `review-requests-card.tsx`, `lib/estimates.ts`, `app/opportunities/[id]/estimate/reviews/[rid]/page.tsx` -- panel, Inspector wiring, Open in tab, pills, live refresh (tests with axe).
- [x] `web/src/components/inbox/inbox-view.tsx` (+ test), `backend/app/modules/reviews/application/decisions.py` notify call, 9.2's review `subject_status` read -- panel in the Inbox detail, escalation Inbox item, original reviewer's item closed.

**Acceptance Criteria:**
- Given an escalation to Cy, when it commits, then Cy has an unread Review item in the Inbox whose detail shows the actionable panel, and Ana's item shows no actions.
- Given a reviewer with a pending request, when they open it from the Inbox, the card or `?review=`, then the Inspector shows the target (lines, totals, Assumptions, Risks, diff, or Assessment Findings with Evidence chips) and both action rows; Open in tab shows the same full width.
- Given a non-Approve action, when no reason is typed, then Confirm stays disabled and the API also rejects it (422).
- Given the panel in every state (actionable, author-locked, read-only, superseded, 412), when axe runs, then there are no violations and every status has icon + text.

## Review Triage Log

Pass 1 (2026-10-26). Layers: Blind Hunter (BH), Edge Case Hunter (EC), Verification Gap (VG).

| # | Layer | Finding | Verdict | Evidence / route |
|---|-------|---------|---------|------------------|
| 1 | BH, EC | `decide()` records decisions on a request whose version is superseded | medium | `decide` never checks `version.status`. 8.6's submit supersedes an `in_review` version while its requests stay pending (`test_reviews_requests.py:746`). Patch: 409 `estimate_version_superseded`. |
| 2 | EC | Cancelling the last pending request, when the rest are approved, sends the version back to `submitted` | high | `requests.py:398` calls `mark_submitted_from_review` without checking `all_approved`, so the approvals never approve the version. Patch. |
| 3 | BH | Diff matches by section and title, not "line key" | false | `EstimateLine` (`models.py:71-96`) has no catalogue or line key; section and title is the only stable identity across versions. |
| 4 | BH, EC | Duplicate React keys in `DiffView` | low | `diff_lines` can emit rows with the same change, section and title. Direct fix (index in the key). Patch. |
| 5 | BH | Approve has no reason field or confirm step | false | The spec reveals the reason only for non-Approve actions, and Approve records at once as the mockup shows. |
| 6 | BH | Inbox "Escalated" applies to any recipient who isn't the reviewer | low | Only reviewer recipients get review-subject items today (9.2 kinds). Not reachable; the fix adds branches. Rejected. |
| 7 | BH | Deciding in the Inbox detail doesn't refresh the list row | low | `inbox-view.tsx` passes no `onDecided`; the row stays open until the 30 s poll. Direct fix (call `reload`). Patch. |
| 8 | BH | The reason carries over when switching action | low | `choose()` keeps `reason`, so text typed under Reject can be confirmed as an escalation. Direct fix. Patch. |
| 9 | BH | Escalate has no empty state | low | Rare (one reviewer per role); the fix adds a branch. Rejected. |
| 10 | BH | The candidate list is capped at `SEARCH_MAX_LIMIT` | low | Rare at R1 org size; the fix adds a search. Rejected. |
| 11 | BH | Times are shown in UTC | false | App-wide convention (`inbox.ts:75`, `estimates.ts:427`, `checklists.ts:217`); not this change. |
| 12 | BH, VG | "Superseded by v4" links to the Estimate tab, not v4 | low | The tab has no version URL and shows the current version (the superseder). The fix needs a new route parameter. Rejected. |
| 13 | BH | The Challenge hint is visible only to screen readers | low | Spec: Challenge is `aria-disabled` "with the hint". The `sr-only` class hides it. Direct fix. Patch. |
| 14 | BH | `version_status` is typed `str` | low | Developer-only, no named harm. Rejected. |
| 15 | BH | The 422 reason check runs before the 409/412 checks | false | The spec orders actor, then state, then If-Match; it doesn't place body validation, and the matrix rows use valid bodies. |
| 16 | BH | Other reviewers' pending requests on a rejected version still get reminders | medium | Deliberate per the Design Notes; closing them belongs with 9.4's supersede flow. Defer. |
| 17 | BH | The adapters docstring says "without foreign keys" but a FK was added | low | `reviews/adapters/models.py:1-5` contradicts `ReviewDecisionRow`. Docstring-only. Patch. |
| 18 | BH | The spec and sprint-status statuses disagree | false | The sprint status is `in-progress` until step 5; the spec status is the workflow's own. |
| 19 | EC | `submission.tsx` shows approved/rejected versions as drafts | false | `isSent` (`estimates.ts:74`) includes `approved` and `rejected`. |
| 20 | EC | The diff compares against an abandoned draft N-1 | false | The frozen intent says "diff against the previous version number". |
| 21 | EC | `?review=` never opens the panel under StrictMode | low | The ref is set before the timer, and StrictMode's cleanup clears the timer. Dev-only, direct fix. Patch. |
| 22 | EC | A transient read error hides the actions | low | Recovers on the next read; the fix adds branches. Rejected. |
| 23 | EC | A reload in flight can overwrite the local post-decision state | maybe-false | Needs a race between SSE and the decision; if it happens the next decision gets 412 and Reload fixes it. Low; rejected. |
| 24 | EC | The spec's `test_estimates_api` update is missing | low | Covered by `test_reviews_decisions` and the export tests added in #29. Rejected. |
| 25 | VG | No test that a submit supersedes an approved or rejected version | gap | Patch: parametrized test. |
| 26 | VG | The rejected-version send guard is untested | gap | Patch: assert 409 `estimate_version_rejected`. |
| 27 | VG | `decideReviewRequest` server action is untested | gap | Patch: a `describe` block in `actions.test.ts`. |
| 28 | VG | Loader state after Escalate / Request evidence is untested | gap | Patch: two `ReviewPanelLoader` tests. |
| 29 | VG | Export header labels for approved/rejected are untested | gap | Patch: parametrize the export label test. |
| 30 | VG | Decide's `has_pending=True` access path is untested | gap | Patch: a reviewer with two pending requests keeps access. |
| 31 | VG | The migration downgrade mapping is untested | gap | Patch: down to 0048, assert `in_review`, back up. |

## Design Notes

- **One component, two places.** EXPERIENCE.md :114 puts the panel in the Inspector, and the mockup draws the same block in the Inbox detail (EXPERIENCE.md :117). `ReviewPanel` is one component, and 9.4 extends it with the outcomes list.
- **Approve on a non-`in_review` version.** If an approve lands on a version that is already `rejected` (another reviewer rejected it), it is recorded but the version stays `rejected`. Only 9.4's new version clears it.
- **Escalation keeps one row.** It reassigns the same request rather than creating one, so the pending-uniqueness index and `to_baseline` stay correct.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-93`. Work, read and run commands only there. Do not commit or push. The test DB is `psa_test93`: create it if missing, and take only the two DB URLs from `.env` with the host swapped to `127.0.0.1`.

**Commands:**
- `cd backend && uv run pytest tests/test_reviews_decisions.py tests/test_reviews_requests.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_errors.py tests/test_authorize.py` on `psa_test93` -- expected: pass.
- Full backend suite on `psa_test93` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
