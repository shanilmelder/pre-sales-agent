---
title: 'Story 6.6: Blocking Findings and overrides'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
baseline_commit: 'c363dfe1d7e5817628eba8e02d583131bf0462a5'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-4-critic-review.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Critic and Red Team Findings are insert-only and read-only. A critical Finding can be ignored: nothing records that it was addressed, evidenced or knowingly overridden, and nothing counts what still blocks submission (FR-29).

**Approach:** Give Critic and Red Team Findings a status (`open | resolved | overridden`), a fingerprint and a deterministic `policy_ref`. Add three reason-required commands: Supply Evidence, Mark resolved and Override (plus Re-apply override). Add `assessments.get_blocking_findings(opportunity_id)`. Surface statuses, actions and the blocking count on the Assessments tab.

## Boundaries & Constraints

**Always:**
- **Scope:** only Findings of the current Critic and Red Team Reviews (`assessments_findings`). Specialist `assessments_assessment_findings` are untouched.
- **Blocking:** `get_blocking_findings` returns every `open` + `critical` Finding of the current Critic and Red Team Reviews, with its review kind and version. It is exported from `assessments` public for Epic 8's `estimates.get_submission_blockers`.
- **Fingerprint:** set at acceptance as a hash of `kind`, `category` and the sorted cited Requirement ids (Red Team: also the Estimate line keys; Critic: also the target specialist Finding ids). Existing rows are backfilled in the migration.
- **Discipline and policy_ref (decided, 2-a):** both are set at acceptance by code, never by the model.
  - A Finding is **security discipline** when it cites a specialist Finding of `security_agent`. In practice that means Critic targets.
  - A Finding gets a **policy_ref** `{kind: "checklist_item", checklist_id, version, item_id}` when one of its cited Requirements is linked to a mandatory Gap whose `checklist_item` trigger is a mandatory item on a `security`-domain Checklist.
  - A Finding with a `policy_ref` is not overridable.
- **Evidence (decided, 3-a):**
  - Supply Evidence offers a combobox (Popover + Command) over the Opportunity's active Requirements and source documents.
  - Register `requirement` and `source_document` resolvers in `platform/evidence`, owned by `intake`.
  - Store the refs in `assessments_finding_evidence`.
- **Badge (decided, 1-a):** the Assessments tab gets a blocker-coloured badge with `blocking_count`. It joins `BLOCKER_COUNT_TABS` and stays live like the Gaps and Conflicts badges. This is the one deliberate departure from the new mockup.
- **Commands** (one Unit of Work each, `If-Match` row_version → 428/412, reason 1–1000 chars → 422, trace in the same transaction, only `open` Findings → otherwise 409):
  - `POST …/findings/{id}/evidence` `{refs, note}`: refs validated through `platform/evidence.resolve_all` (422 `evidence_unresolvable`). The Finding becomes `resolved` with kind `evidence_supplied`. Trace `assessments.finding.resolved`.
  - `POST …/findings/{id}/resolution` `{reason}`: becomes `resolved` with kind `addressed`. Trace `assessments.finding.resolved`.
  - `POST …/findings/{id}/override` `{reason}`: under `pg_advisory_xact_lock` on the Opportunity, inserts `assessments_finding_overrides` (finding, review kind + version, person, reason, policy basis). The Finding becomes `overridden`. Trace `assessments.finding.overridden` with person and reason.
  - Re-apply override is the same endpoint called on the newer Finding. The UI pre-fills the previous reason.
- **Override policy (R1):** new action `assessments.finding.override`.
  - Allowed: the Opportunity owner (presales engineer); a Head of Delivery; a security reviewer, only for security-discipline Findings.
  - Sales reps and anyone else get 403. Resolve and Evidence follow the `conflicts.resolve` rules.
  - The `policy_ref` check runs before the role check: 422 `finding_not_overridable` for everyone, platform administrator included.
- **Carry-over:** at acceptance, a new Finding whose fingerprint matches an overridden Finding of an earlier version of the same kind starts `open` and stores `previous_override_id`. The view shows "Previously overridden by {name}: {reason}". Nothing carries over automatically.
- **View fields:** each Finding gets `status`, `resolution` (kind, reason, by, at, evidence), `override`, `previous_override`, `overridable`, `can_resolve`, `can_override` and `row_version`. Each view also gets `blocking_count`.
- **Web (follow the new mockup):**
  - Keep the mockup's Findings table columns: Severity, Type, Finding, Raised by, Evidence.
  - The status pill sits under the Finding title. Open is blocker-coloured when critical, neutral otherwise. Resolved uses the resolved tone with a check icon. Overridden is neutral with a shield. Every pill pairs an icon with a label.
  - Open critical rows also show the mockup's note "Blocks submission until resolved".
  - The Critic and Red Team inspectors gain the actions: **Supply Evidence**, **Mark resolved**, **Override** (reason plus a confirm dialog, like `CancelRunButton`) and **Re-apply override**. Actions are hidden by the `can_*`/`overridable` flags.
  - Errors map like `decisionFailure`. Feedback goes through `useAnnounce`.
- **Privacy:** reasons appear in the trace payload, as Conflicts do. No Finding text goes into logs.

**Never:**
- A submit or Baseline command, or `estimates.get_submission_blockers` itself (Epic 8). Opportunity close clearing blockers (Story 10.5).
- Changing how the Critic or Red Team generate Findings, or the specialist Findings.
- An LLM deciding `policy_ref` or discipline.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Blocking | 2 open critical, 1 open high, 1 overridden critical | `get_blocking_findings` → 2; tab badge 2 | N/A |
| Evidence | Owner supplies a valid ref + note | `resolved`/`evidence_supplied`, trace event, badge −1 | Unknown ref → 422 `evidence_unresolvable` |
| Addressed | Owner with no reason | — | 422 |
| Override ok | Head of Delivery, reason | override row, `overridden`, trace event | N/A |
| Not overridable | Admin overrides a Finding with `policy_ref` | unchanged | 422 `finding_not_overridable` |
| Security reviewer | On a non-security Finding | unchanged | 403 |
| Sales rep | Any command | unchanged, actions hidden | 403 |
| Stale | Old `If-Match` | unchanged | 412 |
| Carry-over | Re-run raises the same fingerprint | new Finding `open` with previous override shown | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/assessments/adapters/models.py:106` `FindingRow` (insert-only docstring), the link tables :135/:153/:170 -- add the columns and `FindingOverrideRow`/evidence rows.
- Migration `0042_blocking_findings` after `20261024_0041_critic_review.py`:
  - Reuse its `_replace_check` helper. The 0014 constraint names are double-prefixed.
  - Grant column-level UPDATE (status, resolution, row_version) only. Overrides and evidence tables are SELECT/INSERT.
  - Backfill fingerprints and `status='open'`.
- `assessments/application/review.py:208` `accept_red_team_review` and `application/critic.py:341` `accept_critic_review` -- set the fingerprint, discipline, `policy_ref` and `previous_override_id`.
- `assessments/application/reviews.py:116` `review_view`, `critic_reviews.py:79`; `application/models.py:46,117` -- extend the views.
- `assessments/api/routes.py` -- the three POST routes. Copy `conflicts/api/routes.py:106-137` (`_IF_MATCH`, `_decision_responses`) and `conflicts/application/decisions.py:202-292` (`resolve_conflict` order; `_checked_version`, `_reason`).
- `assessments/adapters/repository.py:98` lock pattern. `application/public.py` -- export `get_blocking_findings`.
- `platform/evidence.py:89` `resolve_all`. Register resolvers next to `knowledge/application/evidence.py:55`.
- `identity/actions.py`, `identity/domain/policy.py:83,101,162`. Add the action to `scripts/seed_auth0.py:46` for `HEAD_OF_DELIVERY` and `SECURITY_REVIEWER`. The owner comes from `Resource.owner_id`.
- `gaps/domain/gaps.py:703` (mandatory trigger), `knowledge/domain/checklists.py:38` (`security` domain), `domain/assessments.py:30` (`security_agent`).
- `platform/trace/catalogue.py` -- copy `ConflictsConflictResolved` :1081. Subject `assessments.finding`.
- Web:
  - `lib/assessments.ts:356-470` (`FindingRow`).
  - `specialist-assessments.tsx:219-348` (`FindingsTable`), :944 (`CancelRunButton` dialog).
  - `red-team-inspector.tsx`, `critic-inspector.tsx`.
  - `conflict-inspector.tsx:136-247` (reason, `useDecision`).
  - `app/opportunities/actions.ts:2622-2685`.
  - `workspace-tabs.tsx:21,52-92,168` and `app/opportunities/[id]/layout.tsx:36` (badge).
  - `components/ui/pill.tsx`.
  - Regenerate `schema.d.ts` from a local uvicorn.
- Tests:
  - `tests/test_conflicts_resolution.py`, `test_assessments_red_team_api.py`, `test_assessments_critic.py`, `test_authorize.py`.
  - Fixtures `_user` (`test_opportunities.py:45`), `owner()`.
  - Web `conflict-inspector.test.tsx` (mocking + axe).

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261024_0042_blocking_findings.py` + `models.py` -- columns, overrides/evidence tables, grants, backfill
- [x] `backend/app/modules/assessments/**` -- fingerprint/discipline/policy_ref at acceptance, carry-over, the 3 commands, `get_blocking_findings`, views, routes, trace
- [x] `backend/app/modules/identity/**`, `scripts/seed_auth0.py` -- the override action and the R1 policy
- [x] `backend/app/modules/intake/**` -- `requirement` and `source_document` Evidence resolvers, plus a picker query
- [x] `backend/tests/test_assessments_findings_decisions.py` -- every matrix row, the admin-cannot-override proof, grants
- [x] Web -- `schema.d.ts`, the row status pill and blocks note, the inspector actions and dialogs, the Assessments badge, the evidence combobox, tests with axe

**Acceptance Criteria:**
- Given a demo Opportunity with a critical Red Team Finding, when the owner overrides it with a reason, then the pill shows Overridden (shield), the inspector shows who and why, and the blocking count drops without a reload.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- **Second action:** besides `assessments.finding.override`, a `assessments.finding.resolve` action (owner and member grants, sales reps excluded) carries the "`conflicts.resolve` rules" for Supply Evidence and Mark resolved. Only the override action is a role permission (Head of Delivery, security reviewer in `seed_auth0.py`); the owner basis is relational.
- **Storage:** `assessments_findings` gains `status`, `fingerprint`, `security_discipline`, `policy_ref`, `previous_override_id`, `resolution` (JSONB `{kind, reason, by, at}`) and `row_version`; `psa_app` may UPDATE only `status`, `resolution`, `row_version`. Migration `0042_blocking_findings` backfills fingerprints with a literal copy of the domain function (a test keeps them equal); `policy_ref` is not backfilled.
- **Fingerprint keys:** Red Team line keys are `<section>:<normalised title>` (line ids change across Estimate Versions). Critic keys are the cited specialist Finding ids, which change on every run, so Critic carry-over rarely matches.
- **policy_ref in practice:** mandatory Gaps are raised without Requirement links today, so `policy_ref` only appears when such a link exists (the test inserts one).
- **Superseded Findings:** commands on a Finding of a superseded Review answer 409 `finding_not_open`.
- **Evidence:** `GET …/evidence-options` (intake) feeds the picker; Supply Evidence also rejects references of another Opportunity (422 `evidence_unresolvable`).
- **Badge:** the workspace layout reads the Red Team and Critic views for `blocking_count`; the badge re-reads on the `assessments.finding.*` and review-completed trace frames.
- **Verified (implementation run):** backend ruff, mypy, lint-imports, alembic check, full pytest on `psa_test66` (2229 passed, 3 eval tests skipped for want of their own DB URLs); web lint, typecheck, 1905 tests, build.

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge | Supply Evidence accepts any registered kind (`knowledge_chunk`), unchecked by `foreign_evidence` | medium | patch | `EvidenceRefIn.kind` is a free string; `resolve_all` resolves `knowledge_chunk`; `foreign_evidence` skips other kinds. |
| 2 | blind+edge | Acceptance supersedes the Review before taking the Findings lock | false | reject | A command that commits first is serialised before the acceptance's lock and seen by `latest_overrides`; one that waits re-reads the Review as superseded → 409. Same outcome as sequential. |
| 3 | blind+edge | `totalBlocking` undercounts when one Review read fails | low | patch | Sums the non-null reads; direct correction (null unless both read). |
| 4 | blind+edge | Migration doesn't backfill `policy_ref` | low | reject | Mandatory Gaps carry no Requirement links today, so no existing Finding qualifies; fix adds migration logic. |
| 5 | blind+edge | Assessments table/inspector don't follow `assessments.finding.*` frames | medium | patch | Section re-reads only on `PROGRESS_EVENTS` (specialist-assessments.tsx :1325); badge updates, pill stays Open until a 412. |
| 6 | edge | Source missing from `source_numbers` shows S0 | low | reject | Every Source gets a number at creation; unreachable in practice. |
| 7 | edge | Client doesn't pre-validate 1–20 refs | low | reject | The form blocks an empty pick and caps at 20; the API answers 422 otherwise. |
| 8 | blind | Unbounded `version` → 500; no schema max on reason/note | low | patch | Direct field constraints. |
| 9 | blind | Body validated after the lock (blank reason + stale If-Match → 412) | false | reject | Mirrors `resolve_conflict`'s order (version, then reason) on purpose. |
| 10 | blind | Overrides `finding_id` index not unique | low | patch | Direct change in the new migration. |
| 11 | blind | `NewFinding.fingerprint` defaults to "" | low | reject | Every insert path goes through `stamp`; fix adds a constraint for an unshown path. |
| 12 | blind | Evidence table lacks CHECKs, nullable `ref_version` | low | patch | Direct change in the new migration. |
| 13 | blind | Picker hides chosen state; 21st pick silently ignored | medium | patch | `CommandItem` marks only `data-checked`; no visible or accessible state. |
| 14 | blind | 412 names a changer when If-Match was simply wrong | low | reject | Needs a hand-crafted If-Match; adds a branch. |
| 15 | blind | "Blocks submission until resolved" omits override | false | reject | The new mockup's exact copy, kept by the frozen intent. |
| 16 | blind | README: security reviewer must be a collaborator | low | patch | Role has no read permission; one-line doc note. |
| 17 | blind | Resolution `at` (app clock) vs override `created_at` (DB clock) | low | reject | Display-only skew of milliseconds; fix restructures writes. |
| 18 | blind | Missing tests (Critic blocking, superseded, >20 refs, backfill, …) | low | patch | Folded into #19–#23. |
| 19 | verify | Inspector `opportunityId` wiring untested | medium | patch | Pre-verified gap. |
| 20 | verify | `get_blocking_findings` untested on superseded Reviews and Critic Findings | medium | patch | Pre-verified gap. |
| 21 | verify | Foreign `source_document` ref untested | medium | patch | Pre-verified gap. |
| 22 | verify | Non-security mandatory item never tested as overridable | medium | patch | Pre-verified gap. |
| 23 | verify | 0042 backfill never run on existing rows | medium | patch | Pre-verified gap. |
| 24 | verify | `latest_overrides` newest-of-several ordering unpinned | low | defer | Affects only which earlier reason is shown, never blocking. |
| 25 | verify | Critic fingerprints rarely match across runs | false | reject | Frozen intent puts the cited specialist Finding ids in the Critic fingerprint; recorded in Implementation Notes. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test66> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test66> uv run pytest` -- expected: all pass
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
