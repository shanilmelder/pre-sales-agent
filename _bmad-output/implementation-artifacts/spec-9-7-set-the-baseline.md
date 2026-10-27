---
title: 'Story 9.7: Set the Baseline'
type: 'feature'
created: '2026-10-26'
status: 'done'
baseline_commit: '567c90b48cc3cbeab0ce0d45b286c08b01877664'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-4-review-outcomes.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After 9.3 and 9.4 an Estimate Version can be `approved`, but nothing turns it into the committed figure. The review panel says "Baseline can be set." and offers no action. The Overview pipeline is stuck on "Approved, Baseline not set yet". Every module also takes its own advisory lock, so a rejection can race a Baseline.

**Approach:** Add `estimates_baselines` and the human-only `estimates.set_baseline` command behind one shared per-Opportunity lock (`platform.locks.opportunity_lock`), and make the Baseline gate and the command read the same blocker check. Then surface it as the **new mockup** draws it: the Set Baseline confirm dialog, the Baseline marker, the lifecycle stepper reaching Baseline, and the "Blockers to Baseline" gate going to "0 blockers to Baseline".

**Mockup wins (user, 2026-10-26: "follow the new mockups").** Where the epic and the mockup differ, use the mockup:
- Use the mockup's dialog warning copy.
- Use the mockup's approver rows.
- Use the mockup's four-step lifecycle.
- Add the anchor icon to the marker, because DESIGN.md:369 requires it.

## Boundaries & Constraints

**Always:**
- **`platform/locks.py` `opportunity_lock(uow, opportunity_id)`:**
  - It runs `pg_advisory_xact_lock(<bigint>)`. The bigint is the first 8 bytes of the UUID as a signed big-endian integer.
  - Replace the per-module lock functions with it:
    - Estimates `lock_opportunity` (the `estimates.draft` key, also re-exported as `lock_for_review`) and `lock_assumptions` (the `estimates.opportunity` key).
    - The Gap dismissal and answer lock (`gaps` repository).
    - Finding overrides (`assessments.findings`).
    - Gap and Unknown conversion.
  - Keep the other locks: conflicts, intake, knowledge, runs, tool gateway.
  - Postgres advisory locks are re-entrant within a session, so nested calls are safe. Any path that also takes a module lock must take the shared lock first.
- **Migration `0051` (down revision `0050_review_outcomes`):**
  - Table `estimates_baselines`: `id`, `opportunity_id` (FK), `estimate_version_id` (FK), `previous_version_id` (nullable FK), `set_at`, `set_by`. Index on `(opportunity_id, set_at DESC)`. The current Baseline is the latest row.
  - Grant `SELECT, INSERT` only.
  - Add the table to the `estimates` ownership row in `ARCHITECTURE-SPINE.md`.
  - The migration is reversible.
- **Blockers:** for a non-draft version, `to_baseline` contains:
  - its open Review Requests (as today);
  - a `no_review_request` blocker, "No Review Request sent yet", when no non-cancelled request exists;
  - the content checks that `to_submit` runs (Gaps, Unknowns, Assumptions, Conflicts, Findings, uncovered). These can reopen after submit.
  - The gate and `set_baseline` both read this one list.
- **`estimates.set_baseline(uow, actor, opportunity_id, version_id, if_match)`, action `estimates.baseline.set`:** it runs these steps in one Unit of Work.
  1. `identity.authorize`, granted to the owner and members.
     - `policy.is_allowed` gains a `HUMAN_ONLY_ACTIONS` set that denies any principal that isn't a user, whatever its grants.
     - `estimates.baseline.set` is in that set, so agents and system actors get 403.
  2. `opportunity_lock`.
  3. Load the version; the version `row_version` must match `If-Match`, or 412.
  4. If a Baseline exists and the version's number is ≤ the Baseline's or the version is not `approved`, return 409 `baseline_not_newer`, "Only a newer approved Estimate Version can replace the Baseline".
  5. Otherwise, if the version is not `approved` or `to_baseline` is non-empty, return 409 `baseline_blocked`. Its `blockers` extension lists each blocker by kind, and nothing is written.
  6. Insert the Baseline row.
  7. Append `estimates.baseline.set` with the version, the previous Baseline version and the approvers (user, review type, decision id). Add "set" to `_IRREGULAR_PAST_TENSE`.
- **Endpoints:**
  - `POST /opportunities/{id}/estimate-versions/{vid}/baseline` (`If-Match`).
  - `GET …/estimate-versions/{vid}/approvers` returns `[{name, review_type, decided_at, decision_id}]` through a new `reviews.public.version_approvals`, which lists the non-cancelled requests with their latest decision.
- **Baseline in reads:**
  - `EstimateView` gains `baseline: {version_id, version, set_at, set_by_name} | null`.
  - The submission-blockers view gains `is_baseline`.
  - The derived Opportunity status becomes `baselined` when a Baseline row exists, and `intake` otherwise, as today. `status_expression()` uses a raw `EXISTS (SELECT 1 FROM estimates_baselines …)` with no import from `estimates`, and `derived_status(has_baseline)` mirrors it.
- **Supersede:** `supersede_submitted` skips the Baseline version (Story 8.7: "every earlier submitted version that is not the Baseline"). A replaced Baseline stays `approved` and simply loses the marker.
- **Web: Set Baseline button (shared `SetBaseline` component, outline button 13px/500 with 7×14 padding and radius 8, as in the mockup @539990)**
  - Shown when the current version is not a draft and is not the Baseline.
  - Enabled (primary) only when the version is `approved` and `to_baseline` is empty.
  - Otherwise it is `aria-disabled` and states the reason (the first blocker title, or "Every requested review must approve v{n} first.").
  - It appears in three places:
    - The Estimate toolbar, after Export.
    - The workspace header actions (`SubmissionHeaderActions`), so it is the Overview's primary action.
    - The review panel, beside "All requested reviews approved. Baseline can be set." (mockup @494746). Remove 9.4's "no Set Baseline" test assertion.
- **Web: confirm dialog (mockup @578122):**
  - 480px card, title "Set Baseline for Estimate v{n}?".
  - An "Approvers" eyebrow, then rows of "{Name} · {Type} review" with a green pill (check-circle) reading "Approved {d Mon yyyy}".
  - An amber warning banner with a triangle icon: "This cannot be undone. A Baseline is replaced only by a newer approved version."
  - Buttons: Cancel (outline) and Set Baseline (primary).
  - Errors: 409 shows the blockers inline (`role="alert"`, as `SubmitEstimate` does), and 412 shows "Changed since you opened it." with Reload.
  - On success: `announce("Estimate v{n} is now the Baseline")`, `submission.refresh()`, `router.refresh()`.
- **Web: marker and stepper:**
  - "Baseline" pill: `--resolved-tint` with `--resolved` text and the `AnchorIcon`. It replaces the status pill wherever the Baseline version is shown: Estimate toolbar, review panel header, Overview card, and the Opportunities list estimate cell ("Baseline v{n}" when the summary's version is the Baseline; add `is_baseline` to the list summary).
  - `lifecycleSteps` makes all four steps passed (green ✓) for the Baseline version.
  - Note: "v{n} is the Baseline. A Baseline is replaced only by a newer approved version, and editing it creates a new version."
- **Version switcher (decision 2026-10-26, option a: build it here; mockup @537900 and @625884):**
  - **Backend:**
    - `GET /opportunities/{id}/estimate-versions` lists every version with `{id, version, status, is_baseline, created_by_name, created_at, reason}`, Baseline first, then newest first.
    - `GET /estimate?version={n}` returns that version read only, with the same `EstimateView`. Without `version` it returns the current version, as today.
  - **Web, segmented control in the Estimate toolbar:**
    - It shows the Baseline (if any) followed by the two most recent versions, deduplicated.
    - Each segment is "v{n}" plus a state pill: Baseline (green, with the anchor), Draft (primary), Superseded/In review/Approved/Rejected (as `VERSION_TONES`).
    - The selected segment is `aria-pressed`. Selecting a segment sets `?version={n}` in the URL.
  - **Web, "All versions" outline button:** it opens the full list (number, pill, author, date, reason) with the Baseline first. The `v` key is bound only when single-key shortcuts are on.
  - **Selected version:**
    - A non-current selection is read only: no Edit line, Submit, Request review or New version.
    - The selection drives the stepper and its note.
    - Set Baseline applies to the selected version.
  - The diff (`d`) stays with 9.9.
- **Web: gate (`submission.tsx` `BaselineGroup`):**
  - "Blockers to Baseline · N" rows with a clock icon and links, plus the new kinds.
  - An approved version with an empty gate shows the mockup ready state: a green check-circle, "0 blockers to Baseline", and the sub-line "Every requested review approved. Set Baseline is now the primary action."
  - The pill reads "0 blockers".
  - When the version is the Baseline, the state reads "Estimate v{n} is the Baseline".
- **Web: Overview pipeline:** the review step is Complete, "Baseline set on v{n}", for the Baseline version.
- **Web: live updates and copy:**
  - Add `estimates.baseline.set` to `REVIEW_TRACE_EVENTS` and `BLOCKER_TRACE_EVENTS`.
  - Regenerate `schema.d.ts` from a fresh local uvicorn.

**Never:**
- No Scenarios.
- No undo or delete of a Baseline. No UPDATE or DELETE grant.
- No role checks in the browser.
- No Prettier on `web/`.
- No tests on the dev `psa` DB.
- Don't touch the other locks.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First Baseline | v3 approved, 2 approved requests, no blockers | row written, trace with approvers, status `baselined`, marker on v3 | N/A |
| Replace | Baseline v2, v4 approved, gate empty | v4 Baseline, trace `previous` = v2, v2 loses marker | N/A |
| Not newer | Baseline v4; set v3, v4 again, or draft/in_review v5 | nothing written | 409 `baseline_not_newer` |
| No request | v3 approved via no requests (legacy) | gate shows "No Review Request sent yet" | 409 `baseline_blocked` |
| Reopened blocker | v3 approved, a new open Conflict | gate lists it | 409 `baseline_blocked` listing `conflict` |
| Agent caller | agent/system actor | nothing written | 403 |
| Stale | old `If-Match` | nothing written | 412 |
| Race | reject and set_baseline concurrently | serialised: Baseline first, or 409 naming the rejected request | Postgres test (two engines, as `test_estimates_submit.py:501`) |
| Submit after Baseline | Baseline v2, submit v3 | v2 stays `approved` and Baseline | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/` -- new `locks.py`. Existing lock calls:
  - `modules/estimates/adapters/repository.py:97` (`lock_opportunity`) and `:706` (`lock_assumptions`); `application/review_status.py:95` re-exports `lock_for_review`; `versions.py:120-121` (order).
  - `modules/gaps/adapters/repository.py:146`.
  - `modules/assessments/adapters/repository.py:464` (findings).
  - Gap conversion: `modules/gaps/application/conversion.py` (its `actor.type != "user"` check at :33-40 is the human-only precedent).
- `modules/estimates/application/blockers.py:141-190`. `blockers_for` changes for non-draft versions. `models.py:293` `SubmissionBlockers`.
- `modules/estimates/application/submit.py:62-125` -- the template for `set_baseline` (authorize → lock → load → If-Match → rules → write → trace). Put it in a new `application/baseline.py` and export it from `public.py:95`.
- `modules/estimates/application/estimates.py:419` `version_view`, `:529` `get_estimate` (add an optional version number), `:615` `current_version`. Web: `app/opportunities/[id]/estimate.tsx` reads `getEstimate` and passes it to `EstimateSection`. Read `searchParams.version` there, and fit `EstimateSection` polling and edits to the selected version.
- `modules/estimates/adapters/repository.py:441` `supersede_submitted`; models and repo for the Baseline row; `domain/estimates.py:83-101` statuses.
- `modules/estimates/api/routes.py:486-533` -- the submit route and its If-Match and 409 docs (template).
- `modules/reviews/adapters/repository.py:129,297,366` (`of_version`, `DecisionRecord`, `latest_decisions`); `application/requests.py:669,692` (the pattern for `version_approvals`); `public.py:42-53`; `REVIEW_TYPE_LABELS`.
- `modules/opportunities/domain/opportunity.py:20-38`, `adapters/repository.py:51-69,199`; `tests/test_opportunities_filters.py:80`.
- `modules/identity/actions.py:22,~140-190` (action and category), `domain/policy.py:48-57,106,142,209`.
- `platform/trace/catalogue.py:20-22,572,800` and `platform/errors.py:240-249,299` (`EstimateVersionBlockedError` is the extension pattern).
- `migrations/versions/20261026_0050_review_outcomes.py` (head, grants pattern); spine `_bmad-output/planning-artifacts/architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md:320,427`.
- Tests: `tests/test_reviews_decisions.py` (helpers come from `test_reviews_requests.py:93,186,231`), `test_reviews_outcomes.py:148,160,630`, `test_estimates_submit.py:501` (two-engine lock test).
- Web (`web/src/`):
  - `components/opportunities/submission.tsx:60-196` (`SubmitEstimate` dialog, `aria-disabled`, error handling), `:203` `SubmissionHeaderActions`, `:236-372` card, `BlockersBody`, `BaselineGroup`.
  - `lib/submission.ts:17,50-75`.
  - `estimate-grid.tsx:124-135,466-560,1072-1106` (`VersionPill`, `EstimateHeader`, `VersionLifecycle`, slots).
  - `lib/estimates.ts:68-160`.
  - `review-panel.tsx:668-675` (+ test :602-613); `lib/reviews.ts:136,326`.
  - `lib/overview.ts:502-511`.
  - `opportunities-table.tsx:117-126`.
  - `app/opportunities/actions.ts:240,3207-3260` (`submitEstimateVersion` pattern).
  - `components/ui/dialog.tsx`, `ui/pill.tsx`; `components/shell/live-region.tsx:76`; `lib/opportunities.ts:3,58` (`AnchorIcon`).
- Mockup: `new-mockups/Presales Agent Design Spec (standalone).html`. Read slices with `tail -c +OFF | head -c N`:
  - Overview card @432300–435300 (eyebrow @434826)
  - Toolbar @537900–540300
  - Lifecycle @540200 (logic @648788, notes @649251)
  - Review panel @494746
  - Dialog @578122–580900
  - List @608154
- DESIGN.md: :359, :369–371. EXPERIENCE.md: :65, :94, :110–118, :150, :179, :211, :276.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/locks.py` + the call sites listed in the Code Map -- shared lock (AD-26).
- [x] `backend/migrations/versions/20261026_0051_estimates_baselines.py`, estimates `adapters/{models,repository}.py` -- table, grants, current and previous Baseline reads, supersede skip.
- [x] `backend/app/modules/estimates/application/{baseline.py,blockers.py,estimates.py,public.py}`, `api/routes.py` -- command, gate kinds, `baseline` in view, endpoints.
- [x] `backend/app/modules/reviews/application/{requests.py,public.py}` -- `version_approvals`.
- [x] `backend/app/modules/opportunities/{domain/opportunity.py,adapters/repository.py}` and the list summary -- `baselined`, `is_baseline`.
- [x] `backend/app/modules/identity/{actions.py,domain/policy.py}`, `platform/{trace/catalogue.py,errors.py}`, spine -- action, `HUMAN_ONLY_ACTIONS`, event, errors.
- [x] `backend/tests/test_estimates_baseline.py` (+ test updates for the lock rename, authorize, filters) -- every matrix row, append-only grants, migration down/up, race test.
- [x] `backend/app/modules/estimates/{application/estimates.py,api/routes.py}` -- versions list, `?version=` read (+ tests).
- [x] `web/src/lib/api/schema.d.ts` -- regenerate.
- [x] `web/src/components/opportunities/version-switcher.tsx` (new), `app/opportunities/[id]/estimate.tsx`, `app/opportunities/data.ts`, `estimate-grid.tsx` (+ tests with axe) -- segmented control, All versions list, read-only selected version.
- [x] `web/src/components/opportunities/{set-baseline.tsx,submission.tsx,estimate-grid.tsx,review-panel.tsx,opportunities-table.tsx}`, `lib/{estimates,submission,reviews,overview}.ts`, `app/opportunities/actions.ts` (+ tests with axe) -- button, dialog, marker, stepper, gate, pipeline, live events.

**Acceptance Criteria:**
- Given an approved version with an empty gate, when I press Set Baseline in the header, toolbar or review panel, then the dialog shows the mockup's approvers and warning, and on confirm the marker, stepper, gate, pipeline and Opportunity status all update without a reload, and the live region announces it.
- Given a blocked version, when the button renders, then it is `aria-disabled` and names the reason, and axe passes for the button, the dialog (with and without errors) and the ready gate.
- Given Baseline v2 and draft v3, when I open the Estimate tab, then the switcher shows v2 Baseline first, then v3 Draft. Selecting v2 shows its lines read only and a fully passed stepper, and the All versions list shows every version with the Baseline first.
- Given any agent run, when it calls `set_baseline`, then it is denied by `identity.authorize`.

## Implementation Notes

- Beyond the spec (implementation choices): `workflows` `lock_runs` takes the shared lock first (an accepted Gap detection queues a run under the shared lock while finishing a run builds an Estimate under it, so the run lock must come second); Gap detection takes the shared lock too (the `gaps` repository had one lock for detection and dismissal); sales representatives can't set the Baseline (as submit); `can_set_baseline`/`is_current` on the Estimate view and `version_gate` on the review panel keep role checks out of the browser; `schema.d.ts` was regenerated from a dumped `app.openapi()`.
- The race test passes the post-rejection `row_version`, because a rejection bumps the version and a stale `If-Match` would 412 before the blocker rules run.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-26). Layers: Blind Hunter (BH), Edge Case Hunter (EC), Verification Gap (VG).

| # | Layer | Finding | Verdict | Evidence / route |
|---|-------|---------|---------|------------------|
| 1 | VG, EC | Lock-order cycle: Red Team / Critic accept take their module lock, then `stamp` takes the shared lock; drafting takes the shared lock, then `enqueue_review` takes the Red Team lock | high | `review.py:230,114`, `critic.py:355`, `findings.py:133`, `draft.py:393`. Before 9.7 `stamp` used the separate `assessments.findings` key. Patch: shared lock first. |
| 2 | BH, EC | A replaced Baseline (still `approved`, empty gate) is offered Set Baseline, which then 409s `baseline_not_newer` | medium | `VersionGate`/blockers view carry no Baseline number; `targetOf`/`baselineTargetOf` never set `baselineVersion`. Patch: expose it and disable with the not-newer reason. |
| 3 | BH | Disabled reason for superseded/rejected versions says "must approve first" | low | `setBaselineReason` fallback. Direct fix. Patch. |
| 4 | BH | Choosing an older version from All versions leaves no segment pressed | medium | `switcherVersions` = Baseline + two newest. Patch: add the selected version. |
| 5 | BH | `loadEstimate` ternary repeated four times, lines over 100 columns | low | Direct fix. Patch. |
| 6 | EC | `?version=` above int4 max returns 500 | low | Direct fix (`le=`). Patch. |
| 7 | VG | No race test for the Gap/Finding commands moved onto the shared lock | gap | Patch: two-engine Gap reopen test; plus an `in_review` not-newer case (BH). |
| 8 | VG | The `pinned` reload of an earlier version is untested | gap | Patch: `loadEstimate(OPP_ID, 2)` test. |
| 9 | BH | Conflict and intake writers keep their own locks, so a new Conflict or Requirement can commit alongside `set_baseline` | medium | Real, but the frozen intent keeps those locks ("Keep the other locks: conflicts, intake…"). Defer. |
| 10 | BH, EC | Lock key from a UUIDv7's first 8 bytes has only 12 random bits | low | `ids.py:15-19`. Only same-millisecond Opportunities share a key (spurious serialisation, no wrong result); the key derivation is in the frozen intent. Rejected. |
| 11 | EC | Locks keys differ from the old ones during a rolling deploy | low | Local single-process deploys only; prod rollout is out of scope. Rejected. |
| 12 | EC | `create_version` can start from an old approved Baseline while a newer version is in review | false | Intended: the Baseline note says "editing it creates a new version"; the one-draft rule still holds. |
| 13 | BH | `forbidden` and `not-found` share one message | low | Rare (stale panel); adds branches. Rejected. |
| 14 | EC | Unknown `?version=n` shows the generic load error | low | Rare (hand-typed URL); adds a branch. Rejected. |
| 15 | BH | `?version` stays in the URL after that version stops being current | low | The page shows it read only and the switcher returns to current. Rejected. |
| 16 | BH | Non-draft blocker reads run every content check plus a name lookup; `get_estimate(version)` computes unused blockers | low | No measured harm at R1 sizes; rejected. |
| 17 | BH | Baselines table lacks composite/unique constraints | low | Only `set_baseline` writes it, under the lock, with INSERT-only grants. Rejected. |
| 18 | BH | Version reasons are read from trace payloads | low | 9.4 stores the reason only on the trace event; moving it needs a migration. Rejected. |
| 19 | BH | `schema.d.ts` missing from the diff | false | Excluded from the review diff on purpose; the file is regenerated in the worktree. |
| 20 | BH | Spec and sprint statuses disagree; notes empty | false | Sprint status moves at step 5; notes filled now. |
| 21 | BH | Loose tests (403/404 for a reviewer, status filter, escalated approver id, grants after re-upgrade) | low | Rejected except the `in_review` not-newer case (folded into #7). |
| 22 | EC | `locks.py` docstring claims the lock order holds | high | Same root cause as #1; fixed by #1. |

## Design Notes

- **Why the content checks join `to_baseline`.** AC: `set_baseline` requires `get_submission_blockers(version)` to return nothing. A version that has passed submit can still gain a new Conflict or Gap, so the gate must show those blockers, or the button would be enabled and then fail.
- **Primary on the Overview.** The mockup doesn't draw Set Baseline on the Overview. The workspace header (where Submit lives) is visible on the Overview, which satisfies the epic without inventing a new layout.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-97` (branch `task/story-9-7-set-baseline`). Work only there, and don't commit or push. Test DB `psa_test97`: create it if missing, and take only the two DB URLs from `.env`, with the host swapped to `127.0.0.1`.

**Commands:**
- `cd backend && uv run pytest tests/test_estimates_baseline.py tests/test_estimates_submit.py tests/test_reviews_decisions.py tests/test_reviews_outcomes.py tests/test_gaps*.py tests/test_architecture.py tests/test_trace_catalogue.py tests/test_authorize.py tests/test_opportunities_filters.py` -- expected: pass.
- Full backend suite on `psa_test97` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
