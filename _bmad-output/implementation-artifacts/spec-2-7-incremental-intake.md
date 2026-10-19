---
title: 'Story 2.7 (demo slice): Incremental intake with pending changes'
type: 'feature'
created: '2026-10-19'
status: 'done'
baseline_commit: 'e19bb2c34839f7fd2f9ef4f59b8e9455ba985c9a'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-6-edit-and-confirm-requirements.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every extraction supersedes all unlocked Requirements and inserts fresh rows with new ids. Locked ones are skipped silently, so a new Source can neither improve a human-edited Requirement nor keep stable ids for Gaps, Assessments and Estimates (FR-7, AD-11).

**Approach:** Keep the intake agent as it is (all parsed Sources in, same prompt and schema). Reconcile its proposals against the active Requirements in `accept_extraction`: add new ones, version changed unlocked ones in place, and turn changes to locked ones into pending changes. A human accepts or rejects those in a diff view. The Requirements tab also lists the Assessments that used outdated Requirement versions.

## Boundaries & Constraints

**Always:**
- **Matching (pure domain, no DB or LLM):** a proposal matches the active Requirement it shares the most cited passages with, where a shared passage means overlapping spans in the same source version. Ties go to the oldest Requirement. Failing that, it matches equal normalised text (case-folded, whitespace-collapsed). Matching is one-to-one.
- **Changed** means the proposal cites at least one passage the Requirement does not already link **and** its text or classification differs. Anything else that matches is unchanged and nothing is written. A rerun with no new Source therefore changes nothing, and rewording alone never reverts a human edit.
- **Outcomes per proposal:**
  - Unmatched → a new Requirement.
  - Changed and unlocked → same id, `version+1`, a history row, and the new passages linked.
  - Changed and locked → `intake.propose_requirement_change`.
  - **Decision (human):** an active, unlocked, extracted Requirement that a rerun does not produce again is **kept** unchanged. Reruns only add or change; nothing is superseded any more.
  - **Decision (human, review):** passages in *different* versions of the same Source also count as shared when their quoted text is equal after `normalised_text`. Existing passages' text is read from their Source version's extracted-text artifact. A passage that matches this way is not "new" either, so a re-upload with the same wording maps onto the existing Requirements and writes nothing.
- **Decision (human, review):** a person's **edit** (Story 2.6 `PATCH`) of a Requirement with an open change marks that change `superseded` in the same Unit of Work, because the human's newer wording wins. Confirming leaves it open. A later extraction may propose again against the new version.
- **Pending change:** new table `intake_requirement_changes` with `id`, `requirement_id`, `base_version`, `text`, `classification`, the proposed passage ids, `status` (`open`, `accepted`, `rejected`, `superseded`), `reason`, `row_version`, `extraction_id`, `decided_by` and `decided_at`.
  - At most one `open` change per Requirement; a newer proposal supersedes the open one.
  - Proposing a change that is already open, or one rejected earlier with the same proposed passage set, writes nothing.
  - Proposing bumps the Requirement's `row_version`.
- **Accept:** `POST /opportunities/{id}/requirements/{rid}/change/accept` with `If-Match: <requirement row_version>`. It applies the proposed text and classification as a new version, links the new passages, keeps the Requirement locked with origin `human`, and marks the change `accepted`.
- **Reject:** `POST /opportunities/{id}/requirements/{rid}/change/reject` with `If-Match: <requirement row_version>` and a `{reason}` of 1 to 500 code points. It records the reason and marks the change `rejected`.
- **Accept and Reject both:** need `intake.requirement.edit`, so sales representatives get 403. A stale header is 412, a missing header 428, and no open change 409 `no_pending_change`.
- **Trace:** `intake.requirement_change.proposed`, `.accepted` and `.rejected` carry ids and versions only; the reason is never in the trace. Unlocked version bumps trace `intake.requirement.edited` with actor `intake_agent@…`. Gap detection is still enqueued after every accepted extraction.
- **Read model:** `Requirement.pending_change` is null or `{id, text, classification, evidence[], proposed_at}`.
- **Assessments notice:** a new assessments read, `GET /opportunities/{id}/assessments/outdated`, lists the current Assessments with at least one Requirement pin (findings or effort) whose version is older than the Requirement's current version, or whose Requirement is no longer active. Each item is `{id, agent, label, requirement_labels[]}`. Readers of the Opportunity may call it.
- **Web:**
  - Row: an amber `text-gap` marker reading "Pending change".
  - Inspector, Pending change section: the current text as a `−` line and the proposed text as a `+` line, both on `bg-diff-tint` (not green/red); a classification change when there is one; the new Evidence chips; **Accept**; and **Reject**, which opens a reason field reusing the Gaps `ReasonInput`, made shared. 412 shows the existing stale notice with Reload.
  - Tab notice when the outdated list is non-empty: "These Assessments used Requirements that have changed since: …", plus a link to the Assessments tab. Nothing is rerun automatically.
  - Sales representatives see the marker and the diff but no Accept or Reject.

**Never:** no prompt or schema change to `intake_agent` and no eval-set change. No automatic rerun of Assessments, Gaps or Estimates. No pending change for unlocked Requirements. No SSE for the Requirements tab (polling stays). No View diff after a 412. No split, merge or delete.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New info | A new Source adds one new requirement and refines unlocked R1 | One new row; R1 keeps its id at v2 with the new passage; other rows unchanged | N/A |
| Rerun, nothing new | A rerun with the same Sources, reworded output | No writes to any Requirement | N/A |
| Locked target | R2 edited by a human; a new Source refines it | R2 unchanged; one open change; amber marker | N/A |
| Second proposal | A newer proposal for R2 | The old change is `superseded`; one open change | N/A |
| Re-proposal after reject | The same passages are proposed again | Nothing written | N/A |
| Accept | Current `If-Match` | v+1 with the proposed text, new evidence linked, change `accepted` | 412 stale / 428 missing / 409 none open |
| Reject | Reason given | Change `rejected`, reason stored, Requirement unchanged | 422 when the reason is blank or over 500 |
| Sales rep | Accept or reject | 403 | N/A |
| Re-upload | Source S1 re-uploaded as v2 with the same sentences; the model rewords | Matched across versions by passage text; nothing written, no duplicates | N/A |
| Edit while pending | A person edits R2, which has an open change | The change becomes `superseded`; R2 at its next version, no pending change | N/A |
| Outdated Assessments | An Assessment pinned R1 v1, and R1 is now v2 | Listed with label R1 | Empty list → no notice |

</frozen-after-approval>

## Code Map

- `backend/app/modules/intake/application/extraction.py:195-293` `accept_extraction` -- replace the `supersede_extracted` and insert loop with reconciliation; keep the outdated-run and `output_invalid` branches and the gaps enqueue as they are.
- `backend/app/modules/intake/domain/requirements.py` -- the new pure `reconcile(proposals, existing) -> plan` next to `resolve_requirements:162`.
- `backend/app/modules/intake/adapters/requirements_repository.py` -- reuse `passage:268` and `insert_requirement:315`. `supersede_extracted:293` loses its only caller, so remove it. Add the active Requirements with their passage spans, a version bump, evidence linking, and change insert, read and update.
- `backend/app/modules/intake/adapters/models.py:159-242` -- the `intake_requirement_changes` model. Migration `0031_intake_requirement_changes` (down `0030_gaps_question_sent`).
- `backend/app/modules/intake/application/requirement_edits.py:54-82` -- reuse `_stale`, `_expected`, `_authorized` and `_load` for accept and reject. Put `propose_requirement_change` there and export it through `public.py` (Epic 4 calls it later).
- `backend/app/modules/intake/application/{models.py:78,requirements.py:85-158}` and `api/routes.py:242-420` -- `pending_change` in the view, plus the two routes reusing `_IF_MATCH`, `_edit_responses` and `_with_etag`.
- `backend/app/platform/trace/catalogue.py:185-203` -- three payloads following `IntakeRequirementEdited`.
- `backend/app/modules/assessments/` -- `application/public.py` and the repository for pins (`adapters/models.py:115-130,235-282`), a new `outdated` query that reads `intake.active_requirement_snapshots`, and its route. assessments may import intake public, never the other way.
- `web/src/components/opportunities/{requirements-list.tsx:200-265,794-852,requirement-inspector.tsx:102-226,gap-inspector.tsx:440}` and `web/src/lib/{requirements.ts,gaps.ts:310}` -- the marker, the diff section, `ReasonInput` extracted to `web/src/components/opportunities/reason-input.tsx`, and the notice. `web/src/app/opportunities/{actions.ts,data.ts:120}` -- accept, reject and outdated. `npm run gen:api` against a fresh local backend.
- Tests: `backend/tests/test_intake_extraction.py:631` (`test_a_rerun_supersedes…` becomes "a rerun keeps unproduced Requirements"), the `FakeGateway` and `out` helpers there, and `test_intake_requirement_edits.py:516`; web tests next to the components, with `axeViolations`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/domain/requirements.py` + `backend/tests/test_intake_requirements_domain.py` -- `reconcile` and unit tests for matching, ties, changed versus unchanged
- [x] `backend/migrations/versions/20261019_0031_intake_requirement_changes.py`, intake models, repository, extraction, requirement_edits, trace, routes -- reconciliation, propose, accept, reject
- [x] `backend/tests/test_intake_incremental.py` -- every matrix row against Postgres
- [x] `backend/app/modules/assessments/**` + `backend/tests/test_assessments_outdated.py` -- the outdated read and route
- [x] `web/src/lib/api/schema.d.ts`, actions, the Requirements list and inspector, `reason-input.tsx`, and tests -- marker, diff, accept, reject, 412, notice, hidden for sales reps, axe

**Acceptance Criteria:**
- Given confirmed Requirements on the demo Opportunity, when a new email Source refining one of them is added, then that Requirement shows Pending change, the diff shows `−`/`+` lines with the new Evidence, and Accept makes it the next version without touching the others.
- Given CI, when it runs, then the backend and web checks pass, and `make eval` is unaffected.

## Implementation Notes

- **"A passage the Requirement does not already link"** is read as a proposal span that overlaps none of the Requirement's cited passages (same Source version), not an exact span match: a rerun that quotes a slightly different span of the same sentence is not new information. Only those non-overlapping passages are linked (on a version bump or an accept) and stored as a pending change's `passage_ids` (sorted).
- **Text comparison** for "changed" and for the fallback match uses the normalised text (case-folded, whitespace-collapsed), so a case or spacing difference alone is unchanged.
- **Matching order:** all (proposal, Requirement) pairs with shared passages are matched greedily by most shared, then oldest Requirement, then earliest proposal; the remaining proposals then match the oldest unmatched Requirement with equal normalised text.
- **Race with a human lock:** the unlocked version bump is a conditional UPDATE (`locked_by_human = false` at the row version read); if a person locked it in between, the change becomes a pending change instead.
- **Reject** bumps the Requirement's `row_version` (its read model changed), like proposing does; accept goes through the Story 2.6 edit path (origin `human`, locked, next version, history row by the user). Order of checks: 428 (no header), 412 (stale), then 409 `no_pending_change`.
- **`IntakeExtractionCompleted.requirement_count`** still counts the resolved proposals; the log line `intake.extraction_accepted` now carries `add_count`, `version_count`, `propose_count` and `unchanged_count` (the old `superseded_count` is gone).
- **`intake.requirement_change.proposed`** carries `change_id`, `base_version` and `superseded_change_id`; accepted/rejected carry `change_id` and `version`.
- **Stale ORM rows:** the Requirement UPDATE … RETURNING queries now use `populate_existing`, since reconciliation reads the same rows earlier in the Unit of Work.
- **Outdated Assessments** item `label` is the agent's role ("Engineering Agent"); `requirement_labels` are `R<n>` in order, then `Superseded` once for pins on Requirements no longer active. The web refreshes the notice after an accepted change and when a polled extraction finishes.
- **Tests that relied on re-extraction superseding** (Red Team, specialists, conflicts, estimates and Gaps "reads as superseded") now mark the Requirement superseded directly (`test_intake_extraction.supersede`).
- **Review decision, cross-version matching:** `PassageKey` carries the passage's normalised quoted text (outside its identity); `overlaps` also counts passages in different versions of the same Source with equal text, for matching and for "new passage". Proposal texts come from the extraction's Sources; existing passages' texts from their Source version's extracted-text artifact (`texts.extracted_text`, a file read inside `accept_extraction`'s Unit of Work, no model call; `accept_extraction` takes an optional `store`).
- **Review decision, edit while pending:** `edit_requirement` marks the Requirement's open change `superseded` (no decider, no reason) in the same Unit of Work when the edit writes a new version; a no-op edit and confirm leave it open.

## Spec Change Log

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Accepting a change proposed against an older version overwrites a later human edit; editing does not close the open change (blind, edge ×2, verification-gap other) | medium | `accept_requirement_change` never compares `base_version`; `edit_requirement` leaves the change open. The `−` line shows the current text, but the spec is silent on edits while a change is open | intent_gap → resolved by the human; decisions in the frozen block |
| 2 | A re-uploaded Source (new version) turns reworded proposals into duplicate Requirements; the old ones stay active (blind, edge) | medium | Frozen matching needs overlapping spans in the *same* Source version; the text fallback needs equal wording. Re-uploads are a Story 2.1 feature | intent_gap → resolved by the human; decisions in the frozen block |
| 3 | Nothing makes a Requirement inactive any more; the Superseded paths are reachable only through test SQL (blind) | low | A consequence of the human's Keep decision; merge and delete are post-demo | reject |
| 4 | A rejected change with no passages would suppress every later passage-less proposal (blind) | low | Only extraction proposes today, and `reconcile` proposes only with ≥1 new passage; matters for Epic 4 Gap answers | reject |
| 5 | `propose_requirement_change` doesn't check the lock; the VERSION fallback fires on an inactive or bumped row (blind, edge) | low | No production path makes a row inactive; an unlocked row's `row_version` moves only by locking writes; narrow race | reject |
| 6 | `propose` loads the Requirement before locking the change, so a concurrent accept leaves a stale `base_version` (edge) | low | Needs an accept in the same instant as an extraction's acceptance | reject |
| 7 | Two concurrent proposers hit the partial unique index (edge) | false | The only proposer, `accept_extraction`, holds the Opportunity's advisory lock (`repo.lock_opportunity`), so proposals are serialised | reject |
| 8 | New corroborating Evidence isn't linked when the text is unchanged (blind) | false | The frozen intent says any other match is unchanged and nothing is written | reject |
| 9 | `requirement_count` counts proposals; Gap detection is queued after a no-op rerun (blind) | low | The web doesn't show the count; the enqueue behaviour predates this story | reject |
| 10 | Agent refinements are traced as `intake.requirement.edited` (blind) | false | The spec asks for exactly that event with actor `intake_agent@…`; the catalogue docstring was updated | reject |
| 11 | The outdated-Assessments notice isn't refreshed after an inline edit (blind, edge, verification-gap other) | low | `save()` never calls `refreshOutdated()`; one-line fix | patch |
| 12 | The reject reason's limit and message are borrowed from Gaps; `reason` has no `max_length` in the schema (blind) | low | Same 500 limit and both messages correct; cosmetic | reject |
| 13 | Missing indexes on `(requirement_id, status)` and `extraction_id`; `passage_ids` has no FK or non-empty check (blind) | low | A handful of rows per Requirement; ids come from `repo.passage` in the same Unit of Work | reject |
| 14 | `_EDIT_DESCRIBED[409]` is set after the fact on a module-level dict (blind) | low | No current route is affected; direct fix: put 409 in the literal | patch |
| 15 | Rejection reason and decider are never shown (blind) | low | The spec doesn't ask for it; stored for audit | reject |
| 16 | The outdated notice has no `role="status"` (blind) | low | Direct fix | patch |
| 17 | Reject form's Cancel stays enabled while the reject is in flight (blind) | low | Direct fix: `disabled={edit.busy}` | patch |
| 18 | Comment grammar "R1 and R2 is" in `test_conflicts.py` (blind) | low | Direct fix | patch |
| 19 | The notice refresh after a polled extraction is untested (verification-gap) | medium | Gap pre-verified: the polling tests don't mock `loadOutdatedAssessments`, and the `.catch` swallows the error | patch |
| 20 | The three new trace labels aren't pinned by a test (verification-gap) | low | Gap pre-verified | patch |
| 21 | The "locked since it was read" fallback in `_reconcile` is untested (verification-gap) | medium | Gap pre-verified; needs an injected race | defer |
| 22 | The pending change's chip label falls back to `S0` (edge) | low | Same fallback as existing Evidence (`requirements.py:94`); proposed passages belong to the Opportunity's numbered Sources | reject |
| 23 | `refreshOutdated` may resolve after unmount or an Opportunity change (edge) | low | The section is keyed by Opportunity id and remounts; a set on an unmounted component is a no-op | reject |
| 24 | Reject with a blank reason and no `If-Match` gives 422, not 428 (edge) | low | Same as Story 2.6 row 18 | reject |
| 25 | Pass 2: the reject suppression ignores text and `base_version` and never expires (blind) | false | The frozen intent says a change "rejected earlier with the same proposed passage set writes nothing"; the test pins it on purpose | reject |
| 26 | Pass 2: the fallback propose on an inactive Requirement raises `NotFoundError` and fails the extraction (blind, edge) | low | carried: row 5 | reject |
| 27 | Pass 2: no way to retire Requirements (blind) | low | carried: row 3 | reject |
| 28 | Pass 2: an edit that supersedes the open change leaves no trace event of its own (blind) | low | The edit itself is traced (`intake.requirement.edited`) in the same Unit of Work; a new event or field adds catalogue surface | reject |
| 29 | Pass 2: a proposal's `row_version` bump gives an open view a 412 that names the last person, not the agent (blind) | low | The list is re-read when the polled extraction finishes, so the window is a view left open past that; fixing it needs new changer logic | reject |
| 30 | Pass 2: no schema `max_length` on the reason; 422 before 428 (blind) | low | carried: rows 12 and 24 | reject |
| 31 | Pass 2: the client reason limit and message are borrowed from Gaps (blind) | low | carried: row 12 | reject |
| 32 | Pass 2: the outdated notice isn't re-read after the `no-change` reload or a 412 Reload (blind) | low | `refresh()`/`reload()` don't call `refreshOutdated()`; direct fix | patch |
| 33 | Pass 2: the notice's `role="status"` region mounts already holding its text, so it may not be announced (blind) | low | Direct fix: keep the region mounted and render its content conditionally | patch |
| 34 | Pass 2: missing indexes (blind) | low | carried: row 13 | reject |
| 35 | Pass 2: tests missing for an effort-only pin, outdated after an extraction VERSION or accept, and migration constraints (blind) | low | The outdated read is covered by the Finding and effort pins in `_assessed` and by the PATCH-made version; the version source doesn't matter to the query | reject |
| 36 | Pass 2: cited Source texts are re-read in the Unit of Work on every run; `store=None` silently disables matching (blind) | false | A file read is not a model or HTTP call; `extracted_text` falls back to the configured store when `store` is None (`texts.py:27`) | reject |
| 37 | Pass 2: accept can overwrite a newer human edit (edge) | false | An edit now marks the open change `superseded`, so accept returns 409 `no_pending_change` | reject |
| 38 | Pass 2: the fallback propose's `_load` returns a stale identity-map row (edge) | low | Inside the race in row 21; deferred with it | reject |
| 39 | Pass 2: propose loads the Requirement before a concurrent accept or edit commits (edge) | low | carried: row 6 | reject |
| 40 | Pass 2: a missing older Source text disables cross-version matching (edge) | low | Cited versions are parsed (passages exist only for parsed versions); needs a lost blob | reject |
| 41 | Pass 2: overlapping `refreshOutdated` responses can land out of order (edge) | low | Needs two writes within one request's latency; fix adds a request counter | reject |
| 42 | Pass 2: the new web actions (accept, reject, outdated) are untested (verification-gap) | medium | Gap pre-verified: component tests stub the actions | patch |
| 43 | Pass 2: the refresh after a save is untested (verification-gap) | medium | Gap pre-verified | patch |
| 44 | Pass 2: the locked-since-read fallback is untested (verification-gap) | medium | carried: row 21 | defer (already logged) |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
