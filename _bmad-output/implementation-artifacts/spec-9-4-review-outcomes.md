---
title: 'Story 9.4: Author-side review outcomes and superseded requests'
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

**Problem:** After 9.3 a reviewer can decide, but the author never hears about it and can't answer. A rejected version is a dead end. Submitting a newer version leaves the old requests pending: they keep reminders and access, and their approvals look valid.

**Approach:**
- Notify the owner and the requester on every decision.
- Give the author a view of the request, built from the mockup's Inbox review block. It has a **Review outcomes** list, a **Reply** with Evidence, **Link as alternative**, and on a rejected version **New version**.
- Hook `reviews.public.supersede_open_requests` into `estimates.submit_version`.

**Decisions (2026-10-26):**
- (1) Everything stays in this one spec.
- (2) **New version** copies the base version's lines, Assumptions and Risks.
- (3) Reply Evidence is a Requirement, a Source document, or a newly added Opportunity Source. Knowledge Source references are deferred.
- (4) **Link as alternative** records the new draft on the reply. When that draft is submitted, the supersede hook creates the linked request.

**Branch:** `task/story-9-4-review-outcomes` sits on the unmerged 9.3 branch (`4b9c2b3`). Rebase it onto main once 9.3 merges.

## Boundaries & Constraints

**Always:**
- **Migration 0050:**
  - Kinds: recreate `ck_notifications_notifications_kind` from `KINDS`, which gains `review_outcome` and `review_replied`. Both use the label "Review" and the `review_requested` group.
  - Linked request: add `reviews_review_requests.linked_request_id` (nullable self-FK).
  - Replies: add `reviews_review_replies` with `id`, `review_request_id` (FK), `message` (1–2,000 chars), `evidence` (jsonb list of `{kind, id}`), `alternative_version_id` (nullable), `replied_by` and `replied_at`. Grant `SELECT, INSERT` only, and add it to the ownership row in `ARCHITECTURE-SPINE.md`.
  - Reversible.
- **Outcome items:** `decide` notifies the Opportunity owner and `requested_by` in the same Unit of Work, through `notify_reviewer`.
  - Kind `review_outcome`, dedupe key `review:{rid}:outcome:{decision_id}:{recipient}`. When the owner is the requester, send one item.
  - Summary: "{Reviewer} {decision label} Estimate v{n}: {reason}".
- **Inbox subject:** `inbox.py` `_subject` branches on kind. An outcome or reply item for a pending request is open, never "Escalated". Superseded and cancelled subjects show greyed with "Superseded by v{n}" and no actions.
- **Reply:** `POST …/review-requests/{rid}/replies` (`If-Match`) calls `reviews.reply`, with action `reviews.review_request.reply`.
  - Who: only the requester or the owner. Anyone else gets 403.
  - When: the request is `pending` and its latest decision is `evidence_requested` or `alternative_requested`; otherwise 409.
  - Evidence: every reference must resolve, through `evidence.resolve_all` plus `intake.foreign_evidence` as `assessments.supply_evidence` does. Otherwise 422 `evidence_unresolved`, naming the reference.
  - Alternative: `alternative_version_id` is allowed only after `alternative_requested`. It must be this Opportunity's draft, numbered above the target; otherwise 422.
  - Effect: the request stays `pending` and its `row_version` is bumped.
  - Trace: `reviews.review_request.replied` with the request, the Evidence `{kind,id}` refs and `has_alternative`.
  - Inbox: the reviewer gets a `review_replied` item, "Reply on Estimate v{n}".
- **Supersede on submit:** `submit.py` calls `supersede_open_requests(uow, old_version_id, new_version_id)` for each version that `supersede_submitted` touches. Use the lazy import that `blockers.py` uses.
  - Every `pending` or `challenged` request on those versions becomes `superseded`.
  - Access: the old reviewer's access is revoked once they have nothing pending.
  - Trace: one `reviews.review_request.superseded` per request, carrying the new version.
  - Linked request: if the request's latest reply points `alternative_version_id` at the new version, create a request on it with the same reviewer and type, and `linked_request_id` set to the original. Notify the reviewer with `review_requested`. This counts as one of the version's requests.
  - Superseded requests get no reminders, and their approvals never count.
- **New version:** `estimates.create_version(uow, actor, opportunity_id, base_version_id, reason)`, with action `estimates.estimate_version.create`.
  - The base must be `rejected` or `approved`, and no draft may exist; otherwise 409.
  - **Decision (2026-10-26, review):** it also works from a `submitted` or `in_review` base that has a `pending` request whose latest decision is `alternative_requested`. The base keeps its status until the new draft is submitted. The author panel shows **New version** next to **Reply** in that case.
  - It copies the base's lines and carries Assumptions and Risks, through `store_version`'s carry.
  - Trace: `estimates.estimate_version.created` with the base and reason.
  - Endpoint: `POST …/estimate-versions/{vid}/new-version`.
- **Panel read:** adds `is_author`, `can_reply`, `can_link_alternative`, `can_create_version`, `replies[]` (each with Evidence labels), `linked_request` (`{id, version_number}`) and the escalation assignee.
- **Web (author view, following the mockup review block at bytes 488,882–494,600):**
  - **Header and status:** the mockup header, then the status, the reviewer and the latest decision with its reason. For an escalation, "Escalated to {name}" with the reason. The reviewer actions stay hidden.
  - **Reply composer:** shown when `can_reply`. It has a "Reply to {reviewer} (required)" `ReasonInput`, the existing `EvidencePicker` (export it from `finding-decisions.tsx`) with `EvidenceChip`s, an **Add Source** button that opens `source-upload`, so the new source becomes pickable, and **Link as alternative**. That last one is a toggle, shown when `can_link_alternative`, with a select of the current draft. **Reply** is the primary button.
  - **Review outcomes list:** laid out as at byte 493,631, under the actions. The heading is 12px uppercase `text2`. Each row has a tone icon, "**who** · what", the time and a note. It has one row per decision and per reply (each reply row lists its Evidence chips). The icons:
    - Approved: green check-circle.
    - Rejected: blocker.
    - Requests and Escalated: amber triangle.
    - Replied: primary.
  - **Approved version:** show "All requested reviews approved. Baseline can be set." with no button (9.7).
  - **New version:** a button in `EstimateHeader` next to the `rejected` pill, which also shows the reviewer's reason. It also appears in the author panel.
  - **Reviewer panel:** shows the replies, and "Alternative to the v{n} request" linking the original.
  - **Live refresh:** add the new events to `REVIEW_TRACE_EVENTS`.
  - **Generated client:** regenerate `schema.d.ts` from a fresh local uvicorn.

**Never:**
- No Challenge, rerun or "Approved after rerun" rows (9.5/9.6).
- No Set Baseline (9.7), no Scenarios (R3), no Knowledge Source references.
- No role checks in the browser. No Prettier on `web/`. No tests on the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Outcome | Ana rejects v3; Alex is owner and requester | Alex gets one item | N/A |
| Owner ≠ requester | Requester Ben, owner Alex | Each gets an item | N/A |
| Evidence reply | Ana asked for evidence; Alex replies with R4 | stays `pending`, trace event, Ana's item "Reply on Estimate v3" | unknown ref → 422; no message → 422; stale → 412 |
| Reply not allowed | latest decision approved, or reviewer replies | nothing written | 409 / 403 |
| Alternative | Alex replies linking draft v4, then submits v4 | v3 request `superseded`; new request on v4 to Ana, linked; Ana notified | v4 not a newer draft → 422 |
| Submit v4 | v3 has pending Ben, approved Ana | Ben `superseded` and access revoked; Ana's approval doesn't count for v4 | N/A |
| New version | v3 `rejected`, no draft | draft v4 with v3's lines, Assumptions and Risks | draft exists or base `in_review` → 409 |
| Escalated | Ana → Cy | author panel shows "Escalated to Cy" and the reason | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/reviews/application/decisions.py:215,236-315,399` -- `decide` (add outcome notify after `:315`), panel read and `superseded_by`.
- `backend/app/modules/reviews/application/requests.py:146,212,266,429,443,447,507,531-559,688` -- `_check_reviewable`, `create_review_request` and its insert, `SUMMARY_HEAD`, `opportunity_title`, `notify_reviewer`, `target_labels`, `_views`, `request_status`.
- `backend/app/modules/reviews/adapters/repository.py:34,220` -- `NewRequest` (add `linked_request_id`), the reminder select. `domain/requests.py:41,54-70` -- `SUPERSEDED` and its transitions exist.
- `backend/app/modules/assessments/application/findings.py:429-449` -- `supply_evidence`, the Evidence-resolve pattern. `app/platform/evidence.py:87` -- `resolve_all`. `intake.public` provides `foreign_evidence`, `evidence_labels`, `evidence_options`. The reviews contract (`pyproject.toml:381`) forbids `knowledge`.
- `backend/app/modules/notifications/domain/notifications.py:23-28,50-56`, `application/inbox.py:77-96` -- the `:87` "Escalated" pitfall.
- `backend/app/modules/estimates/application/{submit.py:93-111,draft.py:280,blockers.py:142,review_status.py:54-73}`, `adapters/repository.py:340-365,441`:
  - `store_version` carries Assumptions and Risks, but it doesn't copy lines; add the line copy.
  - Also here: the lazy import, `superseded_by_version`, `supersede_submitted`.
- `backend/app/modules/opportunities/application/opportunities.py:502,524` -- `opportunity_owner`, `revoke_reviewer_access`.
- `backend/app/platform/trace/catalogue.py:1337-1397` -- the event pattern. `migrations/versions/20261025_0048_notifications.py:35-38,154` -- the kind check. The new migration's down revision is `0049_reviews_review_decisions`.
- `backend/tests/test_reviews_decisions.py:58-60,145-180,587,609` -- helpers. `test_reviews_requests.py:746` and `test_notifications_inbox.py:353` assume 9.4 supersedes, so update them.
- Web:
  - `components/opportunities/review-panel.tsx:83,94,279-430,458-619` -- the superseded link is at `:591`.
  - `finding-decisions.tsx:175` -- `EvidencePicker`. `requirement-inspector.tsx:67` -- `EvidenceChip`. `source-upload.tsx`.
  - `components/inbox/inbox-view.tsx:90-211`, `lib/inbox.ts:46,54,97-129`, `lib/reviews.ts:48,167,275-280`.
  - `estimate-grid.tsx:118-133,464`.
  - `app/opportunities/actions.ts:3151,3216,3440,3491`.
- Mockup: `new-mockups/Presales Agent Design Spec (standalone).html` line 382. The review block is at bytes 488,882–494,600 and the outcomes at 493,631, with data `OUT` at 615,308. Read with `tail -c +OFF | head -c N`. EXPERIENCE.md :77, :108, :116, :149, :151, :179-182.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261026_0050_review_outcomes.py` -- kinds, replies table, linked column, grants -- reversible.
- [x] `backend/app/modules/notifications/{domain/notifications.py,application/inbox.py}` -- kinds, kind-aware subject.
- [x] `backend/app/modules/reviews/{application/decisions.py,application/replies.py,application/supersede.py,application/requests.py,application/public.py,adapters/*,api/routes.py}` -- outcome notify, reply, supersede + linked request, panel fields.
- [x] `backend/app/modules/estimates/application/{versions.py,submit.py,public.py}`, `api/routes.py` -- `create_version` + endpoint, supersede hook.
- [x] `backend/app/modules/identity/{actions.py,domain/policy.py}`, `backend/app/platform/{trace/catalogue.py,errors.py}`, `ARCHITECTURE-SPINE.md` -- actions, grants, events, errors.
- [x] `backend/tests/test_reviews_outcomes.py` (+ the two pre-existing tests) -- every matrix row, no reminders after supersede, append-only replies, migration down/up.
- [x] `web/src/lib/api/schema.d.ts` -- regenerate.
- [x] `web/src/components/opportunities/{review-panel.tsx,review-outcomes.tsx,review-reply.tsx,finding-decisions.tsx,estimate-grid.tsx}`, `components/inbox/inbox-view.tsx`, `lib/{inbox,reviews}.ts`, `app/opportunities/actions.ts` (+ tests with axe) -- author view, outcomes, reply, New version, greyed superseded items.

**Acceptance Criteria:**
- Given a decision, when the author opens its Inbox item, then the detail shows the author panel with Review outcomes as the mockup draws them, and no reviewer actions.
- Given a rejected v3, when the author presses **New version**, then the Estimate tab shows draft v4 with v3's lines, Assumptions and Risks, and v3 keeps its pill and reason.
- Given the author panel in every state (reply, alternative, escalated, approved, superseded), when axe runs, then there are no violations, and each outcome has an icon and text.

## Implementation Notes

## Spec Change Log

- 2026-10-26, review pass 1, triage #5 (intent gap, resolved by the user): **New version** may also start from a `submitted`/`in_review` base with a pending `alternative_requested` request. Added as a decision under New version in the frozen block. Code was not reverted, because the change only adds to it; it was patched on top. This avoids an alternative flow that can't copy the version under review. KEEP: everything else as implemented.

## Review Triage Log

Pass 1 (2026-10-26). Layers: Blind Hunter (BH), Edge Case Hunter (EC), Verification Gap (VG).

| # | Layer | Finding | Verdict | Evidence / route |
|---|-------|---------|---------|------------------|
| 1 | BH, EC | An owner who is also the request's reviewer can reply to their own request | low | `reply()` checks requester/owner only; the panel's `is_author` excludes the reviewer. Patch: 403 when `user_id == record.reviewer_id`. |
| 2 | BH, EC | "Superseded by vN" names the current version, not the one that replaced it | medium | `review_status._view` uses the current (else latest) version, so after a new draft v5 a v3 request reads "Superseded by v5". Patch: for a version with `submitted_at`, use the first later submitted version. |
| 3 | BH, EC | A later evidence-only reply drops a linked alternative | medium | `supersede` reads only the latest reply. Patch: use the latest reply that names an alternative. |
| 4 | EC | An alternative draft re-drafted before submit is never linked | medium | Re-drafting v4 → v5 supersedes v4; submitting v5 finds no reply naming v5. Patch: link when the named alternative's number is above the old version and at most the new one. |
| 5 | BH | No way to copy an in-review version as the alternative draft | intent gap | **New version** needed a rejected/approved base. Resolved with the user (2026-10-26): allow it after `alternative_requested`. Added to the frozen block, then patched. |
| 6 | BH | A linked request always targets the Estimate Version | false | An alternative is a new Estimate Version by decision (4). Assessment ids don't move to it. |
| 7 | BH | The UI never sends a New version reason | low | The reason is optional in the API, and the spec draws no reason field. Rejected. |
| 8 | BH | The created trace stores reason text | false | The spec asks for the reason in the trace, and 9.3's `reviews.review_decision.recorded` stores reasons too. |
| 9 | BH, VG | A copy keeps the base's `source` | false | `has_version_from(ASSESSMENTS)` (`draft.py:231`) correctly sees copied Assessment lines as Assessment-built; nothing misreports. |
| 10 | BH, EC | Copied lines keep their old Requirement versions | low | Decision (2) copies the base's lines faithfully. Remapping changes what was estimated. Rejected. |
| 11 | BH | Outcome and reply bodies say "your Review Request" and name the requester as replier | low | `itemBody` copy. Direct fix: neutral wording. Patch. |
| 12 | BH | The client replaces the API's specific Evidence error | low | The route says "the `detail` is the sentence to show". Direct fix: use `detail`. Patch. |
| 13 | BH | The composer stays after a 409 | low | It recovers on reload, and the fix adds branches. Rejected. |
| 14 | EC | The composer's alternative state is set only at mount | low | When the draft appears after mount, Reply stays disabled while the select shows Draft vN. Direct fix: fall back to `panel.alternative_draft.id`. Patch. |
| 15 | BH | The outcomes list repeats the latest decision | false | The spec asks for the latest decision in the header and one outcome row per decision. |
| 16 | BH | Equal timestamps sort arbitrarily | low | Negligible. Rejected. |
| 17 | BH | Only the first rejection reason shows by New version | low | Rare (one reject already rejects the version); the fix adds a list. Rejected. |
| 18 | BH | No index on `linked_request_id`; field has no default; schema left out of the diff | low/false | The table is tiny; the field is a response field; `schema.d.ts` was excluded from the review diff on purpose. Rejected. |
| 19 | EC | A reply is accepted on a pending request whose version is already superseded (rows from before 9.4) | low | The dev DB has such rows; the panel forbids the reply but the API allows it. Direct fix: 409 `review_request_not_pending` when the version is superseded. Patch. |
| 20 | EC | The earlier reviewer's `review_replied` item stays open after an escalation | low | `AUTHOR_SIDE_KINDS` includes `review_replied`, which is a reviewer item. Direct fix: only `review_outcome` skips the escalated branch (backend and `isGreyedReviewItem`). Patch. |
| 21 | VG | No test that a reviewer-authored alternative gets no link | gap | Patch: add the test. |
| 22 | VG | No test that the decider gets no outcome item | gap | Patch: an owner-as-reviewer decision test. |
| 23 | VG | No test that a 412 names the replier | gap | Patch: add the test. |
| 24 | VG | New version from an approved base untested | gap | Patch: add the test. |
| 25 | VG | The empty Requirement-link guard is untested | gap | Defer: whether link-less lines occur isn't confirmed. |
| 26 | VG | The loader's post-reply state is untested | gap | Patch: a `ReviewPanelLoader` reply test. |
| 27 | VG | Superseding a `challenged` request is untested | low | It can't be reached until 9.5. Rejected. |

## Design Notes

- **Not in the mockup.** The Reply composer, the alternative link and **New version** aren't drawn. Build them from the review block's parts: outline buttons 13px with 7×14 padding and radius 8, a primary button for the commit, and `ReasonInput`. Don't invent new styles.
- **Why the link waits for submit.** Submitting the draft supersedes the original request, so the hook is the only point where both requests exist in one Unit of Work.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-94`. Work only there, and don't commit or push. Test DB `psa_test94`; take only the two DB URLs from `.env`, with the host swapped to `127.0.0.1`.

**Commands:**
- `cd backend && uv run pytest tests/test_reviews_outcomes.py tests/test_reviews_decisions.py tests/test_reviews_requests.py tests/test_notifications_inbox.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_authorize.py` -- expected: pass.
- Full backend suite on `psa_test94` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
