---
title: 'Story 2.5 (Part A): Extract classified, cited Requirements (demo scope)'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: '0eb56290712b626436e9d38fbb7ef948b82c1a5e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Parsed Sources are just text. The presales engineer still has to read everything to find the Requirements, and nothing links a Requirement back to what the customer said (FR-5).

**Approach:**
- Each successful parse automatically queues an `intake.extract_requirements` job.
- The job runs `intake_agent` through the ModelGateway over all parsed Sources.
- `intake.accept_extraction` turns each verbatim quote into an immutable `source_passage`, then stores classified Requirements that cite them.
- The Requirements tab lists the Requirements by classification and polls while extraction runs.

## Boundaries & Constraints

**Always:**
- **Depends on:**
  - Story 2.2 Part A: jobs.
  - Story 2.4: the gateway, `AgentResult` and `AgentConfig`.
  - Story 2.2 Part B: the extracted text per Source version, readable inside `intake` as `str`, with a parse status of `parsed`.
- **Trigger (decided: automatic):**
  - When a Source version's parse succeeds, intake enqueues `intake.extract_requirements` for the Opportunity (`background` priority).
  - If a not-yet-claimed extraction job is already queued for that Opportunity, no second one is added.
  - A job reads the latest version of every `parsed` Source at the moment it runs.
- **Agent:**
  - `app/agents/intake_agent/` is `AgentConfig("intake_agent", "0.1.0", prompt v1, profile chat)`, with its prompt in `prompts/v1.md`.
  - Source texts enter the prompt only as delimited data blocks labelled `S1…Sn`, never inside the instructions.
  - The output goes in `extensions["intake_agent"]`: a list of `{text, classification, citations: [{source: "S<n>", quote}]}`.
  - Classifications are `functional | integration | data | security | non_functional | commercial`.
  - The model is told to merge duplicates across Sources into one Requirement that cites every passage.
- **Size:** if the combined text exceeds the profile budget (`num_ctx` minus room for the prompt and output, measured in characters / 3.5), the job fails with `input_too_large` and makes no model call.
- **Accept (`intake.accept_extraction`, one Unit of Work, after the model call):**
  - **Resolving quotes:** each quote is resolved to Unicode code-point `[start, end)` offsets in its Source's text. An exact match wins first. Failing that, the match is whitespace-collapsed and case-insensitive, mapped back to the original offsets.
  - **Unresolved quotes:** an unresolved quote is dropped. A Requirement left with no resolved citation is dropped.
  - **Retry:** if anything was dropped, the job makes one retry call naming the failing items by index only. After that, it accepts what resolves.
  - **Passages:** `intake_source_passages` rows are `(id, source_id, source_version, start, end, created_at)`. They are immutable (`psa_app` has no UPDATE or DELETE) and are reused for the same span.
  - **Requirements:** `intake_requirements` columns are `id`, `opportunity_id`, `text`, `classification`, `origin` (`extracted`), `locked_by_human` (false), `status` (`active | superseded`), `version` (1), `row_version`, `extraction_id`, `created_at` and `updated_at`. Links go in `intake_requirement_evidence(requirement_id, passage_id)`.
  - **Re-run:** a new extraction supersedes every `active`, `extracted`, not-locked Requirement of the Opportunity, then inserts the new set. Locked ones (Story 2.6) are never touched.
- **Extraction record:** `intake_extractions` columns are `id`, `opportunity_id`, `status` (`queued | running | succeeded | failed`), `error_code`, `requirement_count`, `dropped_count`, `source_count`, `created_at` and `finished_at`.
  - Trace event: `intake.extraction.completed`, with counts only.
  - On job death: the extraction is marked `failed`, with an `error_code` of `model_unavailable`, `model_timeout`, `output_invalid` or `input_too_large`.
- **API:**
  - `GET /opportunities/{id}/requirements` (readers): `{items: active Requirements, each with evidence [{passage_id, source_id, source_version, filename, label}], extraction: {status, error_code, source_count} | null}`.
  - `POST /opportunities/{id}/extractions` (new action `intake.extraction.start`, owner and collaborators): retries a failed extraction. Returns 409 while one is queued or running.
- **Web:**
  - **Requirements tab:** the Requirements are grouped under the six classifications in the order above, each group headed with its label and count, and empty groups hidden. Each row shows the text and static Evidence labels (`S1 · call.vtt`).
  - **While extracting:** while `status` is `queued` or `running`, the header shows "Extracting Requirements" with a running dot, and the page polls every 2 s until it's done.
  - **Failed:** "Extraction failed: <reason>" with **Retry**, which appears only when the user may start an extraction.
  - **Empty:** "Requirements appear here after Sources are parsed."
- **Privacy:** logs and trace carry ids and counts only, with no source or Requirement text.
- **Decided (2026-10-04):** Story 2.5 is split. Part B, the Evidence inspector, adds the passage API, clickable chips and the highlighted passage in the right pane.

**Never:** No inspector and no passage view (Part B). No editing, splitting, merging or confirming (Story 2.6). No pending changes (Story 2.7). No SSE (Story 2.3). No chunking. No `make eval-intake` gate. No merge lineage events. No tab badge. The deferred items are all `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Auto-queue | A Source parses OK | One extraction job queued | N/A |
| Coalesce | 3 Sources parse while 1 job is unclaimed | Still one queued job | N/A |
| Happy | 2 Sources; fake gateway returns 3 Requirements with exact quotes | 3 active Requirements with passages at the correct code-point offsets; `succeeded`; one trace event | N/A |
| Fuzzy quote | Quote differs only in whitespace or case | Resolves to the original span | N/A |
| Non-BMP | Emoji before the quote | Offsets are in code points | N/A |
| Bad quote | 1 of 3 Requirements cites invented text | One retry call; then 2 kept, `dropped_count` 1 | N/A |
| Merge | Fake returns 1 Requirement citing S1 and S2 | 1 Requirement, 2 passages | N/A |
| Re-run | A second extraction | Earlier extracted ones `superseded`; locked ones untouched | N/A |
| Too large | Combined text over budget | `failed`, `input_too_large` | No model call |
| Gateway down | `ModelUnavailableError` until the job dies | `failed`, `model_unavailable` | Retry enabled |
| Retry API | `POST /extractions` while running | 409 | N/A |
| Who | HoD reader / sales rep collaborator calls `POST /extractions` | 403 / 201 | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/agents/intake_agent/` (new) -- `agent.py` (implements `Agent`, builds the delimited prompt, calls `model_gateway.complete_structured`), `schema.py`, `prompts/v1.md`. The agent never writes (AD-4).
- `backend/app/modules/intake/` -- add `domain/requirements.py` (classification enum, pure `resolve_quote(text, quote) -> (start, end) | None`), `application/extraction.py` (job handler, `accept_extraction`), `application/requirements.py` (list query, retry command), routes and repository functions. Register the job type with the Story 2.2 Part A registry, and hook the enqueue into the Story 2.2 Part B parse-success path.
- Job type sizing -- the gateway's per-attempt timeout (`PSA_MODEL_TIMEOUT_S`, 120 s) × up to 3 attempts, plus the one quote-resolution retry call, can exceed the job layer's default `timeout_s` (300 s). Register `intake.extract_requirements` with a `timeout_s` above the worst case (e.g. 900 s) and `max_attempts` 2. Gateway errors to map: `ModelUnavailableError` → `model_unavailable`, `ModelTimeoutError` → `model_timeout`, and `ModelOutputInvalidError` (including `error_code="truncated"`) → `output_invalid`.
- `backend/app/modules/identity/{actions.py,domain/policy.py}` -- `EXTRACTION_START`, granted to owner and member like `SOURCE_ADD`.
- `backend/app/platform/trace/catalogue.py` -- `IntakeExtractionCompleted`.
- migrations -- the next revision: `intake_extractions`, `intake_source_passages`, `intake_requirements` and `intake_requirement_evidence`, with grants.
- `web/src/app/opportunities/[id]/[tab]/page.tsx` -- route `requirements` to a new `[id]/requirements.tsx`, as was done for `sources`, and reuse the token classes.
- Tests -- domain tests for `resolve_quote` (including non-BMP characters), job and accept tests with a fake gateway against Postgres, API tests, and web component tests with axe.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/agents/intake_agent/*` -- agent, schema, prompt v1
- [x] `backend/app/modules/intake/**`, identity policy, trace catalogue, migration -- domain, job, accept, queries, routes
- [x] `backend/tests/test_intake_extraction.py`, `test_intake_requirements_api.py`, domain tests -- every matrix row
- [x] `web/src/lib/api/schema.d.ts` (regenerated from local uvicorn), actions, `[id]/requirements.tsx`, components and tests -- grouped list, polling, failed and Retry, axe

**Acceptance Criteria:**
- Given the prepared demo Opportunity (anonymised transcript plus two emails) and the cloud profile, when its Sources finish parsing, then grouped Requirements with Evidence labels appear on the tab within a few minutes.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | An extraction stays `running` forever when the job is cancelled (900 s timeout) or the worker is killed on its last attempt. Start then returns 409 indefinitely and the tab never recovers | high | The handler catches only `Exception`; `CancelledError` is a `BaseException`; there is no staleness rule | patch |
| 2 | BH | A run where every proposal is dropped, or the retry fails with nothing resolved, still supersedes the existing Requirements and reports `succeeded` with 0 | high | `accept_extraction` supersedes whenever any Sources were read | patch |
| 3 | BH, ECH | Two extractions can overlap (one `running`, one `queued`), and an older run accepted later replaces the newer results | medium | Coalescing only merges `queued`; accept doesn't check for a newer succeeded run | patch |
| 4 | BH, ECH | The retry reply replaces the first reply wholesale, so items that resolved the first time can be lost | medium | `_extract` swaps `result`; tests only use a strictly better retry | patch |
| 5 | BH, ECH | A Source whose newest version failed to parse is left out, and its Requirements are superseded | medium | `parsed_latest_versions` takes only latest-and-parsed | patch |
| 6 | BH | Retry is offered for `input_too_large`, which fails again every time | low | Direct UI condition plus a guidance sentence | patch |
| 7 | BH, ECH | After the 15-minute poll limit the tab keeps showing "Extracting" with no notice | low | Direct notice | patch |
| 8 | BH, ECH | A succeeded run with 0 Requirements shows the "after Sources are parsed" empty state; "1 Requirements" plural | low | Direct copy | patch |
| 9 | ECH | `ModelGateway(...)` is constructed outside the try, so a construction failure leaks the engine | low | Direct move into the try | patch |
| 10 | ECH | The list doesn't resync when the server re-renders with new `initial` data | low | `users-admin.tsx` already has the sync pattern | patch |
| 11 | VG | No test checks that the worker installs the gateway, so broken wiring would fail every extraction unnoticed | medium | The fixture installs a fake; no test reads the provider in `run` | patch (test) |
| 12 | VG | The 15-minute poll limit is untested | low | Direct test | patch (test) |
| 13 | VG | The live-region announcement on finish is untested | low | Direct test | patch (test) |
| 14 | VG | The not-found message for a failed Retry is untested | low | Direct test row | patch (test) |
| 15 | BH | Unexpected errors are all coded `model_unavailable` | low | The spec allows four codes | reject |
| 16 | BH | The extraction API response is thin (no id, counts or timestamps) | low | Not needed by the UI | reject |
| 17 | BH | No trace event for a user-started run or for a failure | low | Logs carry it; completion is traced | reject |
| 18 | BH, ECH | The input budget is 0 for profiles with `num_ctx` ≤ 12k | low | Both shipped profiles are well above | reject |
| 19 | BH, ECH | A missing Source falls back to an `S0` label | low | Not reachable: evidence always references a read Source | reject |
| 20 | ECH | Two `run()` calls in one process uninstall each other's gateway | low | One worker loop per process | reject |
| 21 | BH | Forged `<<<SOURCE …>>>` fences in customer text | low | Prompt-injection hardening is Story 2.8 | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks:**
- With the worker and Ollama (signed in) running, upload the demo Sources and watch the Requirements appear.
