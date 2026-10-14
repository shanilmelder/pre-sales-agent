---
title: 'Story 4.4 (demo slice): Gaps tab with ranked Gap cards — impact change, dismiss and reopen, multi-select, history'
type: 'feature'
created: '2026-10-14'
status: 'done'
baseline_commit: '563387116f3e9655be72a0e17c5e895ad80d5b24'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-3-detect-gaps.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-5-edit-questions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Gaps tab (minimal slice from 4.3, questions from 4.5) lists Gaps, but a presales engineer can't correct an impact, set aside an irrelevant Gap, or act on several Gaps at once. Nothing records why a Gap changed, and the FR-11 "≤20% irrelevant" measure has no data.

**Approach:** Add Gap commands for impact change, dismiss and reopen, each with a reason, a trace event and a history entry. The list shows dismissed Gaps greyed at the bottom and supports `x` multi-select with **Approve N selected**. The inspector gains Gap history and these actions. The layout follows `mockups/gaps.html`.

## Boundaries & Constraints

**Always:**
- **Depends on:** 4.3 (Gaps, detection, tab), 4.5 (questions, If-Match/412 pattern), 8.4 (`converted`).
- **Lifecycle:** `GapStatus` gains `dismissed` (the domain's `dismissed_with_reason`). Transitions are pure functions in `gaps/domain`: `open → dismissed` and `dismissed → open`. Impact changes only on an `open` Gap. Any other source status → 409 `gap_not_open` (dismiss, impact) or `gap_not_dismissed` (reopen).
- **Commands** (each one Unit of Work, `If-Match` on the Gap's `row_version`: 428 missing, 412 stale with "Changed by {name}"):
  - `PATCH /opportunities/{id}/gaps/{gid}/impact` `{impact, reason}`. Same impact → 200 no-op. Trace `gaps.gap.impact_changed {old_impact, new_impact, row_version}`.
  - `POST …/gaps/{gid}/dismiss` `{reason_kind: not_relevant|other, note?}`. `note` is required for `other` and optional for `not_relevant`. Trace `gaps.gap.dismissed {reason_kind, row_version}`.
  - `POST …/gaps/{gid}/reopen` `{reason}`. Trace `gaps.gap.reopened {row_version}`.
  - Reasons and notes are 1–500 characters after trimming (422 otherwise). They never go in trace or logs.
  - Dismiss and reopen take `lock_opportunity` (AD-26 / epic: they change submission blockers). Impact change takes it too, so it can't race a detection.
- **Who:** new action `gaps.gap.edit` for the owner and collaborators except sales representatives (403). No access → 404. `GapList` gains `can_edit_gaps`.
- **Storage (migration 0029):**
  - `gaps_gaps` adds:
    - `dismiss_reason_kind`, `dismiss_note`, `dismissed_by`, `dismissed_at`: all set only while `dismissed`, enforced by a check.
    - `changed_by`: the latest human writer, used for the 412 text.
    - `touched_by_human` (bool): set by an impact change or a reopen.
  - The status check is widened to include `dismissed`.
  - New insert-only table `gaps_gap_history` (`id`, `gap_id`, `kind` `impact_changed|dismissed|reopened|converted`, `actor_id`, `at`, `old_impact`, `new_impact`, `reason_kind`, `reason`), with grants.
  - `mark_converted` writes a `converted` row too.
- **Re-detection (decided 2026-10-14: keep human decisions):**
  - Dismissed Gaps are never superseded or reopened.
  - An open Gap with `touched_by_human` is kept like one with a touched question.
  - A new candidate whose category and normalised title (case and spacing ignored) match a dismissed Gap of the Opportunity is dropped and counted in `dropped_count`.
- **Read API:** `list_gaps` returns open Gaps, then converted, then dismissed. Each group is ranked by impact, then `created_at`.
  - `Gap` adds `dismissal {reason_kind, note, by: UserRef, at} | null` and `history: [{kind, at, actor: UserRef|agent, old_impact, new_impact, reason_kind, reason}]`. History starts with a synthesized "Raised by Clarification Agent" entry at `created_at`.
  - A sales representative sees the `history` and `dismissal` entries without their `reason` and `note` text.
  - New public query `gaps.irrelevance_share(uow, opportunity_id | None)` → `{raised, dismissed_not_relevant}`. "Raised" counts detected Gaps that are not superseded. This is the FR-11 live measure. No UI.
- **Approve selected:** `POST …/clarification-questions/approve-selected` `[{id, row_version}]` (1–200 items). It approves exactly the listed drafted questions of open Gaps, all or nothing: 412 if any is stale, not drafted, or not on an open Gap. Each gets the 4.5 `approved` event.
- **Web (follow the mockup; the spines win where they disagree):**
  - Header: "N Gaps · M open · ranked by impact", plus **Approve N selected** when the selection holds drafted questions, else **Approve all (N)**.
  - Columns: status icon (Open / Converted / Dismissed per UX status pills), title, impact bar with label, Affects (category label), Trigger ("Clarification Agent · {category}"), question pill.
  - Dismissed rows are greyed, last, and keep their focus and keyboard behaviour.
  - Keys: `x` toggles the focused row's selection (checkbox column, `aria-selected`), and Esc clears the selection when the inspector is closed. The footer shows the key hints.
  - Inspector, for editors only:
    - Impact control: a select plus a required reason, then Save.
    - **Dismiss** form: a "Not relevant" / "Other" radio group, a note, then Dismiss.
    - On a dismissed Gap: a "Dismissed · {reason} · {name}, {date}" line, and **Reopen** with a reason.
    - A "History" list.
    - Convert is not offered (Epic 8 does it from the Estimate).
  - 412 shows the stale notice with Reload, as in 4.5. Run axe on every new state.

**Never:**
- No Checklists, mandatory Gaps, mandatory-first sort, Knowledge triggers, Evidence chips to Checklist items or passages, or "Checklist no longer applies".
- No Unknowns, no Convert or Record answer in this tab, no bulk dismiss, no Filter button.
- No GAP-nn ids, no Export questions button (4.6), no tab badge, no SSE live updates, no View diff, no FR-11 report UI.

All of these are `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Impact | Open High Gap → Low, reason, current If-Match | 200, re-sorted list, history row, `impact_changed` event | N/A |
| Dismiss | Open Gap, `not_relevant`, no note | `dismissed`, greyed last, history, event; `irrelevance_share` +1 | N/A |
| Dismiss other | `other` without note | 422 | Nothing changed |
| Reopen | Dismissed Gap, reason | `open`, ranked again, dismissal fields cleared, history kept | N/A |
| Wrong state | Dismiss a converted Gap / reopen an open one | 409 `gap_not_open` / `gap_not_dismissed` | Nothing changed |
| Stale | Old If-Match / none | 412 "Changed by …" / 428 | Nothing changed |
| Who | Sales rep dismisses / reads | 403 / sees history without reason text | N/A |
| Approve selected | 2 of 4 drafted selected | 200 `{count: 2}`, the other 2 stay drafted | 412 if one changed; nothing approved |
| Re-detect | 1 dismissed, 1 impact-changed, 1 untouched open Gap; new run re-raises the dismissed one's title plus 2 new | Dismissed stays dismissed; impact-changed kept; untouched superseded; re-raised candidate dropped; 2 new added | N/A |
| Privacy | Any command | No reason, note or question text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/domain/gaps.py` -- `GapStatus` (:65), `IMPACT_RANK`; add the dismiss/reopen/impact transitions and reason limits next to the 4.5 question transitions (:233+). Unit tests without a DB.
- `backend/app/modules/gaps/adapters/models.py` -- `GapRow` (:54-92) new columns and checks; new `GapHistoryRow`.
- `backend/app/modules/gaps/adapters/repository.py` -- `GapRecord` (:33), `_gap` (:320), `gaps_in` (:338), `lock_opportunity` (:74), `supersede_detected` (:220, `_untouched_question_or_none` :207 for the touched rule), `convert_gap` (:374). Add `update_gap` (row_version WHERE, like `update_question` :472), `insert_history`, `history_for`, and the irrelevance count.
- `backend/app/modules/gaps/application/questions.py` -- model the new `gap_commands.py` on it: `_authorized` :83, `_expected` :104, `_stale` :76, `_write` :128. `approve_all` :284 → share a helper with `approve_selected`.
- `backend/app/modules/gaps/application/gaps.py` -- `list_gaps` :203 (add the dismissed group, `can_edit_gaps`), `gap_views` :131 (history, dismissal, sales-rep redaction via `sees_only_approved_questions` :197).
- `backend/app/modules/gaps/application/{models.py,public.py,conversion.py}` -- `Gap` :93, `GapList` :121; export `irrelevance_share`; `mark_converted` :31 writes history.
- `backend/app/modules/gaps/application/detection.py` -- `accept_gap_detection` (supersede call; drop candidates matching a dismissed Gap, reusing the domain `_key` normalisation).
- `backend/app/modules/gaps/api/routes.py` -- add routes following `edit_clarification_question` :167 / `_with_etag` :105 (ETag from the Gap's row_version).
- `backend/app/modules/identity/{actions.py:26,domain/policy.py:71,94,112}` -- `GAP_EDIT`; update `tests/test_authorize.py`.
- `backend/app/platform/trace/catalogue.py` (~:213-290) -- three payloads; `web/src/lib/trace.ts` `EVENT_LABELS`.
- `backend/app/platform/errors.py` -- `gap_not_dismissed` error.
- `backend/migrations/versions/` -- `20261014_0029_gaps_dismiss_history.py`, revising `0028`.
- Unaffected, verify only: `estimates` uses `open_gap_summaries` (dismissed drop out of proposals and blockers); `export_content.py:243` already filters `open|converted`.
- Web: `components/opportunities/gaps-list.tsx` (`GapsList` :84, `GapsSection` :268), `gap-inspector.tsx` (:58), `impact-bar.tsx`, `status-pill.tsx`, `lib/gaps.ts` (`toApprove` :112, `approveAllLabel` :117), `app/opportunities/actions.ts` (`approveAllClarificationQuestions` :1279, `QuestionWriteResult` :1101 → the same shape for Gap writes). The reason form follows `conflict-inspector.tsx` (:263-420, `REASON_REQUIRED`). Regenerate `schema.d.ts` from a local uvicorn.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/gaps/domain/gaps.py` + `tests/test_gaps_domain*.py` -- transitions, limits
- [x] migration 0029, `adapters/models.py`, `adapters/repository.py` -- columns, history table, queries
- [x] `application/gap_commands.py`, `gaps.py`, `models.py`, `public.py`, `conversion.py`, `questions.py` (approve-selected), `detection.py` (re-detection rule) -- commands and read model
- [x] `api/routes.py`, identity, catalogue, errors -- wiring
- [x] `backend/tests/test_gaps_commands.py` -- every matrix row against Postgres
- [x] Web: `schema.d.ts`, actions, list (status icons, groups, `x`, Approve selected), inspector (impact, dismiss, reopen, history), trace labels, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity's Gaps, when the presales engineer lowers one Gap's impact, dismisses another as "Not relevant", then selects two drafted questions with `x` and presses **Approve 2 selected**, then the list re-ranks, the dismissed Gap shows greyed at the bottom with its reason, both questions show Approved, and the inspector history shows each change with who and when.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Read model:** `Gap` gains `dismissal`, `history` and `last_changed_by` (the person behind the latest change, for the 412's "Changed by {name}"). History `actor` is a `UserRef` or `"agent"`; a `converted` entry made by a non-user actor also reads `"agent"`. History rows store `actor_id` null for that case.
- **Order of checks** (as 4.5): authorize (403/404) → Gap in this Opportunity (404) → body (422) → `If-Match` (428) → status (409) → stale (412) → no-op or write. The same impact with a stale `If-Match` is still 412. `update_gap` also checks the source status in its WHERE, so a Gap converted by `estimates` meanwhile is 409, not a lost write.
- **Dismissal check:** `ck_gaps_gaps_dismissed_fields` requires all dismissal fields while `dismissed` (the note only for `other`) and none otherwise. A blank `not_relevant` note is stored as no note.
- **Re-detection:** candidates matching a dismissed Gap are filtered after the "every candidate invalid" check, so a run whose only valid candidates repeat dismissed Gaps succeeds with 0 new Gaps instead of retrying. `kept_count` counts open Gaps kept for any human reason.
- **Approve selected:** duplicate ids with different versions, unknown ids, approved questions, and questions of non-open Gaps are all 412. Body 1–200 items (422 otherwise).
- **Web:** `aria-selected` on rows now means multi-selected (`aria-multiselectable` grid, editors only); the opened row is `aria-current`. `x` is a single-key shortcut (off with single-key shortcuts off; the checkbox still works by pointer). The visual column header is `aria-hidden`; each row's status icon has a visually hidden label. After a Gap write the list is re-ranked locally with the API's order (`rankGaps`).

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge | A re-detected candidate can duplicate an open Gap a person kept (impact changed/reopened) | low | reject | Same trade-off the human accepted in 4.5 (triage row 3: "the run may add a Gap that overlaps one you kept"); the 4.4 decision only adds dismissed-title matching. |
| 2 | blind | `dropped_count` mixes invalid output with dismissed repeats | false | reject | The frozen decision says re-raised dismissed candidates are "counted in `dropped_count`". |
| 3 | blind+edge | All candidates repeat dismissed Gaps → 0 new, untouched open Gaps superseded | false | reject | Same as an empty candidate list, already a valid result since 4.3 (Implementation Notes: "0 Gaps, earlier ones superseded"). |
| 4 | blind | `mark_converted` doesn't set `changed_by` | low | reject | `changed_by` only names the editor on a 412; once converted, every Gap write answers 409 (`update_gap` WHERE status), so the stale name is never shown. |
| 5 | blind | History "converted" entry doesn't say Condition or Contingency | low | reject | Cosmetic; the row label already shows the kind; needs a new column. |
| 6 | blind | `gaps_gap_history` lacks per-field checks / FKs | low | reject | Only gaps code writes it, with enum values; no FKs to identity by module rule (as 4.5 row 10). |
| 7 | blind | `irrelevance_share` has no caller | false | reject | Spec: "This is the FR-11 live measure. No UI." |
| 8 | blind+edge | Saving the unchanged impact silently clears the typed reason | low | patch | `gaps-list.tsx` `changeImpact` returns "ok" with no request; direct fix: return an `invalid` message. Fixed. |
| 9 | blind+verify | Migration 0029 downgrade never exercised with a dismissed Gap | medium | patch | Pre-verified; the only downgrade crossing 0029 (`test_workflows_events.py:317`) has no Gaps. Fixed. |
| 10 | blind | Docstring check order vs `MAX_ROW_VERSION` 412 | false | reject | An If-Match ≥ 2^31−1 can't come from a real ETag; same guard as 4.5. |
| 11 | blind+edge | Selection keeps non-approvable rows; with no drafted question selected the header falls back to Approve all | low | reject | Spec: "Approve N selected when the selection holds drafted questions, else Approve all (N)"; the label says "all". |
| 12 | blind | Not-open messages omit "dismissed" | low | patch | `conversion.py:26`, `questions.py:73`, `assumptions-register.tsx:44` still say "converted or replaced"; a dismissed Gap now also gives `gap_not_open`. Fixed. |
| 13 | blind | Sales-rep redaction only partly tested | false | reject | `test_sales_reps_may_not_change_gaps_and_see_history_without_reasons` checks history reasons, the dismissal note and 403s; `can_edit_gaps` false is covered by the web "no controls" test. |
| 14 | edge | History `at` from app clock vs DB `now()` | low | reject | API and DB share a host (as 4.3 row 25). |
| 15 | edge | `ImpactForm` keeps a stale impact after a reload changes it | low | patch | Keyed only by Gap id (`gaps-list.tsx:1026`); direct fix: key the form by `row_version`. Fixed. |
| 16 | edge | AC: the dismissed row shows no reason in the list | medium | patch | AC says "greyed at the bottom with its reason"; the row shows only the status icon. Direct fix: a "Dismissed · {reason}" label in the question column, as converted rows do. Fixed. |
| 17 | edge | Question approvals aren't in the Gap history | false | reject | Spec defines history kinds as impact_changed, dismissed, reopened, converted; approvals show in the question block. |
| 18 | verify | Export not tested with a dismissed Gap | medium | patch | Pre-verified; `export_content.py:243` is now the only guard keeping dismissed questions out of the customer export. Fixed. |
| 19 | verify | New server actions untested in `actions.test.ts` | medium | patch | Pre-verified; `gaps-list.test.tsx` mocks them, so 409/412/422 mapping and request shapes are unchecked. Fixed. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
