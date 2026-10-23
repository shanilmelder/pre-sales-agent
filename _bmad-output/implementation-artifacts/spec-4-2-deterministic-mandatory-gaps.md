---
title: 'Story 4.2: Deterministic Gaps from mandatory Checklist items'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '8d1443233b2290e575b4eb285a1fec12021caa46'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-3-4-author-version-checklists.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Gaps today come only from `clarification_agent`, so a mandatory Checklist item that applies to an Opportunity can be missed whenever the model misses it (FR-11 needs 100%).

**Approach:** The `gaps.detect_gaps` job gains a deterministic first step: before any agent call, it reads `knowledge.public.find_applicable_checklists` for the Opportunity's products and industry, raises one `origin: mandatory_checklist` Gap per mandatory item that has none yet, and flags open mandatory Gaps whose item no longer applies. The Gaps tab shows them with a "Mandatory" label and a Checklist trigger.

## Boundaries & Constraints

**Always:**
- The mandatory step runs in `_start`'s Unit of Work, after the `running` check and **before** the registry/agent check, so the Gaps commit even when the agent is disabled, fails or there are no Requirements. Pure domain code decides which items need a Gap; no LLM output is read.
- Identity: unique partial index on `(opportunity_id, trigger->>'checklist_id', trigger->>'item_id') WHERE origin = 'mandatory_checklist'`; insert with `ON CONFLICT DO NOTHING`. A Gap in any status (open, answered, converted, dismissed) blocks a new one, and is never reopened.
- New Gap: title = item text (cut to `TITLE_MAX` with "…"); `why_it_matters` = item's (cut to `WHY_MAX`) and new nullable `why_entry_id` = item's `affected_entry_id`; impact = item impact; `impact_basis` = "Default impact of mandatory item in Checklist "{name}" v{n}."; category from domain (security→security_and_compliance, commercial→commercial, delivery→scope_and_ownership, engineering→integration_details, general→other); trigger `{"kind": "checklist_item", "checklist_id", "version", "item_id", "checklist_name"}`; no Requirement links; `detection_id` = the run; a `drafted` question with the item text (cut to `QUESTION_MAX`), topic = Checklist name (cut to `TOPIC_MAX`) and new column `from_checklist = true`.
- Applicability: each run sets new column `checklist_applies` on every **open** mandatory Gap: true iff its `(checklist_id, item_id)` is a mandatory item of an applicable version (it flips back to true if scope returns). Never deletes a Gap.
- Dismiss: an open mandatory Gap with `checklist_applies = true` → 409 (`gap_mandatory`, "A mandatory Gap can be dismissed only once its Checklist no longer applies."). Answer, convert, impact change and reopen are unchanged.
- Trace: one `gaps.gap.raised` per new Gap with new field `origin` (default `"detected"`), actor `Actor(type="system", id="gaps.detect_gaps")`; ids/counts only. `notify_gaps_changed` when anything was raised or flipped.
- List order: impact, then mandatory first within an impact, then oldest.
- Web: the row and inspector trigger read "Checklist · {name} v{n}" for `checklist_item` (mockup style), the row shows `MandatoryLabel` for `origin: mandatory_checklist`, a "Checklist no longer applies" note (row and inspector) when `checklist_applies` is false, "from Checklist" next to the question while `from_checklist`, the inspector hides "Related Requirements" when empty and hides Dismiss while a mandatory Gap still applies. Badge and SSE refresh already work: no change.

**Never:** Integration Type tagging or the Gaps-tab Checklist header/notice (Story 4.1); enqueueing detection on scope edits (no products/industry/tag edit command exists yet — `gaps.public.enqueue_detection` is the hook for 4.1); agent-drafted questions for mandatory Gaps, "Possibly answered", passing Checklists to the agent (Story 4.3 remainder); re-running detection when a Checklist is published or retired; the mockup's row-layout redesign (second-line chips, High tint, "Blocks submit").

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run | 2 applicable Checklists, 3 mandatory + 2 optional items | 3 open mandatory Gaps with questions, 3 `gaps.gap.raised`; then the agent step as before | N/A |
| Re-run / concurrent | Same scope, runs twice or in parallel | Still 3 mandatory Gaps | Conflict → skipped insert |
| Settled | Item's Gap answered/converted/dismissed | No new Gap, status untouched | N/A |
| New version | v2 keeps item IDs, adds one mandatory item | One new Gap; existing ones kept | N/A |
| No longer applies | Checklist retired, item removed in v2, or scope no longer matches | Open Gap stays, `checklist_applies = false`; dismiss now allowed | N/A |
| Dismiss while applies | Open mandatory Gap, applies | 409 `gap_mandatory` | Nothing written |
| Agent disabled / fails | Registry disabled or model error | Mandatory Gaps already committed; detection fails as before | N/A |
| Re-detection | Agent run supersedes detected Gaps | Mandatory Gaps never superseded | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/domain/gaps.py` -- add `GapOrigin.MANDATORY_CHECKLIST`, `CHECKLIST_TRIGGER_KIND`, a pure `mandatory_gaps(applicable, existing_keys)` planner (new Gaps + applies set), category map, cut helper, `GapMandatoryError` rule for dismiss (`dismiss_gap` gets a `mandatory_applies` flag).
- `backend/app/modules/gaps/adapters/models.py:107` -- widen `origin` CHECK; add `checklist_applies` (bool, server default true), `why_entry_id` (uuid null); `QuestionRow.from_checklist` (bool default false); the unique partial index.
- `backend/migrations/versions/` -- new `20261023_0037_mandatory_gaps.py` after `0036_knowledge_checklists`.
- `backend/app/modules/gaps/adapters/repository.py:338` -- `insert_mandatory_gap` (pg_insert on_conflict_do_nothing, returns bool), `mandatory_keys`, `set_checklist_applies`; extend `GapRecord`/`_gap`/`QuestionRecord`. `supersede_detected` :288 already filters `origin == 'detected'` — keep.
- `backend/app/modules/gaps/application/detection.py:420` (`_start`) -- call new `raise_mandatory_gaps(uow, opportunity_id, detection_id)` (new file `application/mandatory.py`) reading scope via `opportunities.public` and checklists via `knowledge.public.find_applicable_checklists(products, industry, integration_type_ids=[])`.
- `backend/app/modules/gaps/application/gap_commands.py:272` -- pass mandatory/applies into the rule; map to 409.
- `backend/app/modules/gaps/application/models.py:28,278` -- `GapTrigger` becomes a discriminated union (`agent_category` | `checklist_item`); `Gap` gains `checklist_applies: bool`, `why_entry_id`; `ClarificationQuestion.from_checklist`.
- `backend/app/modules/gaps/application/gaps.py:120` -- sort key adds mandatory-first.
- `backend/app/platform/trace/catalogue.py:327` -- `GapsGapRaised.origin: str = "detected"`.
- Check opportunities' public API has a scope read usable from the worker (no actor); add `opportunity_scope(uow, id)` if not.
- `web/src/lib/api/schema.d.ts` -- regenerate (`gen:api`, see memory: psa_test DB, fresh backend).
- `web/src/lib/gaps.ts:313` `triggerLabel`; `web/src/components/opportunities/gaps-list.tsx:316-335` row; `gap-inspector.tsx:167,179-189` trigger, Related Requirements, Dismiss; reuse `web/src/components/knowledge/mandatory-label.tsx:8`.
- Tests: copy fixtures from `backend/tests/test_gaps_detection.py` and checklist publishing helpers from `tests/test_knowledge_checklists.py:152-214`.

## Tasks & Acceptance

**Execution:**
- [x] `gaps/domain/gaps.py` + `tests/test_gaps_mandatory_domain.py` -- planner, category map, dismiss rule; unit-test every matrix row without a DB.
- [x] `gaps/adapters/models.py` + migration -- columns, CHECK, unique partial index.
- [x] `gaps/adapters/repository.py` -- insert/keys/applies writes.
- [x] `gaps/application/mandatory.py` + `detection.py` -- deterministic step in `_start`, trace, notify.
- [x] `gap_commands.py`, `models.py`, `gaps.py`, trace catalogue -- 409, API shape, sort.
- [x] `tests/test_gaps_mandatory.py` -- fixture suite: every applicable unanswered mandatory item → exactly one Gap (FR-11 bar), rerun, concurrent run, settled, new version, no longer applies, dismiss 409, agent disabled, supersede.
- [x] web: regenerate schema; `triggerLabel`, row label/notes, inspector; extend existing web tests for these.

**Acceptance Criteria:**
- Given an accepted extraction on an Opportunity whose products or industry match published Checklists, when the detection job runs, then the Gaps tab lists one row per mandatory item with "Mandatory", its impact and an Open pill, without a refresh, and the badge counts them.
- Given the agent errors on every attempt, when the job fails, then the mandatory Gaps remain open with "from Checklist" questions.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_gaps_mandatory_domain.py tests/test_gaps_mandatory.py tests/test_gaps_detection.py tests/test_gaps_commands.py tests/test_gaps_api.py` -- all pass (psa_test DB).
- `cd backend && uv run ruff check . && uv run mypy app` -- clean.
- `cd web && npm run lint && npm run typecheck && npm test` -- clean.

## Implementation Notes

- New `gaps/application/mandatory.py` (`raise_mandatory_gaps`), called in `detection._start` before the registry check; new `opportunities.public.opportunity_scope` (no actor) for the worker.
- `checklist_applies` flips don't bump `row_version` (derived flag): a dismiss racing a flip back gets 409 `gap_mandatory`, not 412.
- `test_knowledge_checklists.py` now publishes with a unique industry so its active "Retail" Checklist doesn't raise mandatory Gaps in other suites' fixtures.
- Schema regenerated from a dumped `app.openapi()`. Verified on `psa_test_4_2`: full backend suite 2049 passed / 3 skipped; ruff, mypy, lint-imports clean; web lint/typecheck clean, vitest 1752/1753 (flaky `catalogue-inspector.test.tsx`, passes alone).
- Migration `0037_mandatory_gaps` collides in number with Story 4.1's `0037_requirement_tags` (other worktree): whichever merges second renumbers.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | blind, edge, verif | Reopened mandatory Gap keeps stale `checklist_applies=false` and can be dismissed while it applies | medium | `set_checklist_applies` filters `status == 'open'`; `reopen_gap` never touches the flag | patch |
| 2 | blind | A dismissed mandatory item that applies again gets no open Gap | false | Intended: settled Gaps are never reopened or re-raised (epic AC, frozen matrix "Settled") | reject |
| 3 | blind | Flag only recomputed when a detection runs (publish/retire/scope edit) | low | Frozen Never excludes re-running on publish/retire; no scope-edit command exists | reject |
| 4 | blind | Flag flips leave no history/trace and don't bump row_version | low | Derived flag, recorded in Implementation Notes; no user-visible harm beyond rare 409-vs-412 | reject |
| 5 | blind, edge | Agent may raise a Gap duplicating an open mandatory Gap | maybe-false | Agent isn't given Checklists; exact category+title match unlikely; semantic dedupe belongs to 4.3 remainder | defer |
| 6 | blind, edge, verif | Downgrade deletes mandatory Gaps (orphan Assumption refs) and is untested | low | Downgrade only on dev DBs; prod-hardening track skipped | defer |
| 7 | blind | `why_entry_id` stored but not shown in UI | low | Spec requires only storing/returning it | reject |
| 8 | verif | `why_entry_id` never checked end to end | medium | Only the pure planner test asserts it; integration items have null entry | patch |
| 9 | verif | Mandatory `clarification_question.drafted` trace unasserted | low | No test counts it for mandatory questions; direct test addition | patch |
| 10 | verif | Backend mandatory-first ordering unverified | medium | Existing test passes on created_at alone | patch |
| 11 | edge | `open_gap_summaries` ranking lacks mandatory-first, so G<n> labels diverge from tab | low | gap_refs.py `_ranked` keys on impact, created_at only; one-term fix | patch |
| 12 | blind | Domain module docstring says every Gap has a Requirement / agent trigger | low | Now false for mandatory Gaps; direct correction | patch |
| 13 | blind | Other publishing tests may leak mandatory Checklists into Gap tests | low | Full suite passed (2049); speculative order dependence | reject |
| 14 | blind | Duplicated constants (`MANDATORY`, index exprs, dismiss message) | low | No named diverging caller; repository already uses literals | reject |
| 15 | blind | Trigger ids typed `str`, malformed row crashes step | false | Triggers are only written by `checklist_trigger` with `str(UUID)` | reject |
| 16 | blind | Agent-disabled test asserts job `succeeded` | false | Matches existing queue behaviour: handler returns normally after marking the detection failed | reject |
| 17 | edge | A failing mandatory step blocks agent detection | low | Needs corrupt Checklist data or a DB error, which would fail the run anyway; fix adds savepoint branch | reject |
| 18 | edge | `risk` item text drafted as a Clarification Question | low | Labelled "from Checklist", needs approval before sending; agent drafting is the 4.3 remainder; fix adds branching | reject |
| 19 | edge | Item text >1000 chars cut with "…" in the question | low | Question is edited/approved before sending; rare length | reject |
