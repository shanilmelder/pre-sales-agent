---
title: 'Story 10.5: Record the Opportunity outcome and retention dates'
type: 'feature'
created: '2026-10-27'
status: done
baseline_commit: '56a196953714557f3eed36aadfbd10030389281e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-1-record-actuals-per-estimate-line.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing records whether an Opportunity was won or lost, so the platform cannot know how long its data must be kept, and the derived status never reaches `closed`. Story 10.6 (purge) needs a retention date per Opportunity.

**Approach:** The `opportunities` module gains `outcome` (`won|lost`, null while open), `outcome_recorded_at` and `contract_end_date`, changed only through four commands: record outcome (lost with reason; won with contract end date, needs a Baseline), change contract end date (reason), and reopen (reason). Retention is pure domain code: lost = `outcome_recorded_at` + 3 years, won = `contract_end_date` + 7 years, open = none. The Opportunity response carries `outcome`, `contract_end_date`, `retention_until` and capability flags; the Overview shows the outcome line and the actions.

## Boundaries & Constraints

**Always:** Every command follows the mutation path (`_load_readable` → `identity.authorize` → domain rules → `If-Match` on the Opportunity `row_version`, 412 stale / 428 missing → write → `trace.append`) in one Unit of Work. Each write appends `opportunities.opportunity.closed` (outcome, reason or contract end date, retention date), `opportunities.contract_end_date.updated` (old, new, reason) or `opportunities.opportunity.reopened` (previous outcome, reason); no customer content beyond the reason. Close as lost: owner (not sales-rep-only) or Head of Delivery. Mark as won: owner or Head of Delivery, Baseline required (409 otherwise). Change contract end date: Head of Delivery or platform administrator, only when won. Reopen: Head of Delivery or platform administrator; clears outcome, recorded-at and contract end date. Recording when an outcome exists is 409 `outcome_already_recorded`. Retention dates use calendar years (29 Feb → 28 Feb). Domain `derived_status` and SQL `status_expression` change together. Dates display as "14 Oct 2029". Confirm dialogs follow the mockup's Challenge dialog shell (520px, title, "Reason (required)" textarea, right-aligned Cancel + primary disabled until valid); date inputs use the mockup input style. Other roles see the line read-only, with no actions, and get 403.

**Never:** No purge job or Admin → Retention page (10.6). No CRM pipeline stages. No read-only lock of other tabs after close. No editing or deleting trace rows. No retention arithmetic in the browser.

**Decisions (2026-10-27):**
- Only `lost` derives status `closed` (highest precedence). A won Opportunity keeps its derived status (`baselined`/`delivered`); the Overview line shows the outcome.
- The actions live in a new **Outcome** card on the Overview (label/value rows in the mockup's 90px/1fr style, the retention line, then the actions). The header stays exactly as the mockup draws it.
- The full scope stays in one spec (about 1,900 tokens).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Close as lost | Owner, open, reason, recorded 14 Oct 2026 | status `closed`; Overview "Lost — data kept until 14 Oct 2029"; `closed` event | N/A |
| Lost, no reason | blank reason | Not saved | 422 on `reason` |
| Mark as won | HoD, Baseline, contract end 30 Jun 2028 | "Won — data kept until contract end plus 7 years (30 Jun 2035)"; status stays `baselined` | N/A |
| Won, no Baseline | owner, no Baseline | Not saved | 409 `baseline_required` |
| Won, no date | missing `contract_end_date` | Not saved | 422 |
| Second outcome | outcome exists, owner records again | Not saved | 409 `outcome_already_recorded` |
| Change contract end | HoD, won, new date + reason | retention recomputed; event | owner → 403; lost → 409 |
| Reopen | HoD/admin, reason | outcome null; status re-derived; event | owner → 403 |
| Stale | old `If-Match` | Not saved | 412 |
| Leap day | lost recorded 29 Feb 2028 | retention 28 Feb 2031 | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/opportunities/domain/opportunity.py:21-43` -- `OpportunityStatus` (`CLOSED` exists), `derived_status(has_baseline, delivered)`; add `outcome` parameter, `Outcome` enum and `retention_until(outcome, recorded_at, contract_end)`.
- `backend/app/modules/opportunities/adapters/models.py:26` `OpportunityRow`; `adapters/repository.py:71` `status_expression` (CASE, also used by list filter :228), `_COLUMNS` :88, `bump_row_version` :305, `update_fields` :320.
- `backend/app/modules/opportunities/application/opportunities.py` -- template `update()` :367-436, `_load_readable` :97, `_detail` :115; similar close/reason command `modules/actuals/application/deliveries.py:41`. Response `application/models.py:175` `Opportunity` (+ request models like `OpportunityChanges` :65); re-export in `application/public.py`.
- `backend/app/modules/opportunities/api/routes.py` -- `IfMatchHeader` :70, `_with_etag` :76, `_responses`, PATCH pattern :261.
- `backend/app/modules/identity/actions.py` (`Action`, `ACTION_CATEGORIES`), `identity/domain/policy.py` (`OWNER_GRANTS` :127, `RELATION_EXCLUDED_ROLES` :84, `HUMAN_ONLY_ACTIONS`), `backend/scripts/seed_auth0.py:50` (HoD :82, admin :51).
- `backend/app/platform/trace/catalogue.py:96-113` (opportunities payloads, `OpportunitiesOpportunityUpdated` pattern); web labels `web/src/lib/trace.ts`.
- Migration `backend/migrations/versions/20261027_0057_opportunities_outcome.py`, down revision `0055_reporting_views`; check constraint `outcome IN ('won','lost')`, won ⇒ contract_end_date not null.
- Web: `web/src/app/opportunities/[id]/overview.tsx`, `components/opportunities/overview-summary.tsx`, `lib/overview.ts`; `workspace-header.tsx`; dialog `components/ui/dialog.tsx` + `opportunities/reason-input.tsx` (model: Close delivery dialog in `actuals-table.tsx`); date input `inline-field.tsx:447`; server actions `app/opportunities/actions.ts` (`updateOpportunity` :481 If-Match); pill `lib/opportunities.ts:60`. Run `npm run gen:api`.
- Tests: `backend/tests/test_opportunities.py` helpers (`_create`, `_events`, `_if_match`, `_user`), baseline helpers `tests/test_estimates_baseline.py`; new `tests/test_opportunities_domain.py`, `tests/test_opportunities_outcome.py`; web vitest beside files (`workspace-header.test.tsx`, `actions.test.ts`).

## Tasks & Acceptance

**Execution:**
- [x] `opportunities/domain/opportunity.py` + `tests/test_opportunities_domain.py` -- `Outcome`, `retention_until`, `derived_status` with outcome -- deterministic retention.
- [x] Migration 0056 + `adapters/models.py`/`repository.py` -- columns, constraint, status CASE, fields -- storage.
- [x] `identity` actions/policy/seed + trace catalogue -- `opportunities.outcome.record`, `opportunities.contract_end_date.update`, `opportunities.outcome.reopen`; three events -- authorisation and audit.
- [x] `opportunities/application/*` + `api/routes.py` -- `POST /opportunities/{id}/outcome`, `PATCH .../contract-end-date`, `POST .../outcome/reopen`; response fields `outcome`, `outcome_recorded_at`, `contract_end_date`, `retention_until`, `can_record_outcome`, `can_change_contract_end`, `can_reopen_outcome` -- commands.
- [x] `tests/test_opportunities_outcome.py` -- I/O matrix, 403 per role, 412/428, events, list status agrees with domain.
- [x] Web: server actions, outcome UI, dialogs, trace labels + vitest/axe -- per mockup patterns.

**Acceptance Criteria:**
- Given a lost Opportunity, when the Opportunities list is filtered by `closed`, then it appears and its pill reads "Closed" (neutral).
- Given a reviewer or sales representative, when they open the Overview, then the outcome line shows and no outcome actions render.

## Implementation Notes

- Commands live in `opportunities/application/outcome.py`. Order: `_load_readable` → `authorize` → 409 state checks (`outcome_already_recorded`, `outcome_not_won`, `outcome_not_recorded`) → 422 `outcome_invalid` (`errors: [{field, message}]`, reason trimmed 1–1,000) → 409 `baseline_required` (won) → `If-Match` (428/412) → write → trace. Body shape errors (bad enum, unparseable date) stay FastAPI's 422 `validation_error`.
- `won` ignores any `reason`; `lost` ignores any `contract_end_date`. A contract end date after 9992 is 422 (retention would overflow). Changing the contract end date to the same date writes nothing (a stale `If-Match` is still 412).
- Grants: `opportunities.outcome.record` is an owner grant (sales-rep-only excluded) plus a Head of Delivery permission; `opportunities.contract_end_date.update` and `opportunities.outcome.reopen` are permissions only (Head of Delivery, platform administrator). All three are `HUMAN_ONLY`, category `write`. README and `seed_auth0.py` updated.
- DB: three nullable columns with checks `outcome IN ('won','lost')`, `(outcome IS NULL) = (outcome_recorded_at IS NULL)`, `COALESCE(outcome = 'won', false) = (contract_end_date IS NOT NULL)`. Lost retention uses the UTC date of `outcome_recorded_at`.
- The `opportunities.contract_end_date.updated` payload also carries `retention_until` (the recomputed date).
- Web: `OutcomeCard` sits between the summary cards and Details. **Mark as won** is disabled with "Mark as won once a Baseline is set." when the derived status is neither `baselined` nor `delivered` (the API checks again). One server action `changeOutcome` serves all four commands; 409/422 show the API's sentence, 412 the inline alert with Reload.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-28). B = blind-hunter, E = edge-case-hunter, V = verification-gap.

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| V1/B8 | Same-date contract end change: stale/missing If-Match untested | gap | `test_stale_and_missing_if_match` uses 2030-01-01 (≠ stored), so the branch at `outcome.py` same-date check is unreached | patch (test) |
| V2 | Body with both `reason` and `contract_end_date` untested | gap | every test goes through `_lost`/`_won` with one field | patch (test) |
| V3 | OutcomeCard newer-`initial` adoption untested | gap | `outcome-card.test.tsx` never calls `rerender` | patch (test) |
| B3/E1 | Contract end date has no lower bound; a typo gives a past retention date | low | true, but nothing purges until 10.6, and the HoD can correct it with a reason; a bound is a new rule the intent doesn't state | reject (note for 10.6 purge safeguards) |
| B7/E3/E4/E5 | 409 state checks run before the If-Match check, so a stale view gets 409 not 412 and keeps stale actions | low | order is the spec's (authorize → rules → If-Match); the 409 shows the API's sentence; concurrent outcome changes are rare and a fix adds reload branches | reject |
| B1 | Generated API types not updated | false | `schema.d.ts` was regenerated; it was left out of the review diff only (adds the three paths and fields) | reject |
| B2 | A closed Opportunity can still be edited | false | Never: "No read-only lock of other tabs after close" | reject |
| B4 | Lost reason not stored on the row | false | the reason is recorded in the `closed` trace event, as the story's AC requires | reject |
| B5 | `hasBaseline` guesses from status | low | every other status precedes a Baseline; the API re-checks | reject |
| B6 | Ignored field silently dropped | low | recorded decision in Implementation Notes; no data harm | reject |
| B9 | No tests for backstop/StrictStr/extra=forbid | low | framework behaviour; unlikely inputs | reject |
| B10 | Retention date has no SQL twin for the purge | false | epic allows pure domain code; 10.6 owns the purge query | reject |
| B11 | "3 years from today" vs UTC date | low | off only near midnight, helper copy only | reject |
| B12 | Field errors dropped in the web | low | one dialog, one message shown; the UI already validates both fields | reject |
| B13 | Trace payload not rendered; `closed` name used for won | false | event name is fixed by the epic (`opportunities.opportunity.closed`); trace labels added | reject |
| B14 | `_iso` relies on `assert` | false | callers pass an outcome with its date, so `retention_until` is never None there | reject |
| B15 | README lacks a re-seed note | low | permissions are documented in the role table; seeding is the standard step | reject |
| E2 | Year > 9992 stored outside the API → 500 on GET | false | no write path other than the validated commands | reject |
| E6 | Reason > 4,000 raw chars but ≤ 1,000 trimmed | low | absurd input; generic message still shown | reject |
| E7 | Impossible date like 2026-02-31 | false | the dialog uses `type="date"`, which yields only real dates | reject |

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_opportunities* tests/test_trace_catalogue.py tests/test_architecture.py -q` -- expected: pass
- `cd backend && uv run lint-imports && uv run ruff check . && uv run mypy app` -- expected: clean
- `cd web && npm run gen:api && npm run typecheck && npm test -- overview workspace-header actions && npm run lint` -- expected: pass

**Manual checks:**
- Screenshot the Overview with a lost and a won Opportunity and the Close as lost dialog; compare with the mockup's Overview and Challenge dialog.
