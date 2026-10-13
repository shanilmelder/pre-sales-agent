---
title: 'Story 8.2 (demo slice): edit an Estimate line''s hours and role mix inline, with a reason'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: 'a2a7431c4acb3252525467791b085d534f7105b2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-1-draft-estimate.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-7-carry-assumptions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The draft Estimate is entirely the model's: a presales engineer who disagrees with a line's hours or role mix can't change them, so stakeholders see an Estimate nobody can shape and the platform's "a person stays in control" story has no proof on screen (FR-35).

**Approach:** On the current draft version, the presales engineer edits a line's effort hours and role mix (%) inline in the Estimate grid and gives a short reason; the server saves it with `If-Match`, recalculates the totals and role hours, traces the before and after values with the reason, and the grid shows the line as edited. A re-draft carries a person's edits onto the new version's matching line, so automatic re-drafting never silently discards them.

## Boundaries & Constraints

**Always:**
- **Who:** new action `estimates.estimate_line.edit` for the owner and collaborators except sales representatives (403); read-only for everyone else, as today.
- **Editable (decided):** effort hours and role mix only.
- **API:** `PATCH /opportunities/{id}/estimate-lines/{line_id}` with `If-Match: "<row_version>"` and `{effort_hours?, role_mix?, reason}` (at least one of the two values). Hours 0–2,000, rounded half up to 0.1. Role mix: whole percentages 0–100 for exactly the template's roles, summing to 100 (the existing `valid_mix` rule) — otherwise 422 "Role mix must name every role and add up to 100%". Reason trimmed 1–300 characters, required. Only a line of the Opportunity's current `draft` version: otherwise 409 `estimate_version_not_draft` ("This Estimate Version was replaced by a newer draft. Reload to see it."). Stale `If-Match` → 412 "Changed by {name} since you opened it." (Reload); missing → 428. Values equal to the stored ones are a 200 no-op. The response is the updated Estimate read model, so totals refresh from the server (line role hours, subtotals, version totals, role totals, line totals with Contingency).
- **Carry on re-draft (decided):** when a re-draft is accepted as a new version, each edited line of the superseded draft is matched to the new version's line with the same section and title (the matching rule 8.7 uses for Contingencies); the match takes the edited hours, role mix, editor, time and reason, plus "carried from v{n}". Edited lines with no match are counted on the new version ("{k} edited lines from v{n} had no matching line; they stay in v{n} and the Trace."). A carried edit appears in the draft's completion trace as counts (carried, unmatched).
- **Migration `0019_estimates_line_edits`:** lines gain `row_version` (default 1), `edited_by`, `edited_at`, `edit_reason` and `edit_carried_from_version` (null until edited or carried); versions gain `uncarried_edit_count` (default 0). `psa_app` gets UPDATE on only the edit columns, `effort_hours` and `role_mix`; still no DELETE.
- **Trace:** `estimates.estimate_line.edited` (actor the user; subject the line; version number, `before_hours`, `after_hours`, `before_role_mix`, `after_role_mix`, `reason`). The reason is the user's own words, so it may be traced; no Requirement text.
- **Web:** on a draft version, for those who may edit:
  - the Effort cell is an inline field (Enter or blur to save, Esc to cancel; `e` on a focused row starts editing);
  - the Role mix cell opens a compact editor with one whole-number field per role and a live "= {sum}%" check; Save is disabled until it is 100;
  - then a compact reason prompt (prefilled with the user's last reason in this version, kept in the browser) with Save / Cancel.
  - While saving the cell is disabled; on success the grid re-renders from the response; on 4xx the value rolls back and the server's message shows inline. Edited lines show an "Edited" marker (icon plus label; "Edited, carried from v{n}" when carried) with "{name}, {date}: {reason}" in the line inspector; the unmatched-edits note shows above the grid. Keyboard and axe as the other grids.
- **Privacy:** no Requirement or customer text in logs.

**Never:** No editing title, section or Requirement links; no adding or deleting lines; no Contingency or Assumption edits (8.4/8.7 unchanged); no version switcher, submit or Baseline; no View diff on 412; no LangGraph code. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Hours | Draft v2, line 40 h → 32 h, reason "Reuse the existing connector" | 200; line 32 h, marked edited; role hours, subtotal and totals recalculated; trace with before 40, after 32 and the reason | N/A |
| Role mix | 50/30/20 → 40/40/20 | 200; role hours and role totals recalculated; trace with both mixes | N/A |
| Bad mix | Shares summing to 90, a missing role, or a fraction | 422 with the role-mix message; nothing saved | Rolls back |
| Rounding | 12.25 h | Saved 12.3 h | N/A |
| Bad value | −1 h, 2,500 h, or a blank reason | 422; nothing saved | Rolls back |
| Unchanged | Same values | 200 no-op; no trace | N/A |
| Stale | Another user saved the line first | 412 "Changed by {name} since you opened it."; nothing overwritten | Reload |
| Superseded | The version was replaced by a re-draft | 409 `estimate_version_not_draft` | Reload |
| Carry matched | v2 line "SAP connector" (integration) edited to 32 h; Gap detection re-drafts v3 with the same line at 40 h | v3 line 32 h with the v2 role mix, editor and reason, "carried from v2"; totals from the carried values | N/A |
| Carry unmatched | The edited line has no same-section-and-title line in v3 | v3 shows "1 edited line from v2 had no matching line…"; v2 keeps it | N/A |
| Who | Sales rep edits / reads | 403 / read-only grid | N/A |
| Contingency | Line with a linked Contingency | Line total = new effort + Contingency | N/A |

</frozen-after-approval>
## Code Map

- Backend:
  - `backend/app/modules/estimates/adapters/models.py:91-121` `EstimateLineRow` (insert-only today, no `row_version`); migration 0012 grants lines SELECT/INSERT only (`migrations/versions/20261005_0012_estimates.py:152-154`) — 0019 adds the columns and column-level UPDATE.
  - `backend/app/modules/estimates/domain/arithmetic.py` — server totals (`sum_totals`, line totals with Contingency); reuse, don't re-implement.
  - `backend/app/modules/estimates/application/estimates.py` — the read model (`get_estimate`), `accept_assumption` as the pattern for an If-Match write (412/428, `etag`, ETag header), version lock and draft checks; `application/models.py` `EstimateLine` (add `row_version`, `edited`, `edited_by_name`, `edited_at`, `edit_reason`).
  - `backend/app/modules/estimates/api/routes.py:34-35,89-156` — If-Match parameter and responses pattern.
  - `backend/app/modules/estimates/application/assumptions.py:132` `carry_accepted` and `repository.py:474-499` — the section-and-title matching to reuse for carrying edits; the re-draft acceptance (`accept_draft`, which already calls `carry_accepted`) is in `application/draft.py`. Role-mix rule: `domain/estimates.py` `valid_mix`; role hours: `domain/arithmetic.py` (`split_tenths`).
  - Identity: `identity/actions.py`, `domain/policy.py` (pattern `ASSUMPTION_ACCEPT`), `tests/test_authorize.py`. Errors: `platform/errors.py`. Trace: `platform/trace/catalogue.py`; web label in `web/src/lib/trace.ts`.
- Web: `web/src/components/opportunities/estimate-grid.tsx` (+ tests), `estimate-inspector.tsx`, `web/src/app/opportunities/actions.ts` (an If-Match write pattern: `acceptAssumption`), the 2.6 `InlineField` pattern used for Requirement edits. Regenerate `schema.d.ts` from a local uvicorn.
- Tests: `backend/tests/test_estimates_api.py` / `test_estimates_draft.py` patterns (fake gateway, hidden jobs), grants test for the new column-level UPDATE.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/*_0019_estimates_line_edits.py`, `estimates/adapters/**` -- columns, column-level grants
- [x] `backend/app/modules/estimates/{application,api}/**`, identity, errors, catalogue -- edit command, route, read model, trace, carrying edits on re-draft
- [x] `backend/tests/**` -- every matrix row, grants
- [x] Web: `schema.d.ts`, `editEstimateLine` action + tests, inline Effort cell and Role mix editor with reason prompt, unmatched-edits note, Edited marker and inspector history, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity's draft Estimate, when the presales engineer changes a line's hours with a reason, then the totals update at once, the line shows as edited, and the Trace tab shows who changed it, from what to what, and why.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Command:** `application/line_edits.py` (`edit_line`, `carry_edits`); `estimates.edit_line` wraps it and answers with `get_estimate`. Order: authorize → validate body (422 with the rule's sentence) → draft lock → load (404, also for a line of another Opportunity) → draft check (409) → If-Match (428/412). A stale If-Match is 412 even when the values are unchanged (as Requirement edits). The 412 `detail` is "Changed by {name} since you opened it." (the line's last editor, else "someone else"); the web re-reads the Estimate for the name, like the other If-Match writes.
- **Body:** `EstimateLineChanges` (`extra="forbid"`): `effort_hours` strict int/float, `role_mix` an object checked by `valid_mix` (so a missing role, a fraction, a bool or an extra key all get the role-mix sentence), `reason` required. Effort 0–2,000 after half-up rounding.
- **Read model:** `EstimateLine` gains `row_version`, `edited`, `edited_by_name`, `edited_at`, `edit_reason`, `edit_carried_from_version`; `EstimateVersion` gains `uncarried_edit_count` and `uncarried_edits_from_version` (= version − 1, the superseded draft); `EstimateView` gains `can_edit_lines`.
- **Carry:** after `carry_accepted` in `accept_draft`; uses `domain.assumptions.carried_line` (one same-section-and-title match, trimmed, casefold). A new line already taken by another edit counts as unmatched. A carried line keeps `row_version` 1; editing it again makes it a direct edit (`edit_carried_from_version` null). Chains say the immediately preceding version (as 8.7). `estimates.estimate_version.created` gains `carried_edit_count` and `uncarried_edit_count` (default 0).
- **Grants:** column-level `UPDATE (effort_hours, role_mix, row_version, edited_by, edited_at, edit_reason, edit_carried_from_version)`; `row_version` is included because the edit bumps it.
- **Web:** `EstimateGrid` holds the edit state (`InlineInput` for Effort, `RoleMixEditor` and `ReasonPrompt` in `estimate-line-edit.tsx` in a row under the line, as is the failure sentence with Reload for 412/409). The last reason is kept per version in `localStorage` (try/catch). `schema.d.ts` regenerated from a dumped `app.openapi()`.

## Spec Change Log

## Review Triage Log

Pass 1 (2026-10-06; blind-hunter, edge-case-hunter, verification-gap):

| # | Finding | Verdict | Evidence | Route |
|---|---------|---------|----------|-------|
| 1 | Save sends the current render's `row_version`; a poll refresh while the prompt is open overwrites a colleague's edit without 412 (edge) | high | `save` reads `line.row_version` at save time | patch: capture at edit start |
| 2 | "1,000" parsed as 1.0 h and saved silently (edge) | medium | `parseEffort` treats the comma as a decimal point | patch: thousands separators; rounded max |
| 3 | A new version arriving mid-edit drops the typed change silently (blind) | medium | Edit state keyed to gone line ids | patch: reset with a notice |
| 4 | VG: pure carry chain (carried twice without re-edit) untested | medium | Pre-verified | patch: test |
| 5 | VG: cells disabled while saving untested | medium | Pre-verified | patch: test |
| 6 | A 412 can become a generic error; server's 412 detail ignored (blind) | low | Extra re-read inside the same try | patch: use `detail` |
| 7 | Summary and optimistic cell round with `toFixed`, server rounds half up (edge) | low | 0.35 → "0.3" shown, 0.4 stored | patch |
| 8 | Client refuses 2000.01–2000.04 that the server accepts (edge) | low | Raw value compared with the max | patch (with #2) |
| 9 | Reason keys pile up in `localStorage`, read on every render (blind) | low | One key per version, never cleared | patch |
| 10 | Over-limit reason disables Save without explanation (blind) | low | `maxLength` 600 vs rule 300 | patch: counter |
| 11 | Invalid role-mix field counted as 0 without explanation (blind) | low | Live sum misleads | patch: `aria-invalid` + message |
| 12 | `taken` collision branch untested (VG defer, blind) | low | Cheap to cover | patch: test |
| 13 | Import not Prettier-formatted (VG other, blind) | low | `estimate-line-edit.tsx` | patch |
| 14 | Carry copies hours and role mix even when only one was edited (edge) | low | The intent says the match takes the edited hours and role mix | reject (intent) |
| 15 | Carried-from names the immediately preceding version, not the original (edge) | false | Deliberate (Implementation Notes); #4 tests it | reject |
| 16 | Model's own value for a carried line isn't recorded (blind) | low | Superseded version keeps the history | reject |
| 17 | `uncarried_edits_from_version` derived as version − 1 (blind) | low | Holds: the superseded draft is always the previous version | reject |
| 18 | `role_mix` is an open map in the API schema (blind) | low | `valid_mix` enforces the rule server-side | reject |
| 19 | A missing line's 404 says "no access" (blind) | low | Same mapping as other actions | reject |
| 20 | Clicking another cell discards a pending change without warning (blind) | low | Cosmetic | reject |
| 21 | Row-version overflow / higher If-Match reports "Changed by" (blind, edge) | low | Unreachable in practice | reject |
| 22 | 428 logged as an unexpected error (edge) | low | The app always sends If-Match | reject |
| 23 | More edge tests (malformed If-Match, limits, lock race; blur, error paths) (blind) | low | Covered by shared patterns | reject |
| 24 | Client copies of server rules can drift (blind) | low | Server `detail` is shown on 422 | reject |
| 25 | Export doesn't show edits (blind) | low | Not in this slice | reject (`[post-demo]`) |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass (known local-only failure: `test_user_search.py::test_matches_email`, deferred)
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
