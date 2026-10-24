---
title: 'Story 9.1: Send Review Requests to named reviewers'
type: 'feature'
created: '2026-10-24'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-6-submission-blockers.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A submitted Estimate Version (Story 8.6) can't be sent to a qualified human, so nothing stands between agent output and a Baseline.

**Approach:** A new `reviews` module owns Review Requests and their state machine. The Estimate tab gets **Request review** for submitted / in-review versions: pick a review type, one or more reviewers holding the matching role, optionally specific Assessments, and a message. Requested reviewers get read-only `reviewer` collaboration. Senders can cancel with a reason. Open requests feed the "Blockers to Baseline" group of `get_submission_blockers`.

**Sequencing (decision 2026-10-24):** implement only after Story 8.6 is merged to main. Rebase this branch onto main first, and number the migration after 8.6's.

## Boundaries & Constraints

**Always:**
- **Table `reviews_review_requests`:**
  - Columns: `id`, `opportunity_id`, `review_type` (`engineering | pm | security`), `target_kind` (`estimate_version | assessment`), `target_id`, `target_version`, `estimate_version_id` (the version the request counts towards), `reviewer_id`, `requested_by`, `message` (≤2,000 chars, optional), `status`, `cancel_reason`, `row_version`, timestamps.
  - Grants: `SELECT, INSERT, UPDATE` to `psa_app`, with DELETE revoked.
  - Add the table name to the Entity ownership row in `ARCHITECTURE-SPINE.md`. Other modules reach it only through `reviews/application/public.py`.
- **State machine (domain layer):** statuses `pending, approved, rejected, challenged, superseded, cancelled`. 9.1 uses only `pending → cancelled`; the other transitions are defined now and used by 9.3/9.4. A transition test covers every allowed and forbidden pair.
- **Create:**
  - `reviews.create_review_request(uow, actor, opportunity_id, version_id, review_type, reviewer_ids, assessment_refs, message)` with action `reviews.review_request.create`. Owner and collaborators may create; sales representatives get 403 through `RELATION_EXCLUDED_ROLES`; reviewer collaborators get 403.
  - Takes the per-Opportunity lock (8.6's `lock_opportunity`) and checks the version's `If-Match`.
  - Version rules: it must be `submitted` or `in_review`. A draft gets 409 `estimate_version_not_submitted` "Submit this Estimate Version before requesting review". A superseded version gets 409 `estimate_version_superseded` "v2 is superseded by v3". A rejected version also gets 409; 9.3 adds that status.
  - Reviewer rules:
    - Each reviewer must hold the role for the type (`ENGINEERING_REVIEWER`, `PM_REVIEWER`, `SECURITY_REVIEWER`); otherwise 422 `reviewer_not_authorized_for_type`.
    - The version's author can't be a reviewer: 422 `author_cannot_review` "The author of v3 can't review it".
    - A reviewer who already has a pending request of that type on the same target gets 409 `review_request_duplicate`.
  - Writes one row per reviewer and per target (see Design Notes) and moves the version `submitted → in_review` through a new `estimates.public.mark_in_review(uow, version_id)`.
  - Grants reviewer collaboration through a new `opportunities.public.grant_reviewer_access(uow, opportunity_id, user_id)`, then appends one `reviews.review_request.created` event per row with request id, target kind/id/version, review type and reviewer id.
- **Author:** add a nullable `created_by` column to Estimate Versions.
  - New versions record the person who triggered the draft. For Assessment-sourced versions, that is the user who started the run, through `workflows.public`.
  - The migration backfills existing rows from the user actor of each version's `estimates.estimate_version.created` trace event, or else the starter of its run. Rows with neither stay NULL, and then no author check applies.
- **Reviewer collaboration:**
  - `opportunities_collaborators` gains `role` (`collaborator | reviewer`, default `collaborator`). A reviewer can read the Opportunity but gets no write action from `MEMBER_GRANTS`. Existing collaborators keep their row.
  - `opportunities.public.revoke_reviewer_access` removes a `reviewer` row once the user has no pending request left on the Opportunity. It runs on cancel now; 9.3/9.4 reuse it.
  - The owner's Collaborators list shows reviewers with a "Reviewer" tag and can't remove them.
- **Cancel:** `POST .../review-requests/{rid}/cancel` with `If-Match` and a required reason (1–1,000 chars), with action `reviews.review_request.cancel` for the sender or the owner. Only `pending` requests can be cancelled; otherwise 409.
  - Sets the request to `cancelled`, revokes reviewer access as above, and appends `reviews.review_request.cancelled`.
  - If no pending request is left for the version, it goes back to `submitted` (`estimates.public.mark_submitted_from_review`).
- **Reads:**
  - `reviews.public.list_open_requests(uow, version_id)` returns pending, rejected and challenged requests. `get_submission_blockers` fills `to_baseline` with one `review_request` Blocker per request, using title "{Type} review · {Reviewer} · {Status}" and an href to the Estimate tab with `?review={id}`. Use a lazy import to avoid the estimates↔reviews cycle.
  - `GET /opportunities/{id}/review-requests?version_id=` lists requests with names and statuses.
  - `GET /opportunities/{id}/review-requests/reviewer-candidates?review_type=&q=` returns users who hold that role, minus the author, using a new `identity.public.search_users_with_role`. Callers need `reviews.review_request.create`.
- **API flags:** `EstimateView.can_request_review` is true when the caller holds the action and the current version is `submitted` or `in_review`. Every write emits trace frames, so SSE refreshes the tab and the blockers.
- **Web (the new mockup has no Request review dialog, so it is built from the mockup's patterns):**
  - **Request review** (outline) sits in the Estimate toolbar after Export and shows only when `can_request_review` is true.
  - A new **Review requests** card below the Version lifecycle card lists each request: reviewer, type, target, status pill (EXPERIENCE.md L180 tones, icon + label), sent time, message, and **Cancel request** for the sender while it is pending. `?review={id}` scrolls to and highlights that row.
  - The lifecycle stepper shows "In review" as current for `in_review`. Add the version pills `submitted` (neutral) and `in_review` (gap).
  - Overview "Blockers to Baseline": each request is a mockup row (title plus meta "Sent {date} · {message excerpt}"), and its title links to the request. Copy: "No Review Request sent yet".
  - **Dialog (decision 2026-10-24, option a):** the mockup's Challenge-dialog conventions in a 520px dialog titled "Request review of Estimate v3". It contains:
    - a **Review type** segmented control (Engineering / PM / Security);
    - a **Reviewers** multi-select combobox (Popover + Command, removable chips, like `EvidencePicker`) that re-queries the candidates when the type changes;
    - "Assessments to review (optional)" as `aria-pressed` toggle cards, all unticked, with the helper "Leave all unticked to review the whole Estimate Version.";
    - a "Message (optional)" textarea;
    - a footer with **Cancel** (outline) and **Send N requests** (primary, disabled until a reviewer is chosen).

    A 4xx shows inline in the dialog.
  - **Targets (decision 2026-10-24, option a):** one request per reviewer per picked Assessment, whose target is that Assessment and its version. With no Assessment picked, there is one request per reviewer with the Estimate Version as target.
  - Announce "Review requested from 2 reviewers" and "Review request cancelled" through `useAnnounce()`.
- **Access:** no new 404/403 leaks. An outsider gets 404 and a sales representative gets 403 on every new endpoint.

**Never:**
- No decisions, Approve/Reject/Challenge, review panel or escalation (9.3/9.5); no supersede-on-submit hook (9.4); no Baseline (9.7).
- No `notifications` module or Inbox items. The reviewer's cancelled Inbox state lands in 9.2, which reads the request status.
- No role checks in the browser; use only the API's `can_*` flags. Don't extend `/users/search` to non-presales users.
- Don't run Prettier on `web/`. Don't run tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | v3 `submitted`; engineering; Ana and Ben (engineering reviewers); no Assessments | 2 requests `pending`, v3 `in_review`, both get reviewer access, 2 created events | N/A |
| Narrowed | security; Cy; Assessments A1 and A2 picked | 2 rows (Cy×A1, Cy×A2), target `assessment` with its version, `estimate_version_id`=v3 | N/A |
| Wrong role | PM reviewer named for engineering | nothing written | 422 `reviewer_not_authorized_for_type` |
| Author | v3's `created_by` named as reviewer | nothing written | 422 "The author of v3 can't review it" |
| Draft / superseded | draft v4, or superseded v2 | button hidden | 409 with the copy above |
| Sales rep | collaborator with sales role | button hidden | 403 |
| Cancel last pending | one pending request, reason given | `cancelled`, access revoked, v3 back to `submitted` | blank reason → 422; stale → 412 |
| Stale version | `If-Match` older than v3's row_version | nothing written | 412 inline alert |

</frozen-after-approval>

## Code Map

- `backend/app/modules/conflicts/` -- module skeleton to copy (domain/, application/public.py, adapters/, api/routes.py with prefix `/opportunities/{opportunity_id}`; If-Match header `routes.py:61`).
- `backend/app/main_api.py:17-36,131-151` -- register router; `backend/migrations/env.py:14-29` -- import new models.
- `backend/pyproject.toml:69-400` -- import-linter: add a `reviews` public-API contract, add it to the registry contract source list (:319), add `reviews.domain/adapters/api` to forbidden lists (opportunities :107, estimates :194, identity, workflows, assessments); `tests/test_architecture.py` runs it.
- `backend/app/modules/identity/domain/roles.py:13-22` -- reviewer roles exist (keep `test_authorize.py:106` nine-role count). `identity/actions.py:15-77` add actions; `domain/policy.py` `OWNER_GRANTS` :97, `MEMBER_GRANTS` :126, `RELATION_EXCLUDED_ROLES` :73-94 (sales rep; reviewer collaborators must get no member write grants); `scripts/seed_auth0.py:46-84` permissions (tests build tokens from it, `tests/auth_tokens.py:35`).
- `identity/adapters/models.py:30` `identity_user_roles`, `repository.py:50,99` `load_roles`/`_roles_by_user` -- base for `search_users_with_role` and `users_with_role(ids, role)`; existing `user_search.py:39` (no role filter, presales-only — leave as is).
- `opportunities/adapters/models.py:42-58` collaborators table (add `role`); `application/opportunities.py:84-94` `_load_readable`, `:389,:397` add/remove collaborator (owner-only, If-Match — do not reuse for reviewers; add system-level grant/revoke in `public.py`).
- `estimates/adapters/models.py:55-102` `EstimateVersionRow` (after 8.6: status check incl. `submitted`; add `in_review`, `created_by`); `application/draft.py:343-365` created event actor; `application/from_assessments.py:10` system-actor versions (use run starter); `adapters/repository.py:90` `lock_opportunity`; 8.6 `application/blockers.py` (`to_baseline` currently `[]`) and `submit.py:65-73` pattern.
- `app/platform/trace/catalogue.py` -- register `ReviewsReviewRequestCreated/Cancelled` and an `EstimatesEstimateVersionReviewStarted`-style status event if you emit one; `tests/test_trace_catalogue.py:149,156`.
- `app/platform/errors.py` (+ `tests/test_errors.py:31-45`) -- new codes; `platform/concurrency.py:44,71` If-Match.
- Migration after 8.6's (latest here `20261024_0043_estimates_risks.py`; grants pattern :90-91).
- Tests to imitate: `tests/test_estimates_risks.py` (`test_who_may_convert_and_edit` :231), `tests/test_opportunities.py:45,71,102` (`_user`, `_if_match`, `_add`), 8.6's submit tests for a submitted fixture.
- Web: `components/opportunities/estimate-grid.tsx` `EstimateHeader` :431-487 (toolbar :454-459), `VersionLifecycle` :492-559, `EstimateSection` :594+; `lib/estimates.ts:101-119` lifecycle steps/notes; `app/opportunities/actions.ts` (pattern `escalateConflict` :2970, `searchUsers` :484); `components/opportunities/finding-decisions.tsx:171-290` `EvidencePicker` multi-select, `reason-input.tsx:14`; `specialist-assessments.tsx:960-998` dialog trigger; `ui/{dialog,pill,card,inline-alert,button}.tsx`; `collaborators.tsx` (Reviewer tag); Overview card from 8.6 (`overview-summary.tsx`); `shell/live-region.tsx:76`.
- Mockup: `new-mockups/Presales Agent Design Spec (standalone).html` (= imports v2). Challenge dialog = dialog pattern; blockers card rows title+meta; EXPERIENCE.md L53, L94, L111, L179-180.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/migrations/versions/<after 8.6>_reviews_review_requests.py` -- table + grants, version status `in_review` + `created_by` (with backfill), collaborators `role` -- one migration, reversible downgrade.
- [ ] `backend/app/modules/reviews/{domain,application,adapters,api}/` -- state machine, create/cancel/list/candidates, public.py (`list_open_requests`, `create_review_request`, `cancel_review_request`) -- the new module.
- [ ] `backend/app/modules/identity/{actions.py,domain/policy.py,application/public.py,adapters/repository.py}`, `scripts/seed_auth0.py` -- actions, grants, reviewer-collaborator read-only, role search.
- [ ] `backend/app/modules/opportunities/{adapters/models.py,application/public.py,application/opportunities.py}` -- reviewer role, grant/revoke, collaborators list tag.
- [ ] `backend/app/modules/estimates/{domain,application/public.py,application/blockers.py,application/draft.py,application/from_assessments.py,api/routes.py}` -- `in_review`, `created_by`, `mark_in_review`/back to submitted, `to_baseline`, `can_request_review`.
- [ ] `backend/app/platform/{trace/catalogue.py,errors.py}`, `backend/app/main_api.py`, `backend/migrations/env.py`, `backend/pyproject.toml`, `ARCHITECTURE-SPINE.md` -- wiring.
- [ ] `backend/tests/test_reviews_requests.py` (+ updates to errors, catalogue, authorize tests) -- matrix rows, transition table, grants, reviewer read-only access, blockers `to_baseline`.
- [ ] `web/src/lib/api/schema.d.ts` -- regenerate from a fresh local uvicorn.
- [ ] `web/src/components/opportunities/{request-review-dialog.tsx,review-requests-card.tsx}` (+ tests with axe) and edits to `estimate-grid.tsx`, `lib/estimates.ts`, `actions.ts`, `overview-summary.tsx`, `collaborators.tsx`, `status-pill` tones -- UI.

**Acceptance Criteria:**
- Given a reviewer collaborator, when they open the Opportunity, then every tab reads and no write control or write endpoint is available to them (403).
- Given an open request, when 8.6's blockers query runs on its version, then `to_baseline` lists it and the Overview card shows it linking to the request; with none sent it reads "No Review Request sent yet".
- Given the Estimate tab, when the dialog and card render, then axe reports no violations and every status has icon + text.

## Design Notes

Author check: `created_by` IS NULL means "unknown author", and the check is skipped. Don't block reviews on legacy versions.

Back to `submitted` on the last cancel keeps the lifecycle stepper honest. 9.4 owns supersede, so a version that is `in_review` and superseded is out of scope here.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_reviews_requests.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_errors.py tests/test_authorize.py` against `psa_test91` (both app and owner URLs on 127.0.0.1) -- expected: pass.
- Full backend suite on `psa_test91` -- expected: no new failures.
- `cd web && npm run typecheck && npm run lint && npm test` -- expected: pass.
