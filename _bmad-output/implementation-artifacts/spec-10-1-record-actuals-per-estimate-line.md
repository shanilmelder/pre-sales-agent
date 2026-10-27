---
title: 'Story 10.1: Record Actuals per Estimate line'
type: 'feature'
created: '2026-10-27'
status: 'done'
baseline_commit: '126d06989d3a89c6cbb59db19ac11f9b94f8741a'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-7-set-the-baseline.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A Baseline (9.7) is the committed figure, but nothing records what delivery actually took. The Actuals tab (key `8`) reads "Not available yet.", so estimate-vs-actual history cannot start.

**Approach:** Add an `actuals` module that owns `actuals_actuals` (versioned, one current Actual per Baseline line plus any number of Unplanned work entries) and `actuals_deliveries` (Close delivery record). Writes go through the single mutation path and are allowed only to users who hold the delivery manager role and can read the Opportunity. Build the Actuals tab exactly as the **new mockup** draws it: a header with subtitle and **Save Actuals**, a five-column table (Line, Estimate h, Actual h editable, Variance, Variance cause) where hours and cause are edited inline, and the footnote. The Inspector holds the full Actual form (kind, milestone label, duration, cost, note, failed Assumptions, history).

## Boundaries & Constraints

**Always:** Variance in hours and percent is computed server-side (domain function, unit-tested) and returned on the view. Effort uses `numeric(10,1)`, cost uses integer minor units plus ISO-4217, and the UI shows figures with `tabular-nums`. Variance is amber when over and green when under, always with a `+`/`−` sign and a label; never red here. Lines with no Actual show "—" and "Not recorded" and are excluded from variance. A final Actual that differs from the estimate needs a cause, and `other` also needs a note. Failed Assumption refs must come from the Actual's own Baseline version register and are stored with the Assumption version. Unplanned work needs an Integration Type or Work Package and a cause in {`scope_change`,`unknown_requirement`,`other`}, and it counts in total variance. A correction makes a new version with a required reason, `If-Match`, and a 412 when stale. Each write appends its trace event (`actuals.actual.recorded`, `.corrected`, `actuals.delivery.closed`) in the same Unit of Work. Close delivery is disabled with "N lines have no final Actual" until every line has a final Actual; once closed, derived status is `delivered` (domain `derived_status` and SQL `status_expression` change together). Every Actual stays tied to the version it was recorded against; on mismatch show "Actuals recorded against v3; the current Baseline is v5". Other roles get a read-only view and 403 on writes.

**Never:** No file import parsing (Story 10.2), no Reports or `reporting_*` views (10.3), no drill-down (10.4), no purge step (10.6). No red variance, no browser-computed variance, no editing a trace row, no overwriting an Actual in place. Don't add cost or rates to Estimate lines.

**Decisions (2026-10-27):**
- Variance is hours and percent only. Actual cost and currency are recorded in the Inspector, and the view returns cost variance as `null` until Estimate lines carry a cost. Don't add cost to Estimates.
- Planned-line Actuals store the Integration Type IDs derived from the line's Requirements; Work Package is left empty. Unplanned work takes the Integration Type or Work Package the delivery manager picks.
- **Import from file** renders disabled in the header, with the tooltip "Import arrives in a later release".
- The full scope stays in this story (no split), at about 2,300 tokens.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Record over | Line est 36 h, final Actual 41 h, cause `estimation_error` | Variance "+5.0 h (13.9%)" amber; `recorded` event | N/A |
| Missing cause | Final 41 h vs 36 h, no cause | Not saved | 422 problem+json, field error on cause |
| `other` without note | cause `other`, empty note | Not saved | 422 on note |
| Milestone | kind `milestone`, no cause | Saved; cause optional | N/A |
| Foreign Assumption | ref from another version | Not saved | 422 |
| Unplanned bad cause | no line, cause `customer_delay` | Not saved | 422 |
| Stale correction | old `If-Match` | Not saved | 412 + InlineAlert Reload |
| Non-DM write | presales engineer POST | Not saved | 403 |
| No Baseline | Opportunity not baselined | "No Baseline yet. Actuals are recorded against the Baseline." | N/A |
| No Actuals | Baseline, zero Actuals | EmptyTabCard "No Actuals recorded" / Record Actuals | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/actuals/` (new) -- `domain/actuals.py` (causes enum, kind, `variance(est, act)`, validation rules), `adapters/models.py` + `repository.py`, `application/{record.py,view.py,deliveries.py,public.py,models.py}`, `api/routes.py`. Template: `modules/estimates/application/baseline.py::set_baseline` (l.92; readable_resource → authorize → `platform/locks.opportunity_lock` → load for update → `platform/concurrency.parse_if_match` → rules → write → `platform/trace/writer.append`). Reason + If-Match example: `reviews/application/challenges.py:435,713`.
- Wiring: `app/main_api.py:38,156`; `migrations/env.py:24`; `identity/actions.py` (`Action` + `ACTION_CATEGORIES`, see l.192); `identity/domain/policy.py:81,115,159,194,217,224` (add a member grant that also requires `Role.DELIVERY_MANAGER`, `identity/domain/roles.py:20`; HUMAN_ONLY); `scripts/seed_auth0.py:50,95`; `platform/trace/catalogue.py` (pattern `EstimatesBaselineSet` l.835); `pyproject.toml` importlinter l.358,381; web trace labels `web/src/lib/trace.ts`.
- `estimates/application/public.py` -- export `current_baseline_ref` (`baseline.py:87`), `version_lines` (`line_refs.py`, `LineRef`), and add `version_assumptions(uow, version_id)` wrapping `repo.assumptions_of` (`repository.py:846`). Line labels "L{n}" come from section + position order.
- `opportunities/domain/opportunity.py:21-38` (`DELIVERED` exists, `derived_status`) and `adapters/repository.py:52-69` `status_expression` (EXISTS on `table("actuals_deliveries")`).
- Migration `backend/migrations/versions/20261027_0053_actuals_actuals.py`, down revision `0052_estimates_baselines`.
- Web: `lib/workspace.ts:12` (tab exists, key 8); `app/opportunities/[id]/[tab]/page.tsx` (replace `TAB_NOT_AVAILABLE` for actuals) + new `[id]/actuals.tsx` (model: `[id]/estimate.tsx`) + fetcher in `app/opportunities/data.ts` + server actions in `app/opportunities/actions.ts`; new `components/opportunities/actuals-table.tsx` and `actual-inspector.tsx`; reuse `ui/{table,button,select,input,textarea,empty-tab-card,inline-alert,tooltip}`, `opportunities/reason-input.tsx`, `shell/read-only-notice.tsx`, `shell/right-pane.tsx`. Gate on view `can_record`. Run `npm run gen:api`.
- Mockup: `ux-designs/.../new-mockups/Presales Agent Design Spec (standalone).html` — the `<!-- ACTUALS -->` block (grid `minmax(0,1fr) 90px 100px 130px 220px`, row pad `calc(var(--rowpad)+4px) 20px`, Actual h and cause boxed `border2`/`bg` 8px radius) and its data at offset ~649328. EXPERIENCE.md:55,123,137.
- Tests to update: `web/src/app/opportunities/pages.test.tsx:2323,2512`, `workspace-tabs.test.tsx`. Baseline helpers: `tests/test_estimates_baseline.py:49,94,129`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/actuals/domain/actuals.py` + `tests/test_actuals_domain.py` -- causes, kinds, variance and validation as pure functions -- deterministic numbers.
- [x] Migration 0053 + `adapters/models.py`/`repository.py` -- `actuals_actuals` (AC columns plus `actual_group_id` for versions, `is_current`, `correction_reason`) and `actuals_deliveries` -- storage.
- [x] `estimates/application/public.py` -- export the Baseline, line and Assumption readers -- the cross-module boundary.
- [x] `identity` actions, policy, seed and trace catalogue -- `actuals.actual.record`, `actuals.actual.correct`, `actuals.delivery.close` (DM role + read access) -- authorisation.
- [x] `actuals/application/*` + `api/routes.py` -- `GET /opportunities/{id}/actuals` (view incl. variance, totals, version mismatch, `can_record`, close-delivery count), `POST` batch save (records and corrections; reason required if any is a correction), `POST /actuals/{id}/corrections`, `POST .../delivery/close` -- commands.
- [x] `opportunities` domain + `status_expression` -- `delivered` status -- derived status.
- [x] `tests/test_actuals_*.py` -- the I/O matrix, 403 per role, 412, trace events, status agreement between domain and SQL.
- [x] Web tab, table, inspector, actions + tests (vitest, axe) -- per mockup.

**Acceptance Criteria:**
- Given a DM edits two lines inline and one already had an Actual, when they choose Save Actuals, then a reason is asked for once and both save in one Unit of Work, with one `recorded` and one `corrected` event.
- Given every line has a final Actual, when the DM chooses Close delivery, then `actuals.delivery.closed` is appended and the Opportunity list shows `delivered`.
- Given a reviewer, when they open the tab, then it renders read-only with no editable cells and no actions.

## Implementation Notes

- Concurrency: Save Actuals and Close delivery take `If-Match` = the tab's `row_version`, which is the count of `actuals_actuals` rows plus `actuals_deliveries` rows for the Opportunity (rows are insert-only, so it grows with every write); a correction via `POST …/actuals/{id}/corrections` takes the Actual's `version` and is 412 when stale or no longer current.
- Grants: `psa_app` has SELECT, INSERT and a column-level `UPDATE (is_current)` on `actuals_actuals` (a correction clears the old version's flag), SELECT and INSERT on `actuals_deliveries`. No cross-module FKs except the Opportunity (AD-2).
- Authorisation: `actuals.actual.record`, `.correct` and `actuals.delivery.close` are in `OWNER_GRANTS`/`MEMBER_GRANTS`, narrowed by the new `RELATION_REQUIRED_ROLES` to holders of `delivery_manager`, and in `HUMAN_ONLY_ACTIONS`; the seed also gives delivery managers the three permissions (the API checks read access first, so a non-collaborator DM gets 404).
- Choices beyond the spec: once delivery is closed every Actuals write is 409 `delivery_closed` (and `can_record` is false); the 422 is `actual_invalid` with an `errors` extension `[{item, field, message}]`; a zero variance reads "±0.0 h (0.0%)" ("On estimate"); a milestone label is optional; planned-line Actuals ignore any Integration Type / Work Package in the body. The table shows the current Baseline's lines; Actuals against an earlier Baseline are only counted in the mismatch note. Unplanned work is listed under the table with an **Add Unplanned work** action (Inspector), and the total variance is shown beside **Close delivery** (neither is drawn in the mockup). Cost is entered in minor units in the Inspector.
- Live updates: the tab re-reads on `actuals.*` trace frames unless it has unsaved edits.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-27). B = blind-hunter, E = edge-case-hunter, V = verification-gap.

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| B1 | Close delivery is irreversible, with no confirm step | medium | `actuals-table.tsx:243` `onClose` posts on click; after that every write is 409 `delivery_closed` | patch (confirm dialog). A reopen action is out of scope |
| B2/E5 | A Baseline re-set after delivery closed breaks the delivered tab | medium | `estimates/application/baseline.py::set_baseline` never checks `actuals_deliveries`; `build_view` uses the current Baseline's lines | patch: once delivery is closed, `build_view` shows the closed version's lines and totals |
| B3/E7 | Inspector submit can be sent twice | medium | `actual-inspector.tsx:156` `save()` has no `busy` guard; the button only sets `aria-disabled` | patch |
| E8 | A live frame remounts the Inspector and discards its edits | medium | `actuals-table.tsx:131` `apply()` bumps `targetKey`; the reload guard at :149 checks only table `dirty` | patch: skip the live reload while the Inspector has unsaved edits |
| B4 | Trace payloads omit duration, cost, currency, milestone label, IT/WP | medium | `catalogue.py` `ActualsActualRecorded`/`Corrected` carry effort, cause and assumptions only; a cost-only correction leaves no visible change | patch: add the non-text fields |
| B7/E9 | Cost formatting assumes 2 decimals | low | `lib/actuals.ts:209` divides by 100 for every currency (JPY, BHD wrong); one-line fix | patch |
| B12a | No Baseline still shows Save Actuals and Import | low | `view.py` `_empty()` passes `can_record` through | patch: `can_record=False` without a Baseline |
| B12b | A 403 on Close delivery shows the generic text | low | `onClose` falls through to `SAVE_FAILED`; the save path has a specific message | patch |
| B12c | UTC `slice(0,10)` dates can be a day off | low | `actuals-table.tsx:586`, `actual-inspector.tsx:79` | patch: format in local time |
| B8 | Cause chosen on a line with blank hours is silently dropped | low | `changedItems` skips blank hours; an everyday interaction | patch: mark the hours cell "Enter hours to record this line" |
| E1/O1 | The same Unplanned `actual_id` twice in a batch gives 412, not 422 | low | `record.py` `seen` holds line ids only; the second `retire` returns False | patch: dedupe `actual_id` |
| V1 | Close delivery 412 and 428 untested | gap | the `_close` helper always sends a fresh tag | patch: tests |
| V2 | Unplanned correction via Save untested | gap | no test body sets `actual_id` | patch: tests |
| V3 | Correction after a newer Baseline untested | gap | `test_actuals_stay_tied_to_their_version` only reads | patch: tests |
| V4 | Actuals server actions untested | gap | `actions.test.ts` has no Actuals block | patch: tests |
| V5 | Inspector save paths untested | gap | the only Inspector test renders and submits nothing | patch: tests |
| V6 | Live re-read untested | gap | no EventSource stub in the Actuals tests | patch: tests |
| B11 | Epic context says tab `9` | low | `epic-10-context.md:46`; the code and spec say `8` | patch (doc) |
| B11b | sprint-status is in-progress while the spec is in-review | false | by design: step 5 syncs sprint status | reject |
| B11c | Triage log empty | false | this table | reject |
| B10a | `workspace-tabs.test.tsx` not updated | false | the tab already existed; the test passes unchanged (135/135) | reject |
| B5 | N+1 queries under the lock | low | the 500 ms P95 applies to Reports, not this tab; batching adds complexity | reject |
| B6 | Older-Baseline Unplanned work isn't listed in the UI | low | shown in the mismatch note, as the spec states; rare | reject |
| B9 | Inline edit keeps a milestone a milestone | low | the Inspector switches kind; the Design Notes cover only new entries | reject |
| E2 | IT/WP on a planned-line item is silently ignored | false | decided: planned lines derive IT from Requirements (Decisions) | reject |
| E3 | Zero-line Baseline lets Close delivery run | maybe-false | needs proof that an empty Estimate can be baselined (blockers probably prevent it); would be low | reject |
| E4 | ETag ignores a Baseline change | low | the server re-checks every line has a final Actual, and Save rejects foreign lines with 422 | reject |
| E6 | Cost above 2^53 is rounded | low | not a realistic amount; adds input guarding | reject |

## Design Notes

One current Actual per line keeps the variance unambiguous. `kind` says whether it is final, and moving from milestone to final is a correction. Inline cells record final Actuals by default; milestone entry is done in the Inspector.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_actuals_* tests/test_architecture.py tests/test_opportunities_filters.py -q` -- expected: pass
- `cd backend && uv run lint-imports && uv run ruff check . && uv run mypy app` -- expected: clean
- `cd web && npm run gen:api && npm run typecheck && npm test -- actuals pages workspace-tabs && npm run lint` -- expected: pass

**Manual checks:**
- Screenshot the Actuals tab and compare it side by side with the mockup's Actuals screen.
