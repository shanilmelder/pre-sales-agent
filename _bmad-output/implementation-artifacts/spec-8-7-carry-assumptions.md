---
title: 'Story 8.7 (demo slice): a re-draft carries accepted Assumptions forward'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '95355aae7c28aea8b1123077470d0e0665e67641'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-4-gaps-to-assumptions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A re-draft creates a new draft Estimate Version that keeps none of the previous version's Assumptions. Gaps already converted by an accepted Assumption are no longer open, so they get no new proposal either: the Condition or Contingency, and who accepted it, silently disappear. That is the "assumed away" failure the Register exists to prevent (FR-14, AD-23), and re-drafting is also how the Red Team is re-run.

**Approach:** When `estimates.accept_draft` stores a new draft, it copies every **accepted** Assumption of the version it supersedes into the new version, keeping its kind, wording, hours, origin and acceptance. The proposal job then proposes only for Gaps that are still open.

## Boundaries & Constraints

**Always:**
- **Depends on:** Story 8.1 (draft versions) and 8.4 (Assumptions, proposals, accept).
- **Where:** inside `accept_draft`'s Unit of Work, under the lock it already holds, after the new version and its lines are inserted. The source is the draft version being superseded in that same call (none on a first draft).
- **What is carried:** only Assumptions with `accepted_by` set. Each copy is a new row in the new version with the same `kind`, `wording`, `amount_hours`, `origin_ref`, `accepted_by` and `accepted_at`, a new id, `row_version` 1, positions 1…n in the source order, and `carried_from` = the source Assumption's id. Unaccepted Assumptions are not carried: their Gaps are still open and get fresh proposals.
- **Contingency line link (decided: match by section and title):** a carried Contingency links to the new version's line with the same section and the same title (trimmed, case-insensitive). With no match, or more than one, it is carried with no line and counts as Unallocated contingency. A Condition carries no line. The old `line_id` is never copied.
- **Proposals:** a version whose only Assumptions are carried still gets proposals. "Already has proposals" now means "has an Assumption that is not carried". New proposals are numbered after the carried ones. `unconverted_gaps` is unchanged (open Gaps without an Assumption).
- **Arithmetic:** carried Contingencies count exactly like any other (line Contingency or Unallocated), through the existing domain functions.
- **Accepting:** carried Assumptions are already accepted, so Accept and Accept all ignore them (unchanged behaviour for accepted rows).
- **Trace:** `estimates.estimate_version.created` gains `carried_assumption_count`. Ids and counts only.
- **Read API:** each Assumption gains `carried_from_version` (the source version number, or null).
- **Web:** a carried row shows "Carried from v{n}" next to "Accepted by …". No other change to the Register.
- **Migration:** `0015_estimates_carry_assumptions` adds a nullable `carried_from` (FK to `estimates_assumptions.id`). Grants unchanged; still no DELETE.

**Never:** No **New version** button or `create_version` command, no submit, version list, `v` switcher or `d` diff, no Risks, no changing a carried Assumption, no carrying across Opportunities. These stay in full Story 8.7 `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Carry | v1 has 4 Assumptions, 2 accepted (one a Contingency on a line); re-draft | v2 starts with the 2 accepted, same origin, accepted_by and accepted_at, `carried_from` set; proposals then cover the 2 still-open Gaps | N/A |
| Unaccepted only | v1 has no accepted Assumptions | v2 carries nothing; behaves as today | N/A |
| First draft | No earlier version | Nothing carried | N/A |
| Line match | Carried Contingency on "WMS interface" (Integration); v2 has a line with that section and title | Linked to v2's matching line; its Contingency cell includes the hours | N/A |
| No line match | v2 has no such line, or two | Carried with no line; counted in Unallocated contingency; totals unchanged | N/A |
| Totals | A carried Contingency of 8 h | Counted once in v2's totals | N/A |
| Re-detect | Gaps re-detected between drafts | Converted Gaps untouched; their carried Assumptions keep their origin | N/A |
| Failed draft | The new draft's lines are all invalid | Nothing stored, nothing carried; v1 stays current | Existing retry |
| Trace and privacy | Any carry | `carried_assumption_count` in the event; no wording in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/application/draft.py:183-289` `accept_draft` -- lock at :203 (`repo.lock_opportunity`), `supersede_drafts` at :232, `insert_version` :236-258 (inserts version, lines and Requirement links), trace :259-275, `enqueue_proposals` :276, Red Team :281. Capture the superseded draft's id before :232 and carry after :258, before the trace (so the count goes in the payload).
- `backend/app/modules/estimates/adapters/repository.py` -- `insert_assumptions` :443-465 and `NewAssumption` :409 hard-code `row_version` 1 and can't set acceptance: add a `carry_assumptions` (or extend `NewAssumption` with optional `accepted_by`, `accepted_at`, `carried_from`). `has_assumptions` is the skip check: change to "has a non-carried Assumption". Positions are unique per version.
- `backend/app/modules/estimates/application/assumptions.py` -- skip checks in `_start` :321-331 and `accept_assumption_proposals` :179-185; proposal positions must start after the carried ones.
- `backend/app/modules/estimates/application/estimates.py:203-265` -- read model; add `carried_from_version` (join the source Assumption's version number).
- `backend/app/modules/estimates/adapters/models.py:175-182` -- the assumptions table; add `carried_from`. `line_id` FK doesn't check the version: never copy the old line id.
- `backend/app/platform/trace/catalogue.py:257-271` -- `EstimatesEstimateVersionCreated`: add `carried_assumption_count`.
- Migration `0015_estimates_carry_assumptions`, revising `0014_assessments_red_team`.
- Tests: `backend/tests/test_estimates_assumptions.py:486` `test_a_redraft_gets_fresh_proposals_for_the_gaps_still_open` asserts nothing is carried; rewrite it to the Carry row. `test_estimates_draft.py:382` checks the created payload.
- Web: `web/src/lib/estimates.ts:181-187` `acceptedLabel`, `web/src/components/opportunities/assumptions-register.tsx:121`; regenerate `schema.d.ts` from a local uvicorn, not the Docker `api`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**`, catalogue, migration 0015 -- carry in `accept_draft`, proposal skip and positions, read model
- [x] `backend/tests/test_estimates_assumptions.py` (+ draft payload test) -- every matrix row, against Postgres with the fake gateway
- [x] `web/src` -- `schema.d.ts`, "Carried from v{n}" in the Register, test with axe

**Acceptance Criteria:**
- Given the demo Opportunity with accepted Assumptions, when the Estimate is re-drafted, then the new version's Register still shows them as accepted ("Carried from v1"), the totals include carried Contingencies, and only still-open Gaps get new proposals.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Where:** `accept_draft` reads the current `draft` version (`repo.current_version`) before `supersede_drafts`, and after `insert_version` calls `assumptions.carry_accepted(source, target)`; the count goes into `estimates.estimate_version.created` as `carried_assumption_count` (default 0 in the catalogue, so earlier events still validate).
- **Line match:** the pure `domain.assumptions.carried_line(section, title, candidates)` (trimmed, `casefold`, exactly one match). Only a Contingency whose source line is found is matched; a Condition, or a Contingency with no line, carries none.
- **Repository:** `has_assumptions` became `has_proposed_assumptions` (ignores `carried_from IS NOT NULL`), used by both skip checks; `last_assumption_position` numbers proposals after the carried rows; `insert_carried_assumptions` copies kind, wording, hours, origin, `accepted_by`/`accepted_at`; `assumptions_of(..., accepted_only=True)`; `carried_from_versions(ids)` joins the source's version number for the read model.
- **FK:** `fk_estimates_assumptions_carried_from` with no `ON DELETE` action (psa_app has no DELETE anyway).
- **Chains:** a v3 carries from v2's carried copies, so `carried_from_version` is the immediately preceding version, not the original one.
- **schema.d.ts** regenerated from a dumped `app.main_api.app.openapi()` (same output as a local uvicorn); `carried_from_version` is required and nullable.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind | An accept racing a re-draft is lost (Gap converted, no Assumption in v2) | false | reject | Accept and accept-all take `lock_opportunity` (assumptions.py:546, :581), the same lock `accept_draft` holds (draft.py:204), so they serialise. |
| 2 | blind | Only one superseded version is carried; `previous` might not be a draft | false | reject | `current_version` and `supersede_drafts` both filter `status == "draft"`, and only one draft exists per Opportunity. |
| 3 | blind | Carried even if the origin Gap changed state since | low | reject | A converted Gap is untouched by re-detection (8.4) and the demo has no dismiss; not reachable. |
| 4 | blind | Carried `origin_ref.row_version` is a stale snapshot | false | reject | The intent says to keep the origin; nothing compares it with the live Gap. |
| 5 | blind | No per-Assumption carried trace event | false | reject | The frozen intent fixes the trace to `carried_assumption_count` on the version event. |
| 6 | blind | No CHECK (carried ⇒ accepted) or UNIQUE (version, carried_from) | low | reject | The only writer is `carry_accepted`, which copies accepted rows once; the constraints add guards for states never shown. |
| 7 | blind | "Carried from v2" on a second re-draft, not the version of acceptance | false | reject | The intent defines the label as the source version number. |
| 8 | blind | Position offset untested if carry ever ran after proposals | low | reject | Carry runs only in `accept_draft`, before the version's proposal job exists. |
| 9 | blind | Re-accepting a carried Assumption untested | low | reject | It's the existing accepted-row path (8.4: idempotent 200), already tested. |
| 10 | blind | "v1" isn't openable; no tooltip | low | reject | Cosmetic; the version list is out of scope by intent. |
| 11 | blind | `carried_line` edge tests (empty list, blank titles, already Unallocated) | low | reject | The code handles them (a None source line stays None, no match → None); low value. |
| 12 | verify | No test of a second re-draft (v1 → v2 → v3) | medium | patch | Pre-verified: every carry test re-drafts once. Fixed: v1 → v2 → v3 test added. |
| 13 | edge | Self-FK `carried_from` has no ON DELETE; a version CASCADE delete would fail | low | patch | One-argument direct correction (`SET NULL`) on an unreleased migration. Fixed in 0015 and the model. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
