---
title: 'Story 9.5: Raise a Challenge and confirm reassessment'
type: 'feature'
created: '2026-10-26'
status: 'done'
baseline_commit: '4b9c2b3ca141ec28c0f346e1ddd32ee78b156e7f'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-3-review-decisions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A reviewer who disagrees with an Estimate Version, an Assessment or one of its Findings can only reject it or ask for evidence. Nothing turns the disagreement into a targeted rerun, and the review panel's **Challenge** button is a placeholder ("Challenge arrives with Story 9.5").

**Approach:** Add Challenges to the `reviews` module: raise (with a required reason), deterministic suggestion of the affected Assessments, owner confirm (starts a `challenge` Workflow Run) or decline. Build the 520px Challenge dialog exactly as the new mockup draws it, and open it from the review panel, from a specialist Finding or Assessment on the Assessments tab, and from the owner's Inbox item.

**Run before 9.6 (decision 2026-10-26, option a):** a `challenge` run plans only the confirmed specialist agents plus the Critic (`queue_run`), and the worker executes it, so the confirmed Assessments really rerun. The Challenge stays `reassessing` until 9.6 adds Conflict detection, Red Team, the new Estimate Version and `completed`.

**Where the run shows (decision 2026-10-26, option a):** in the Assessments tab run header, which already refreshes on `workflows.*` events. The dialog's success state and the Inbox item show "Reassessment started (run N)" with a link to the Assessments tab. The right-pane Activity tab stays a placeholder.

**Base:** branch `task/story-9-5-challenges` in worktree `D:\Projects\Office\pre-sales-agent-95`, cut from the unmerged `task/story-9-3-review-decisions` (4b9c2b3). Rebase onto main once 9.3 merges. Story 9.4 is being built in parallel and also touches `reviews`; whichever merges second renumbers its migration.

## Boundaries & Constraints

**Always:**
- **Table `reviews_challenges`** (migration `0050`, after `0049_reviews_review_decisions`): `id`, `opportunity_id`, `target_kind` (`finding | assessment`), `target_id`, `target_version` (the Assessment version; for a Finding, its Assessment's version), `assessment_id` (the Assessment holding the target), `estimate_version_id` (the Estimate Version in context, from `estimates.current_reviewable_version`; 409 `challenge_needs_estimate` when there is none), `review_request_id` (nullable), `challenger_id`, `reason` (≤1,000 chars, required), `suggested` and `confirmed` (JSON arrays of agent ids), `decline_reason`, `workflow_run_id`, `status` (DB check), `row_version`, timestamps. Grant `SELECT, INSERT, UPDATE` to `psa_app`, no DELETE. Add it to the spine's Entity ownership row.
- **State machine** in `reviews/domain/challenges.py`, with transition tests: `awaiting_confirmation → reassessing | declined`, `reassessing → completed | failed`. Only 9.6 writes `completed`/`failed`. Review Request transitions gain `challenged → pending` (decline).
- **Suggestions** (deterministic, computed at raise, stored in `suggested`): the agent of the Assessment holding the target ("Suggested", pre-ticked), plus the agents of other current Assessments whose Findings cite one of the same Requirements, or a Requirement tagged with one of the same Integration Types ("Optional", unticked). Each carries a one-line "why" ("Holds the challenged Finding", "Cites REQ-12", "Shares the ERP integration type"). Critic and Red Team are always listed as rerunning, never toggleable. Integration Types come from the Requirements' tags through a new per-Requirement `intake.public` read.
- **Commands** (one Unit of Work each: authorize → `estimates.lock_for_review` → load `for_update` → state rules → `If-Match` 412 → write → trace → notify):
  - `POST /opportunities/{id}/challenges` → `reviews.raise_challenge`, action `reviews.challenge.raise`. Allowed for the Opportunity owner and for a reviewer with a `pending` Review Request on it; a sales rep or another reviewer gets 403. Appends `reviews.challenge.raised` (target kind/id/version, reason, suggested). With `review_request_id`, also records a `challenged` decision (drop the 9.3 "arrives with Story 9.5" 422) and the request becomes `challenged`; the reviewer keeps Opportunity access while their request is `challenged`. A reviewer's Challenge notifies the owner (kind `challenge_raised`, group `challenges`, key `challenge:{id}:raised`). When the owner raises it, the body carries `confirmed`, and the same Unit of Work runs the confirm step, recording both trace events.
  - `POST /opportunities/{id}/challenges/{cid}/confirm` (`If-Match`, body `{confirmed: [agent]}`, ≥1) → `reviews.confirm_reassessment`, action `reviews.challenge.confirm`, owner only. 409 `challenge_version_superseded` with "v2 is superseded by v3. Raise the Challenge again on v3 if it still applies." when the version in context is superseded. Stores `confirmed`, sets `reassessing`, calls `workflows.start_run(..., run_type=challenge, trigger_ref=challenge_id, idempotency_key=run:<opp>:challenge:<cid>)`, stores `workflow_run_id`, appends `reviews.challenge.confirmed`. A second confirm returns the existing run (200, no new run, no new event).
  - `POST /opportunities/{id}/challenges/{cid}/decline` (`If-Match`, required reason), action `reviews.challenge.decline`, owner only. → `declined`, the `challenged` request returns to `pending`, the challenger gets an Inbox item (kind `challenge_declined`) with the reason, and `reviews.challenge.declined` is appended.
  - `GET /opportunities/{id}/challenges/{cid}` returns the Challenge, target labels, suggestions, `superseded_by` version number, and flags `can_confirm`/`can_decline`. `GET /opportunities/{id}/challenges/suggestions?target_kind=&target_id=` returns the suggestions for a dialog that has not raised yet.
- **Workflows:** extend `start_run` with `run_type` (`assessment` default, `challenge`), `trigger_ref`, `idempotency_key`; add those columns to `workflows_runs` with a unique index on `idempotency_key`. An existing key returns that run. An active run on the Opportunity still gives 409 `assessment_in_progress`.
- **Inbox:** add `challenge_raised` and `challenge_declined` (kind check migration, `KIND_GROUP` → `challenges`), a `reviews.challenge` subject with a live status read in `inbox.py`. The owner's item opens the Challenge dialog in the detail pane; when superseded it shows the blocked message and **Raise on v3** (opens a new dialog on the current version with the reason prefilled).
- **Web (mockup `new-mockups/…standalone.html`, the `dlgChallenge` dialog; EXPERIENCE.md :115; DESIGN.md :376):**
  - `ChallengeDialog`: `DialogContent` (520px default), title "Challenge Estimate v3" (or "Challenge {Agent} Assessment v2" / "Challenge Finding: {title}"), "Reason (required)" textarea with placeholder "State what looks wrong and why.", eyebrow "Assessments to rerun", `aria-pressed` toggle cards copied from `request-review-dialog.tsx:357-381` (agent, why, tag), a non-toggle line "Critic and Red Team always rerun", the helper "A rerun creates a new Estimate Version and shows the delta. Conflict detection, Critic and Red Team run again.", Cancel + primary.
  - **Reviewer:** cards are display-only (`aria-disabled`), primary "Raise Challenge" disabled until a reason is typed. **Owner raising:** cards editable, primary "Rerun N Assessments" disabled until reason and ≥1 tick. **Owner confirming from the Inbox:** reviewer's reason read-only, cards editable, "Rerun N Assessments" plus **Decline**, which reveals a required decline reason.
  - Entry points: enable the review panel's Challenge button (reviewer only); a **Challenge** button in `assessment-finding-inspector.tsx` and on `AssessmentCard` (owner, or a reviewer with a pending request; from API flags, never browser role checks).
  - Statuses in `lib/reviews.ts` `CHALLENGE_STATUSES`: awaiting_confirmation → gap "Awaiting confirmation", reassessing → agent "Reassessing", completed → resolved, declined → neutral, failed → blocker; icon + text. Add `reviews.challenge.*` to `REVIEW_TRACE_EVENTS`, `INBOX_TRACE_EVENTS` and `lib/trace.ts` labels. Announce "Challenge raised", "Reassessment started", "Challenge declined".

**Never:**
- No planning or execution specific to `run_type=challenge`, no new Estimate Version, no `completed`/`failed` writes (9.6). No Activity-tab build. No author-side outcomes list (9.4).
- No Challenges on Critic or Red Team Findings (they keep Supply evidence / Resolve / Override).
- Don't run Prettier on `web/`. Don't run tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Reviewer raises from review | Ana pending on v3, reason | Challenge `awaiting_confirmation`, `challenged` decision, request `challenged`, owner Inbox item, trace | blank reason → 422 |
| Owner raises own | owner, reason, confirmed [engineering] | one UoW: `reassessing`, run started, raised + confirmed events | none ticked → 422 |
| Confirm | owner, 2 ticked | `reassessing`, run id stored | stale `If-Match` → 412 |
| Confirm twice | same Challenge | same run returned, no second run | N/A |
| Decline | owner, reason | `declined`, request back to `pending`, challenger Inbox item | blank reason → 422 |
| Superseded | v2 in context, v3 exists | nothing written | 409 `challenge_version_superseded` |
| Run active | assessment run running | nothing written | 409 `assessment_in_progress` |
| Not allowed | sales rep, or reviewer without pending request | nothing written | 403 |
| Already decided | confirm/decline on non-`awaiting_confirmation` | nothing written | 409 `challenge_not_awaiting_confirmation` |

</frozen-after-approval>

## Code Map

- `backend/app/modules/reviews/application/decisions.py:135-149,206-315` -- `decide` is the template (authorize, lock, `for_update`, `_check_if_match`/`_stale`, trace, notify). `_clean_reason` 422 for `challenged` at :106,153 goes; `test_a_challenge_is_not_recorded_yet` (`tests/test_reviews_decisions.py:527`) flips. Access revoke at :278-284 must treat `challenged` as still open (`repository.has_pending_for_reviewer` :161).
- `backend/app/modules/reviews/domain/{requests.py:116-135,decisions.py:33-48}` -- TRANSITIONS (add `challenged → pending`; update `ALLOWED` in `tests/test_reviews_requests.py:48-57`), `RECORDABLE`, `status_after`.
- `backend/app/modules/reviews/application/requests.py:103,125,443,447,507,688` -- `ROLE_FOR_TYPE`, `superseded_detail`, `opportunity_title`, `notify_reviewer`, `target_labels`, `request_status` (model for `challenge_status`). New `application/challenges.py` + `domain/challenges.py`; export from `public.py`.
- `backend/app/modules/reviews/adapters/{models.py:41,78,repository.py}` + `api/routes.py` -- `ChallengeRow`, repo methods, 4 routes.
- `backend/migrations/versions/20261026_0049_reviews_review_decisions.py:77-85` -- grant/check pattern. New `20261026_0050_reviews_challenges.py`: table, `workflows_runs` columns + unique index, notifications kind check (`0048:154`).
- `backend/app/modules/workflows/application/{assessment_runs.py:288,runs.py:184,222,779}`, `adapters/models.py:42-66` -- `start_run`, `queue_run` plan, `enqueue_run` coalescing, worker `_execute`.
- `backend/app/modules/assessments/{adapters/models.py:276-361,application/public.py,assessments.py:157,163}` -- Assessment/Finding rows, `finding_requirements`; `agent_assessments`, `assessment_at`. Add a public read of the Findings' cited Requirement ids per current Assessment.
- `backend/app/modules/intake/{adapters/models.py:205-226,application/requirements.py:216}` -- per-Requirement Integration Type tags; add a public `integration_types_by_requirement(uow, ids)`.
- `backend/app/modules/estimates/application/review_status.py:39-91` -- `current_reviewable_version`, `reviewable_version`, `superseded_by_version`, `lock_for_review`.
- `backend/app/modules/identity/{actions.py:22,81,118-195,domain/policy.py:106-174}` -- 3 actions + `ACTION_CATEGORIES`; owner via `OWNER_GRANTS`, reviewers via `REVIEWER_GRANTS` + a pending-request check in the command.
- `backend/app/modules/notifications/{domain/notifications.py:23-56,adapters/models.py:12-27,application/inbox.py:36-117}` -- kinds, groups, subject status chain.
- `backend/app/platform/{trace/catalogue.py:1370-1393,errors.py:109,141,259,475}` + `tests/test_errors.py:38-57`, `tests/test_trace_catalogue.py`.
- Tests: `tests/test_reviews_requests.py:39-42,93,121,176,186,231` and `tests/test_reviews_decisions.py:145,168,180` helpers. `_assessment` inserts no Findings; add a Finding + requirement-link helper.
- Web (paths under `web/src/`):
  - Dialog: `components/ui/dialog.tsx` (520px default), template `components/opportunities/request-review-dialog.tsx:206-424`; `ui/textarea` (ReasonInput has no placeholder prop).
  - Review panel: `components/opportunities/review-panel.tsx:366-382,487-514,629,692`; `lib/reviews.ts:48,129,158-173`; tests `review-panel.test.tsx:87-94`.
  - Assessments: `specialist-assessments.tsx:472-519,1700-1725`, `assessment-finding-inspector.tsx:61-73`, `lib/assessments.ts:324,360`.
  - Inbox: `components/inbox/inbox-view.tsx:148,173-212`, `lib/inbox.ts:33,41,46-56,100-129,151`.
  - Actions: `app/opportunities/actions.ts:261,3440-3510`; tests `actions.test.ts:2766-2837`. Trace labels `lib/trace.ts:26,106`. Pills `components/ui/pill.tsx:9-15`.
  - `lib/api/schema.d.ts` -- regenerate from a fresh local uvicorn.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261026_0050_reviews_challenges.py` -- challenges table, run columns + index, kind check -- reversible.
- [x] `backend/app/modules/reviews/{domain/challenges.py,domain/requests.py,application/challenges.py,application/decisions.py,application/public.py,adapters/*,api/routes.py}` -- state machine, suggestions, raise/confirm/decline/read.
- [x] `backend/app/modules/workflows/{application/assessment_runs.py,application/runs.py,adapters/models.py,application/public.py}` -- `run_type`, `trigger_ref`, idempotency; plan only the confirmed agents + Critic for `challenge` runs.
- [x] `backend/app/modules/{assessments,intake}/application/public.py` -- suggestion reads.
- [x] `backend/app/modules/notifications/*`, `identity/{actions.py,domain/policy.py}`, `platform/{trace/catalogue.py,errors.py}`, `ARCHITECTURE-SPINE.md` -- wiring.
- [x] `backend/tests/test_reviews_challenges.py` (+ requests/decisions/errors/authorize/workflows updates) -- every matrix row, state-machine transitions, suggestion rules, idempotent confirm, access kept while challenged, migration down/up.
- [x] `web/src/lib/api/schema.d.ts` -- regenerate.
- [x] `web/src/components/opportunities/{challenge-dialog.tsx,challenge-dialog.test.tsx}`, `lib/reviews.ts`, `app/opportunities/actions.ts` (+ test) -- dialog in three modes, statuses, actions.
- [x] `review-panel.tsx`, `assessment-finding-inspector.tsx`, `specialist-assessments.tsx`, `inbox-view.tsx`, `lib/inbox.ts`, `lib/trace.ts` (+ tests) -- entry points, Inbox item, live refresh.

**Acceptance Criteria:**
- Given a reviewer with a pending request, when they open Challenge from the review panel, then the dialog shows the suggested cards display-only and "Raise Challenge" stays disabled until a reason is typed.
- Given the owner opens the Inbox item for that Challenge, when it loads, then the reviewer's reason is read-only, Engineering is pre-ticked, and "Rerun 1 Assessment" starts the run, which appears in the Assessments tab run header.
- Given the dialog in every mode (reviewer, owner raising, owner confirming, decline, superseded, 412), when axe runs, then there are no violations and every status has icon + text.

## Implementation Notes

- **Base moved (review pass 1):** 9.3 and 9.4 merged (#93), then 8.9 (#94). The branch was fast-forwarded to origin/main `567c90b` with the work carried over uncommitted. `baseline_commit` stays the original 9.3 commit; diff this story against `567c90b` for its own changes. The migration is now `20261026_0051_reviews_challenges.py` (`down_revision = "0050_review_outcomes"`), and its kind check also carries 9.4's `review_outcome` and `review_replied`.
- **Deviations from the spec:**
  - `target_kind` also accepts `estimate_version`, needed for "Challenge Estimate v3" from a review of a whole Estimate. Every current Assessment is suggested, or every specialist when none exists yet ("Not assessed yet").
  - `suggested` stores `{agent, why, tag}` objects rather than bare agent ids.
  - The "why" text follows the R-number convention ("Cites R12").
  - The API adds `superseded_by_id` and `can_challenge`.
- **Until 9.6:** when a challenge run finishes, the normal run completion rebuilds the Estimate draft and runs Conflict detection, as it does for any run. The Challenge stays `reassessing`.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-26). Layers: Blind Hunter (BH), Edge Case Hunter (EC), Verification Gap (VG).

| # | Layer | Finding | Verdict | Evidence / route |
|---|-------|---------|---------|------------------|
| 1 | BH, EC | "Critic and Red Team always rerun" and the helper promise more than the run does (no Red Team, Conflict detection or new version) | low | The copy is the mockup's and the frozen spec's; the decision to plan only the confirmed agents plus the Critic before 9.6 is frozen too. The fix would edit the spec. Rejected; 9.6 makes the copy true. |
| 2 | BH, EC | A confirmed Challenge leaves its request `challenged` and the reviewer keeps access indefinitely | medium | Real, but the frozen intent keeps the Challenge `reassessing` until 9.6, which completes it and supersedes the previous version's requests. Defer to 9.6. |
| 3 | BH | A reviewer raising from the Assessments tab links no request, so no `challenged` decision | false | The story records a `challenged` decision only "when raised from a review"; the Assessments-tab path is a separate entry point by design. |
| 4 | BH | Nothing stops duplicate open Challenges on one target | low | Each needs a typed reason; rare. The fix adds an index or guard. Rejected. |
| 5 | BH | A Challenge whose version is superseded stays `awaiting_confirmation` and its Inbox item stays open | false | The story requires the item to stay openable and show the blocked message with **Raise on v3**. |
| 6 | BH | No `confirmed_by` column; the decline item has no sender; the challenger isn't told about a confirm | low | The actor is in the trace; the story requires a decline item only. Fixes add columns or kinds. Rejected. |
| 7 | BH, EC | `superseded_by_id` is the current version, not the superseder, so "Raise on v4" can raise on v5 | low | Only when superseded twice before the owner opens it; raising on the current version is the useful outcome anyway. The fix adds an API field. Rejected. |
| 8 | BH, EC | Decline's `set_status(challenged → pending)` result is unchecked | false | The request was just read `for_update` under the Opportunity lock with its current `row_version`, so the update can't miss. |
| 9 | BH, EC | After decline the request is `pending` while its latest decision reads "Challenged" | low | The history is accurate, and `reviews.challenge.declined` records the reopening. Changing it adds a decision kind. Rejected. |
| 10 | BH | `?challenge=` stays in the URL, so a refresh reopens the dialog | low | Direct fix: drop the parameter when the linked dialog closes. Patch. |
| 11 | BH | Missing schema checks (`confirmed` once past awaiting, `assessment_id` vs kind) and some tests | low | Domain and commands enforce both; no named harm. Rejected (test gaps covered by 15–17). |
| 12 | EC | Challenging an Estimate Version with no current Assessments stores no suggestions; the owner can't confirm or raise | medium | Reachable: the Estimate draft exists after Gap detection, before any assessment run. Patch: with no current Assessment, suggest every specialist agent as Suggested ("Not assessed yet"). |
| 13 | EC | The suggestions read ignores `review_request_id`, so the dialog can show the current version, not the request's | low | From the review panel the target is the request's Estimate Version (exact). An Assessment review on a superseded version is already blocked by 9.3. Rejected. |
| 14 | EC | A pending review of an Assessment that has since rerun can't be challenged (422) | low | Rare. The 422 explains it, and the reviewer can still reject. Resolving non-current versions adds branches. Rejected. |
| 15 | EC | `superseded` with `superseded_by_version` None leaves Confirm enabled | low | `_view` always fills the replacing number for a superseded version. Rejected. |
| 16 | EC | `review_request_id` with an unrelated target flips the request to `challenged` | low | API-only; challenging an Assessment while reviewing the Estimate built from it is legitimate. Rejected. |
| 17 | VG | No test that a `challenged` request keeps access when the reviewer's other request is decided or cancelled | gap | Patch: Ana holds a second request, raises from the first, the second is approved; she keeps her collaborator row and reads the Challenge. |
| 18 | VG | `superseded_by_id` is only checked for non-null | gap | Patch: assert it equals v4's id. |
| 19 | VG | The `?challenge=` deep link is untested | gap | Patch: `specialist-assessments.test.tsx` cases for a valid id (dialog opens) and a malformed one (nothing opens). |
| 20 | VG | No in-app page renders the Challenge item's href | false | The owner's item renders the Challenge form inline in the Inbox detail; the href is the deep link. |
| 21 | VG | 9.4's `supersede.py` on main also reads `has_pending_for_reviewer` and supersedes `challenged` requests; the interplay is untested on this branch | gap | Main now has 9.3, 9.4 (#93) and 8.9 (#94). Patch: merge origin/main, renumber this migration after `0050_review_outcomes`, and run the suites. |

## Design Notes

- **Owner = `opportunities.owner_id`**, not a role, matching `OWNER_GRANTS`. A reviewer's raise right comes from a `pending` Review Request, checked in the command (the `REVIEWER_GRANTS` relation alone isn't enough once the request is `challenged`).
- **Suggestions are stored at raise**, so the owner sees the same set the reviewer saw even if Findings change before confirmation.
- **The version in context** may be a draft for an owner raising from the Assessments tab; the supersede check still applies.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-95`. Work, read and run commands only there. Do not commit or push. Test DB `psa_test95`: create it if missing; take only the two DB URLs from `.env` with the host swapped to `127.0.0.1` and the db to `psa_test95`.

**Commands:**
- `cd backend && uv run pytest tests/test_reviews_challenges.py tests/test_reviews_decisions.py tests/test_reviews_requests.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_errors.py tests/test_authorize.py tests/test_tool_gateway.py` on `psa_test95` -- expected: pass.
- Full backend suite on `psa_test95` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
