---
title: 'Story 4.3 + 4.4 (demo scope): Detect Gaps and draft Clarification Questions'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '8f3d0394c8fc673db080eb779a6945fe1f48c4c1'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-5a-extract-requirements.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A list of Requirements doesn't tell the presales engineer what is *missing*: data volumes, versions, integration details, security expectations. Missing information is the root cause of the 20–50% under-estimates (FR-11, FR-12).

**Approach:**
- Add the `gaps` module and the `clarification_agent`.
- After every successful extraction, a `gaps.detect_gaps` job runs the agent over the Opportunity's active Requirements.
- `gaps.accept_gap_detection` stores ranked Gaps, each with a drafted Clarification Question.
- The Gaps tab shows them as ranked cards, with an inspector.

## Boundaries & Constraints

**Always:**
- **Depends on:**
  - Story 2.5 Part A: active Requirements and `intake.accept_extraction`.
  - Story 2.4: the gateway and agent contract.
  - Story 2.2 Part A: jobs.
  - Story 2.5 Part B: the list plus inspector pattern.
- **Grounding (decided):** there are no Checklists or Knowledge Base in the demo. A Gap is grounded in the Requirements: each Gap must reference at least one active Requirement (at its current version) and carry a `category`. Categories are `data_volumes`, `versions_and_platforms`, `integration_details`, `security_and_compliance`, `non_functional`, `scope_and_ownership`, `commercial` and `other`. The `trigger` is stored as `{kind: "agent_category", category}`, so Checklist and Knowledge triggers can be added later without a schema change.
- **Trigger (decided: automatic):**
  - `intake.accept_extraction` enqueues `gaps.detect_gaps` for the Opportunity in its Unit of Work, through a public `gaps` function, so `intake` doesn't import the internals of `gaps`.
  - If a detection job is still unclaimed for that Opportunity, no second one is added.
  - The job runs at `background` priority with `timeout_s` 900 and `max_attempts` 2.
- **Agent:**
  - `app/agents/clarification_agent/` is `AgentConfig("clarification_agent", "0.1.0", prompt v1, profile chat)`.
  - Requirements enter the prompt only as delimited data labelled `R1…Rn`, with their classification.
  - The output goes in `extensions["clarification_agent"]`: a list of `{title, category, why_it_matters, impact: high|medium|low, impact_basis, related: ["R<n>"…], question: {text, topic}}`.
  - The prompt asks for Gaps that would change the estimate, phrased as customer-ready plain-language questions, with no duplicates.
- **Accept (`gaps.accept_gap_detection`, one Unit of Work after the model call):**
  - Each candidate is validated. It needs a title (1–200 characters), a known category, why it matters (1–1,000), an impact and its basis, at least one related label that resolves to an active Requirement, a question text (1–1,000) and a topic (1–80).
  - Invalid candidates are dropped and counted.
  - If every candidate is invalid, the job retries once. After that it fails with `output_invalid`.
- **Storage:**
  - `gaps_gaps` columns: `id`, `opportunity_id`, `title`, `category`, `trigger` (jsonb), `why_it_matters`, `impact`, `impact_basis`, `origin` (`detected`), `status` (`open | superseded`), `detection_id`, `row_version`, `created_at`.
  - `gaps_gap_requirements` columns: `gap_id`, `requirement_id`, `requirement_version`.
  - `gaps_clarification_questions` columns: `id`, `gap_id` (unique), `text`, `topic`, `status` (`drafted`), `status_changed_at`, `row_version`.
  - `gaps_detections` columns: `id`, `opportunity_id`, `status` (`queued|running|succeeded|failed`), `error_code`, `gap_count`, `dropped_count`, `created_at`, `finished_at`.
- **Re-run:** a new detection marks every `open`, `detected` Gap of the Opportunity `superseded`, together with its question, then inserts the new set. The demo has no human Gap actions to protect.
- **Trace:** `gaps.gap.raised` and `gaps.clarification_question.drafted` per Gap, plus `gaps.detection.completed` with counts. Agent events use `actor_id = "clarification_agent@0.1.0"`. They carry ids, categories, impacts and counts only, never text.
- **Read API (readers):**
  - `GET /opportunities/{id}/gaps` returns `{items, detection: {status, error_code} | null}`.
  - Items are open Gaps sorted by impact (high, medium, low), then `created_at`.
  - Each item has its related Requirements (`id`, `version`, `label`, a text excerpt of up to 140 characters) and its question.
  - `POST /opportunities/{id}/gap-detections` (new action `gaps.detection.start`, owner and collaborators except sales representatives) retries a failed detection. It returns 409 while one is queued or running.
- **Web: Gaps tab (minimal 4.4):**
  - 32px card rows: impact label with a neutral 3-segment bar, a category label in meta type, the title, and a "Draft" question pill.
  - `j`/`k`, arrows and Enter open the inspector, like the Requirements list.
  - The inspector shows the title, why it matters, impact and basis, the related Requirements as chips with their excerpts, and the question with its topic in a bordered, read-only block.
  - The header shows "Detecting Gaps" with a running dot while detection is queued or running, polling every 2 s and pausing while the tab is hidden. On failure: "Gap detection failed: <reason>", with Retry for those allowed.
  - Empty: "Gaps appear here after Requirements are extracted."
  - Sales representatives see the same view, read-only.

**Never:**
- No Checklists, mandatory Gaps or Knowledge triggers.
- No dismiss, reopen or impact change.
- No question edit, merge, drop, approve, export or answers.
- No "Possibly answered".
- No live Overview count or tab badge. No command-palette search.
- No `make eval-gaps` gate.

All of these are `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Auto-queue | Extraction accepted | One detection job queued in the same transaction | N/A |
| Coalesce | Two extractions while 1 job is unclaimed | Still one queued job | N/A |
| Happy | Fake agent returns 4 valid candidates over R1–R5 | 4 open Gaps, each with 1 drafted question and resolved Requirement links at their versions; events; `succeeded` | N/A |
| Bad label | A candidate cites `R99` | Dropped; `dropped_count` 1; the others stored | N/A |
| All invalid | Every candidate invalid, twice | `failed`, `output_invalid`; no Gaps written | Retry offered |
| Re-run | Detection runs again | Earlier open Gaps `superseded` and hidden; the new set shown | N/A |
| Sort | High, low and medium Gaps | Listed high, medium, low | N/A |
| No Requirements | No active Requirements | `succeeded`, 0 Gaps, no model call | N/A |
| Gateway down | Model unavailable until the job dies | `failed`, `model_unavailable` | Retry offered |
| Who | Sales rep POSTs a retry / reads the list | 403 / 200 | N/A |
| Privacy | Any run | No Requirement or question text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/` (new, mirroring `intake`'s layout) -- `domain/` (categories, impact order, candidate rules), `application/` (detection job, `accept_gap_detection`, list query, retry command, `public.py` exposing `enqueue_detection(uow, opportunity_id)`), `adapters/` (tables, repository), `api/` routes. Register the module in `app/modules/__init__.py`, its router in `main_api.py`, its job module in `main_worker._JOB_MODULES`, and its models in `migrations/env.py`. Add import-linter contracts like intake's: gaps uses intake, opportunities and identity only through their `public.py`.
- `backend/app/modules/intake/application/public.py` -- add a query for active Requirements with their versions and texts (for the agent and the read model). The enqueue hook in `accept_extraction` calls `gaps.application.public.enqueue_detection`. If that creates an import cycle, enqueue the gaps job payload by type through the job registry instead, and note it.
- `backend/app/agents/clarification_agent/` (new) -- the agent, schema and `prompts/v1.md`, following `intake_agent`.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- `GAP_DETECTION_START`, excluding sales representatives the same way as Story 2.6's `REQUIREMENT_EDIT`.
- `backend/app/platform/trace/catalogue.py` -- the three event payloads.
- migrations -- the next revision: the four `gaps_*` tables with grants.
- `web/src/app/opportunities/[id]/[tab]/page.tsx` -- route `gaps` to a new `[id]/gaps.tsx`. Reuse the Requirements list and inspector components and tokens, with the impact bar as a small new component.
- Tests -- domain unit tests, job and accept tests with a fake gateway against Postgres, API tests, and web tests with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/gaps/**`, `app/agents/clarification_agent/**`, the intake public query and hook, identity, catalogue, migration, wiring -- module, agent, job, accept, API
- [x] `backend/tests/test_gaps_*.py` -- every matrix row
- [x] Web: `schema.d.ts` (from local uvicorn), actions, `[id]/gaps.tsx`, Gap list, inspector, impact bar, and tests

**Acceptance Criteria:**
- Given the demo Opportunity after extraction, with the cloud profile and the worker running, when detection finishes, then the Gaps tab shows ranked Gaps with plain-language draft questions. Each cites the Requirements it is about, and none asks for something the Requirements already state.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Import cycle (decided in code):** `gaps` reads Requirements through `intake.application.public`, which imports `intake.application.extraction`. A top-level import of `gaps.application.public` in `extraction.py` would be circular, so `accept_extraction` imports it inside the function, just before `gaps.enqueue_detection(uow, opportunity_id)`. It still goes through gaps' public API and the same Unit of Work; the job-registry fallback was not needed. The detection is queued only on the success path that stores Requirements (not for an outdated or `output_invalid` run).
- **Question status:** `gaps_clarification_questions.status` allows `drafted | superseded`, since a re-run supersedes each Gap "together with its question".
- **"All invalid":** acceptance raises `ModelOutputInvalidError` and writes nothing, so the queue retries the job once (`max_attempts` 2); the final attempt marks the detection `failed` / `output_invalid`. An empty candidate list is a valid result (0 Gaps, earlier ones superseded).
- **Validation extras:** labels are resolved against the Requirements read, and only those still active at the version read count. Unknown labels are ignored when another resolves. Repeats of an earlier candidate (same category and title, ignoring case and spacing) are dropped and counted. The agent schema keeps `category` and `impact` as enums (constrained decoding) but puts no length limits on text, so one bad candidate is dropped rather than failing the reply.
- **Read API extras:** `GapList.can_start_detection` (like `can_start_extraction`) drives the Retry button. A related Requirement's `label` is its `R<n>` position among the active Requirements, or `Superseded` once it isn't active; the excerpt comes from that Requirement version's immutable history row. The 409 code is `gap_detection_in_progress`.
- **Stale runs:** as for extractions, a detection `queued`/`running` past both attempts' timeouts plus a minute reads as `failed` / `model_timeout`, and is recorded as such on the next queue or start.
- **Trace payloads:** `gaps.gap.raised` `{detection_id, category, impact, requirement_ids}`, `gaps.clarification_question.drafted` `{gap_id}`, `gaps.detection.completed` `{gap_count, dropped_count, requirement_count, superseded_count}`.
- **Tests:** the intake test fixture `_hidden_jobs` now also hides `gaps.detect_gaps` jobs and retires them after each test, since every accepted extraction queues one.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|--------|---------|---------|-------|----------|
| 1 | verification-gap | Timeout / output_invalid codes and the cancellation branch of `detect_gaps` untested | medium | patch | Pre-verified; intake has these tests, gaps' parametrize has one case. |
| 2 | verification-gap | `_resolvable` (Requirement changed between read and accept) untested | medium | patch | Pre-verified; no test changes a Requirement between `_start` and accept. |
| 3 | verification-gap | "Superseded" chip label and version-pinned excerpt untested | medium | patch | Pre-verified; no test references `INACTIVE_LABEL` or `version_texts`. |
| 4 | verification-gap | `fail_stale` on auto-queue untested | medium | patch | Pre-verified; only the POST path's stale handling is tested. |
| 5 | verification-gap | Inspector clearing after a poll drops the selected Gap untested | low | patch | Pre-verified; no web test selects then polls the Gap away. |
| 6 | blind | Editing a Requirement doesn't re-queue detection | false | reject | Spec's decided trigger is "after every successful extraction"; an edited Requirement stays active by id so its chip keeps `R<n>` (not "Superseded"). |
| 7 | blind | UI can only re-run after a failure | false | reject | Spec: Retry "On failure"; re-run controls are not in the demo slice. |
| 8 | blind + edge | `stale_after()` measured from `created_at` can fail a slow-queued detection | low | reject | Same rule as intake's `stale_after`; one worker and one Opportunity in the demo make a >31 min queue wait unlikely; the fix needs a new `started_at` column. |
| 9 | blind + edge | Requirement changed mid-call leads to retry / `output_invalid` | low | reject | The retry's `_start` re-reads current versions, so attempt 2 recovers; only an extra model call in a rare race. |
| 10 | blind | Outdated run still spends a model call when a newer one is merely queued | low | reject | Rare; the newer run supersedes; the fix adds a branch. |
| 11 | blind | Timeout / cancel tests missing | — | merged into 1 | Same gap as row 1. |
| 12 | blind | No cap on prompt size or Gap count | maybe-false | defer | Demo Opportunities are small; whether a large one overflows the cloud model's context is unverified. |
| 13 | blind | Detection read model omits counts, times and id | false | reject | Spec defines `detection: {status, error_code}`. |
| 14 | blind | Trace `requirement_ids` without versions | low | reject | Spec: events carry ids; versions are in `gaps_gap_requirements`. |
| 15 | blind | Gaps tab misses a detection queued while it is open | low | reject | Extraction is started from the Requirements tab; navigating to Gaps re-reads from the server. |
| 16 | blind | Front-end 15 min poll limit vs back-end 31 min stale rule | low | reject | The UI says "reload to check"; a reload shows the true state. |
| 17 | blind | Partly resolvable labels dropped silently | low | reject | Spec requires at least one resolvable label; matches the rule. |
| 18 | blind | Cancellation always recorded as `model_timeout` | low | reject | Same as intake; the CHECK allows only the three spec codes. |
| 19 | blind + edge | Enqueue failure rolls back the extraction (coupling) | false | reject | Spec requires the enqueue in `accept_extraction`'s Unit of Work. |
| 20 | blind | No index on `gaps_gaps.detection_id` | low | reject | Never queried by `detection_id`. |
| 21 | blind | Excerpt falls back to `""` | false | reject | Every version row exists (backfilled in 0010, written on insert and edit). |
| 22 | blind | `QuestionPill` ignores `question.status` | false | reject | Only open Gaps are listed, and their questions are always `drafted`. |
| 23 | blind | `version_texts` returns an unused classification | low | reject | Cosmetic. |
| 24 | edge | `created_at = now()` at transaction start can misorder detections | low | reject | Extraction acceptance is serialised per Opportunity by its lock; concurrent inserts for one Opportunity don't happen. |
| 25 | edge | App vs DB clock skew in `_detection` | low | reject | API and DB share a host locally; `start_detection` calls `fail_stale` first. |
| 26 | edge | Retry answered 409 with a still-failed list gives no feedback | false | reject | `start_detection` fails stale runs before checking, so 409 means one is genuinely queued or running, and the reload shows "Detecting". |
| 27 | edge | Non-model exceptions recorded as `model_unavailable` | low | reject | Spec allows three codes; a new code means a schema change. |
| 28 | edge | New `initial` after a stall doesn't restart polling | low | reject | Needs a router refresh after 15 min of detecting; a reload works. |
| 29 | edge | Hidden-tab time counts toward the poll limit | low | reject | After 15 min hidden the tab says "reload to check"; a reload works. |
| 30 | edge | Stale check from `created_at` (repository) | — | merged into 8 | Same root cause. |
| 31 | edge | `newer_succeeded` ordering via `now()` | — | merged into 24 | Same root cause. |
| 32 | verification-gap | Single-case parametrize | — | merged into 1 | Same gap. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
