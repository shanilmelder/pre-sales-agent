---
title: 'Story 8.5: Assumptions Register and Risks'
type: 'feature'
created: '2026-10-24'
status: 'done'
baseline_commit: '3b3413ef4da891014683fc5c0837dc0d81f76f4d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-4-gaps-to-assumptions.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-estimate-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Register shipped as a demo slice (Story 8.4 + 8.5 demo scope): Gap-origin Assumptions with Accept and Accept all. Nobody can correct an Assumption's wording, hours, kind or line. A superseded origin looks current. There are no Risks. So the presales engineer can't defend what the Estimate depends on.

**Approach:** Finish 8.5 on the redesigned Estimate tab, using the new mockup's row anatomy (`A{n}` ID, wording, "{kind} · from {origin}: {title}", status, Accept). Add an **Assumption inspector** with an Edit section, styled like the Edit line form. Show origin versioning. Add a Risks card styled like the Assessments Findings table. Make every action read-only off the draft.

## Boundaries & Constraints

**Always:**
- **Register rows:**
  - `A{position}` ID chip, then wording, then a muted "{Condition|Contingency · N.N h} · from {Gap|Unknown}: {title}" line, an optional "Line: {title}", and the status.
  - An Unknown is a Gap whose `why_it_matters` starts with "Unknown to the customer:" (gaps domain). The chip says "from Unknown".
  - The header keeps the mockup pill ("{n} not accepted block submit" / "All accepted"). The live region keeps "7 · 6 accepted · 1 not accepted".
  - The Contingency group total stays server-calculated.
- **Opening a row:** clicking the row, or Enter on it, opens the Assumption inspector:
  - kind, ID, wording, hours and line;
  - origin card (title, impact, why it matters, status);
  - "Accepted by {name} · {date}" or "Not accepted" with **Accept**;
  - an **Edit Assumption** section.
  The origin chip keeps opening the origin Gap inspector.
- **Superseded origin:** the origin is superseded when the Gap's status is not `open` or `converted`, or its `row_version` differs from `origin_ref.row_version`. The read model returns `origin_superseded: bool`. The chip title is then struck through, with a "superseded" text label (never colour alone).
- **Edit:** `PATCH /opportunities/{id}/assumptions/{aid}` with `If-Match` and the fields wording, kind, amount_hours, line_id and reason.
  - Validation: the 8.4 rules (wording 1–500 characters; a Contingency needs 0.5–1,000 h, rounded to 0.1; a Condition has no hours and no line). The reason uses the line-edit `REASON_RULE`.
  - Action `estimates.assumption.edit`, granted like `estimates.assumption.accept`.
  - Locks are taken in the same order as `accept_assumption`. A version that isn't a draft → 409 `estimate_version_not_draft`. Stale → 412 "Changed by {name} since you opened it.". No change → 200, no-op.
  - Otherwise: update the row, bump `row_version`, and clear `accepted_by` and `accepted_at`. A kind change on a converted Gap updates `gaps_gaps.converted_to` through gaps `public.py`. Trace `estimates.assumption.edited`: before/after (kind, hours, line_id, wording length, never the text) and the reason length.
  - Grid totals refresh from the server.
- **Edit form:** a Condition/Contingency segmented control (a small local radio group; there is no SegmentedControl primitive), a wording textarea, an hours input (Contingency only), a line select (Contingency only, "No line" = unallocated), and a required reason.
  - **Save change** is disabled until something changed, the values are valid and a reason is typed. The hint reads "Saving clears the acceptance. Recorded in the Decision Trace."
  - On 412: the existing `InlineAlert` and Reload.
- **Carry (extends 8.7 `carry_accepted`):** a re-draft carries every Assumption whose origin Gap is `converted`, accepted or not. An Assumption made unaccepted by an edit stays unaccepted when carried. This way an edited Assumption never vanishes while its Gap stays converted.
- **Grouping (decided):** keep the Conditions (clipboard-check) and Contingencies (shield-plus) groups and the Contingency total in that group's header. Inside each group use the mockup row anatomy above.
- **Risks (decided: Convert to Risk):**
  - **Table `estimates_risks`** (migration `0041`): `id`, `version_id`, `position`, `description` (1–500), `likelihood` and `impact` (`low|medium|high`), `origin_ref` (`{kind:"gap", id, row_version}`), `created_by`, `created_at`, `carried_from`, and row_version. Migration `0041` also widens the `gaps_gaps.converted_to` check to allow `risk`.
  - **Convert:** `POST /opportunities/{id}/risks` with `{gap_id, description, likelihood, impact}`, action `estimates.risk.create`.
    - It needs the current draft (409 `no_draft_estimate` otherwise) and the Gap must be `open` (409 `gap_not_open`).
    - It takes the same locks as accept. In one Unit of Work it creates the Risk, calls `gaps.mark_converted(kind="risk")` and deletes this draft's unaccepted Assumption proposed for the same Gap.
    - Traces `estimates.risk.created` and `gaps.gap.converted`.
  - **Edit:** `PATCH /opportunities/{id}/risks/{rid}` with If-Match, description, likelihood, impact and reason, action `estimates.risk.edit`. Same not-draft, 412 and no-op rules as the Assumption edit. Traces `estimates.risk.edited`.
  - **Who:** both actions are granted like `estimates.assumption.accept`.
  - **Not blockers:** Risks are never blockers and are never accepted.
  - **Carry:** a re-draft carries every Risk.
  - **Read API:** the version gains `risks: [{id, position, description, likelihood, impact, origin (as OriginGap + origin_superseded), row_version, carried_from_version}]` and `can_edit_risks`.
  - **Risks card** (below the Register, styled like `FindingsTable`): header "Risks · {n}". Columns: ID `R{n}`, Likelihood, Impact (label text plus an icon, High in red), and Risk (description plus the "from Gap: {title}" chip). Rows sort by impact, then likelihood. Clicking a row opens a Risk inspector: details, an origin card, and an **Edit Risk** section (selects plus reason, **Save change**). Empty: "No Risks yet. Convert a Gap to a Risk from the Gaps tab."
  - **Gaps tab:** the Gap inspector (`gap-inspector.tsx`) gets a **Convert to Risk** section for an open Gap when a draft exists and the user may create Risks.
    - Fields: Description (prefilled with the Gap title), Likelihood and Impact selects (Impact defaults to the Gap's impact), and the button **Convert to Risk**.
    - Converted rows read "Converted to Risk".
- **Read-only:** a version that isn't a draft (superseded today; submitted when 8.6 lands) and sales representatives see no Accept, Accept all, Edit or Risk edit controls.

**Never:** Finding-origin Assumptions or Risks (nothing creates them yet; 8.4 full), a manual Convert-to-Assumption form, accepting on behalf of another member, Risk acceptance, Risks in the 8.8 export, the submission gate (8.6), editing on non-draft versions, prettier on `web/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Edit wording | Accepted Condition A1, new wording + reason, current If-Match | 200; wording saved; row_version+1; accepted_by/at null; row is a blocker; event traced | N/A |
| Kind flip | Condition → Contingency 12 h on L2 | L2 Contingency +12.0; totals refresh; Gap `converted_to` = contingency | N/A |
| Invalid | Contingency without hours / Condition with line | 422 problem+json with field reason; nothing saved | Inline field error |
| No change | Same values | 200, no event, acceptance kept | N/A |
| Stale | Old If-Match | 412 "Changed by {name}…" | InlineAlert + Reload |
| Not draft | Assumption on superseded version | 409 `estimate_version_not_draft` | UI never offers Edit |
| Who | Sales rep PATCH | 403 | N/A |
| Superseded origin | Origin Gap re-detected (row_version bumped) | `origin_superseded: true`; chip struck through + "superseded" | N/A |
| Unknown origin | Gap why_it_matters "Unknown to the customer: …" | Chip "from Unknown: {title}" | N/A |
| Re-draft after edit | Edited (now unaccepted) Assumption, then re-draft | Carried to new draft, still unaccepted | N/A |
| Convert to Risk | Open Gap G2 with an unaccepted proposal A2, draft exists | Risk R1 created; G2 `converted` (risk); A2 removed; Risks card shows R1 | N/A |
| Convert, Gap not open | G2 already converted | 409 `gap_not_open`; nothing committed | Inline message |
| Convert, no draft | No draft version | 409 `no_draft_estimate` | Section hidden in UI |
| Edit Risk | Impact medium → high + reason | 200; row_version+1; re-sorted; traced | 412 / 409 as for Assumptions |
| Risks carried | Re-draft with 2 Risks | Both on the new draft, `carried_from_version` set | N/A |

</frozen-after-approval>

## Code Map

Backend (`backend/app/modules/estimates/`):
- `adapters/models.py:173` `estimates_assumptions` -- reuse; add `estimates_risks` beside it. `application/assumptions.py:135` `carry_accepted` -- widen the filter (converted origin) and carry Risks.
- `application/assumptions.py:550` `accept_assumption` -- the lock order, If-Match, `parse_if_match` and trace pattern to copy for `edit_assumption`. `domain/assumptions.py:92-147` -- validation to reuse (extract the kind/hours/wording rules into one function used by proposal and edit).
- `application/line_edits.py:138-203` -- the reason rule, the not-draft error and no-op detection to mirror.
- `application/models.py:109-164` (`OriginGap`, `Assumption`, `AssumptionGroups`) and `application/estimates.py:188-321` (`_register`, origin status mapping) -- add `origin_superseded`, `origin_is_unknown`, `position`, and `EstimateView.can_edit_assumptions`.
- `api/routes.py:128` -- add the PATCH next to accept.
- `modules/gaps/public.py` -- add `set_converted_to(uow, gap_id, kind)`. `gaps/domain/gaps.py:48-60` -- the Unknown prefix (expose `is_unknown`).
- `identity/actions.py:31`, `identity/domain/policy.py:104-130,78-83` -- `ASSUMPTION_EDIT`, `RISK_CREATE`, `RISK_EDIT` (granted like `ASSUMPTION_ACCEPT`; seed as Auth0 permissions wherever the others are seeded).
- `platform/trace/catalogue.py:615` -- payload models for `estimates.assumption.edited`, `estimates.risk.created` and `estimates.risk.edited` (ids, kinds, levels and lengths only, never text).
- `migrations/versions/` -- new `0041_estimates_risks` (down `0040_workflows_decisions`): the table and the widened `gaps_gaps.converted_to` check (`gaps/adapters/models.py:116`).
- `gaps/adapters/repository.py:727` `convert_gap` -- already takes `converted_to`; reuse via `mark_converted(kind="risk")`.

Web (`web/src/`):
- `components/opportunities/assumptions-register.tsx` -- row anatomy (ID chip, origin label, superseded), the row click → `onOpenAssumption`, keep the two groups.
- `components/opportunities/estimate-grid.tsx:558,633,659,841-871` -- the `Selection` union: add `{kind:"assumption"; id}`, a resolver, and a pane branch.
- New `components/opportunities/assumption-inspector.tsx` (details + Accept + Edit form), modelled on `estimate-line-edit.tsx:63-303` (`EditLineForm`, reason counter, `readKeptReason`, 412 alert).
- `app/opportunities/actions.ts:2354,2495` -- add `editAssumption`, `convertGapToRisk` and `editRisk` (copy `editEstimateLine` + `assumptionChanger`).
- `lib/estimates.ts:325,370` -- types and helpers (`assumptionLabel`, `originLabel`). `lib/api/schema.d.ts` -- regenerate with `npm run gen:api <dumped openapi.json>` from a fresh `app.openapi()`, not the Docker api.
- New `components/opportunities/risks-card.tsx` and `risk-inspector.tsx`, copying `FindingsTable` (`specialist-assessments.tsx:214`) and `severity-pill.tsx`. `gap-inspector.tsx` -- add the Convert to Risk section. `gaps-list.tsx` -- the "Converted to Risk" label.

Tests: `backend/tests/test_estimates_assumptions.py` helpers (`drafted`, `proposed`, `_accept`), new `test_estimates_assumption_edits.py`. Web: `assumptions-register.test.tsx` (`renderSection`, fixture builders), new `assumption-inspector.test.tsx`, with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**`, `gaps/public.py`, identity, trace catalogue -- `edit_assumption` command, route, read-model fields, risks table, convert/edit Risk, carry; migration 0041
- [x] `backend/tests/test_estimates_assumption_edits.py`, `test_estimates_risks.py` -- every matrix row, against `psa_test85`
- [x] `web/src/lib/api/schema.d.ts`, `lib/estimates.ts`, `actions.ts` -- types, helpers, `editAssumption`, `convertGapToRisk`, `editRisk`
- [x] `web/src/components/opportunities/{assumptions-register,assumption-inspector,estimate-grid}.tsx` + `risks-card.tsx`, `risk-inspector.tsx`, `gap-inspector.tsx`, `gaps-list.tsx` -- UI per the mockup
- [x] Web tests -- register row anatomy, inspector edit/412/read-only, superseded/Unknown chips, Risks card + Convert to Risk, axe

**Acceptance Criteria:**
- Given a draft Estimate with an accepted Contingency, when the presales engineer edits its hours with a reason in the inspector, then the row returns to a blocker row with Accept, the grid's Contingency and totals change, and the Trace shows `estimates.assumption.edited`.
- Given a superseded Estimate version selected, when the Register and inspector render, then no Accept, Accept all, Edit or Edit Risk control exists.
- Given an open Gap and a draft Estimate, when the presales engineer converts it to a Risk on the Gaps tab, then the Gap shows "Converted to Risk" and the Estimate tab's Risks card lists it with its likelihood and impact.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Superseded origin (interpretation):** converting a Gap bumps its `row_version` (8.4), so a literal "row_version differs" would mark every accepted Assumption superseded. `origin_superseded` is true when the Gap is neither `open` nor `converted`, or is `open` at another row version than `origin_ref.row_version`; a `converted` Gap is the conversion itself and counts as current (`domain/assumptions.origin_superseded`).
- **Accepting again:** a Gap already converted to an Assumption kind is this Assumption's own conversion (one per Gap and version), so accepting after an edit (or a carried unaccepted one) calls `gaps.set_converted_to` instead of `mark_converted` (no second `gaps.gap.converted`). A Gap converted to a Risk is still 409 `gap_not_open`. The 8.4 test that converted a Gap "elsewhere" now converts it to a Risk.
- **Extra columns:** `estimates_assumptions.changed_by` and `estimates_risks.changed_by` (set by accept, edit and create) name the person in the 412 "Changed by {name}…". Migration 0041 also grants `psa_app` DELETE on `estimates_assumptions` (Convert to Risk removes the unaccepted proposal); `estimates_risks` has no DELETE.
- **PATCH semantics:** fields left out of `AssumptionChanges` / `RiskChanges` keep their stored values; `amount_hours` and `line_id` may be sent as null. The web always sends every Assumption field. Both PATCHes answer with the whole `EstimateView`; `POST …/risks` answers 201 with the `Risk` and an ETag.
- **Read model:** `Assumption` gains `position`, `origin_superseded`, `origin_is_unknown`; `EstimateVersion.risks`; `EstimateView.can_edit_assumptions`, `can_create_risks`, `can_edit_risks`. `estimates.estimate_version.created` gains `carried_risk_count`. `gaps` exposes `is_unknown`, `set_converted_to` and `GapStatus` through `public.py`.
- **Web:** the Register row's wording is a button (Enter opens the Assumption inspector; a click anywhere on the row does too, except on Accept and the origin chip). Shared pieces (origin text/card, reason field, form notice) are in `estimate-item-parts.tsx`. The Gaps tab reads the Estimate server-side to decide whether to offer Convert to Risk (a draft exists and `can_create_risks`). Trace labels added for the three new events and the `estimates.risk` subject.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | verification | Convert-to-Risk delete not tested against a superseded version's proposal | medium | patch | Only single-version tests; DELETE now granted table-wide, so a dropped `version_id` filter would pass every test. |
| 2 | verification | `canConvertToRisk` derivation in `gaps.tsx` untested at page level | low | patch | gaps-list tests pass the boolean in; pages.test.tsx never mocks `/estimate` for `/gaps`. |
| 3 | verification+blind | Migration 0041 data-changing downgrade untested | low | patch | No test seeds a `risk` Gap before downgrading. |
| 4 | verification | Inspector Accept failure paths (412, gap not open) untested | low | patch | Only the `ok` path is tested. |
| 5 | verification+blind | `test_psa_app_cannot_delete_assumptions_of_other_gaps` asserts the opposite of its name | low | patch | It now asserts DELETE is granted. |
| 6 | edge | Reload after a 412 with a typed reason resyncs against the old prop; `dirty` then blocks the real resync, so every later save 412s | medium | patch | `setResync(true)` runs on the next render before `onReload` resolves; `reason` is kept, so `dirty` stays true (assumption-inspector.tsx, risk-inspector.tsx). |
| 7 | blind | 404 on an Assumption/Risk edit says "no access to the Opportunity" with no Reload | low | patch | `itemOutcome` maps `not-found` to `NO_ACCESS_TO_OPPORTUNITY`; the likely cause is the item being gone (Convert to Risk deleted the proposal). |
| 8 | blind | Switching to Contingency shows the hours rule in red before anything is typed | low | patch | `hoursOk` false on empty `hoursText` renders the rule immediately. |
| 9 | edge | A Gap converted to a Risk shows "Converted to Assumption" in its history | low | patch | `gapHistoryLabel` `converted` case is a fixed string; the history entry has no kind. |
| 10 | blind | `Gap`/`OriginGap` docstrings say `converted` means "an Assumption was accepted" | low | patch | No longer true after edits and Risk conversions. |
| 11 | blind | No UI test of a 412 on a Risk edit | low | patch | Only the Assumption form's 412 is tested. |
| 12 | blind | A Risk cannot be deleted or unconverted | medium | defer | No delete path; a mistaken Convert to Risk is permanent and carried by every re-draft. Not in this story's intent. |
| 13 | blind | DELETE on `estimates_assumptions` is table-wide; nothing at DB level limits it to unaccepted draft rows | medium | defer | Grant in 0041; only the app code narrows it. |
| 14 | blind | Edit events store only the reason length | false | reject | The frozen spec asks for "the reason length" and "never the text". |
| 15 | blind | Trace inspector has no before/after rendering for the new events | low | reject | Cosmetic; raw fields still shown; needs new formatting code. |
| 16 | blind+edge | Partial PATCH `{kind: condition}` on a Contingency 422s | low | reject | API-only; the web always sends every field; fix adds branches. |
| 17 | blind | Edited (unaccepted) Assumption leaves its Gap `converted` | low | reject | By design: the carry rule relies on it; the Register shows the blocker. |
| 18 | blind | `set_converted_to` appends no Gap trace | low | reject | The Assumption edit/accept is traced; adding a Gap event is new surface. |
| 19 | blind | Risks lack `origin_is_unknown` | low | reject | Spec gives Risks a "from Gap" chip; adding it is new API surface. |
| 20 | blind+edge | Origin card says "Superseded" for dismissed/answered Gaps | false | reject | `OriginGap.status` is only `open|superseded|converted` (models.py:119); the web cannot tell them apart. |
| 21 | blind | Trace payload field naming inconsistent (`assumption_kind: risk`, version id vs number) | low | reject | No named harm beyond style. |
| 22 | blind | Duplicated constants across `assumption_edits.py`/`risks.py` | low | reject | No caller diverges today. |
| 23 | blind | `epic-8-context.md` has unrelated edits | false | reject | It was recompiled by this workflow's step 1 because the planning docs changed. |
| 24 | blind | Gaps tab fetches the whole Estimate for one flag | low | reject | Perf only; a lighter endpoint is new surface. |
| 25 | edge | Race between the Gap read and `mark_converted` gives the Assumption-worded 409 detail | low | reject | Still 409 `gap_not_open`; rare race. |
| 26 | edge | Accept succeeds but the reload fails, so the inspector still shows Accept | low | reject | Rare; fix adds a new notice path. |

## Verification

**Commands:**
- `cd backend && PSA_DATABASE_URL=… PSA_MIGRATIONS_DATABASE_URL=… (127.0.0.1:5432/psa_test85) uv run pytest tests/test_estimates_*` -- expected: pass
- `cd backend && uv run ruff check . && uv run mypy app` -- expected: clean
- `cd web && npm run typecheck && npx eslint src && npx vitest run src/components/opportunities` -- expected: pass
