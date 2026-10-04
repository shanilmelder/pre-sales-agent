---
title: 'Story 2.4: ModelGateway (demo scope)'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: 'd1276c6873baf34c86b068ebd28fb77a87369715'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No code can call a model. Story 2.5's intake agent and every later agent need one governed path to the LLM, with structured output, retries, priority and a record of every call (AD-8).

**Approach:** Add `app/platform/model_gateway/`: a provider-neutral port with an Ollama adapter (native `/api/chat` with `format` set to the JSON Schema), named model profiles, a priority-aware semaphore and a `platform_model_calls` table. Also add `app/agents/contract.py` with `AgentResult` and the `Agent` interface.

## Boundaries & Constraints

**Always:**
- **Port:** `complete_structured(request) -> StructuredResult[T]`. The request carries:
  - messages (system and user);
  - the Pydantic output model `T`;
  - the profile name;
  - the priority (`interactive` or `background`, reusing the job layer's `Priority` from Story 2.2 Part A);
  - a timeout;
  - caller metadata: `agent_id`, `config_version`, and optionally `run_id`, `task_id`, `opportunity_id`.

  The result carries the validated object, the tokens in and out, latency, attempts and the model digest.
- **Ollama adapter:**
  - Calls `POST {PSA_OLLAMA_URL}/api/chat` with `stream: false`, `format` set to `T.model_json_schema()`, and `options` from the profile (`temperature` 0.1 for structured work, plus `num_ctx`).
  - Validates `message.content` with `T.model_validate_json`.
  - On invalid output it retries up to `PSA_MODEL_MAX_RETRIES` (default 2), adding a corrective user message that names the failing field paths only.
  - Tokens come from `prompt_eval_count` and `eval_count`.
  - The digest comes from `/api/tags` and is cached per process. An unknown digest is recorded as `unknown`, not treated as an error.
- **Profiles (decided):**
  - Code-defined named profiles (`model`, `num_ctx`, `temperature`). The default chat profile is `demo-chat` = `gpt-oss:120b-cloud`, `num_ctx` 32768, selected by `PSA_MODEL_PROFILE_CHAT`.
  - A local profile `local-chat` = `qwen3:8b`, `num_ctx` 16384, exists for when the cloud is unavailable.
  - Changing model is a config change, never a code change.
- **Data:** `gpt-oss:120b-cloud` sends prompt text to Ollama's cloud. Until IT approves data handling, only sample or anonymised Opportunities may use it. This is stated in `.env.example` next to the setting.
- **Semaphore:**
  - Per process, with `PSA_MODEL_SLOTS` slots (default 1, which must be ≤ `OLLAMA_NUM_PARALLEL`).
  - Waiting `interactive` calls are always granted before waiting `background` calls, and calls with the same priority are FIFO.
  - The slot is released on success, error or cancellation.
- **`platform_model_calls` columns:** `id`, `agent_id`, `config_version`, `run_id`, `task_id` and `opportunity_id` (all nullable), `profile`, `model`, `model_digest`, `priority`, `input_tokens`, `output_tokens`, `latency_ms`, `attempts`, `outcome`, `error_code` (nullable), `created_at`.
  - `outcome` is one of `ok | invalid_output | error | timeout`.
  - The row is written in its own Unit of Work after the call. No Unit of Work is open during the HTTP call (AD-25).
  - `psa_app` gets SELECT and INSERT.
- **Privacy:** no prompt or response text in logs, rows or exceptions. Logs carry ids, the profile, tokens, latency and the outcome.
- **Errors:** the gateway raises typed errors after recording the row:
  - `ModelUnavailableError` (connection, 5xx);
  - `ModelTimeoutError`;
  - `ModelOutputInvalidError` (retries exhausted).
- **Agent contract (`app/agents/contract.py`):**
  - `AgentResult`, with `contract_version` "1", `findings`, `evidence` (refs `{kind, id, version?, span?}`), `assumptions`, `unknowns`, `risks`, `recommendation`, `confidence` with `confidence_basis`, `needs_human_review`, and `extensions: dict[str, BaseModel]` keyed by agent id.
  - An `Agent` Protocol, `async run(task) -> AgentResult`.
  - An `AgentConfig` dataclass (`agent_id`, `semver`, `prompt_version`, `profile`) defined in code. `actor_id` is `<agent_id>@<semver>`.

**Never:** The following are deferred, with `[post-demo]` entries:
- the OpenAI-compatible adapter;
- the `ollama` compose service, GPU wiring, and the Modelfile build and digest pinning at deploy (host Ollama is used);
- `/api/embed`;
- the DB-owned Agent Registry and its seed;
- run budgets (Story 5.6);
- the structured-output spike across all schemas (Story 2.5 runs it on the intake schema).

There's also no streaming, no tool calling, and no model call from the `api` process.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid | Stub returns schema-valid JSON | Result with object, tokens and digest; one row `ok`, attempts 1 | N/A |
| Request shape | Any call | Body has `format` = the schema, `stream: false`, and the profile's `temperature` and `num_ctx` | N/A |
| Retry then OK | Invalid JSON, then valid | Result, attempts 2. The second request names the failing fields, not the content | N/A |
| Exhausted | Invalid 3 times (retries 2) | `ModelOutputInvalidError`; row `invalid_output`, attempts 3 | Raised |
| Down | Connection refused or 5xx | `ModelUnavailableError`; row `error` | Raised |
| Slow | Exceeds the timeout | `ModelTimeoutError`; row `timeout` | Raised |
| Priority | 1 slot held; `background` waits, then `interactive` arrives | `interactive` gets the slot next | N/A |
| Cancel | A waiting caller is cancelled | The slot isn't leaked; the next waiter proceeds | N/A |
| Privacy | Any outcome | Captured logs and the row contain no prompt or response text | N/A |
| Profile | `PSA_MODEL_PROFILE_CHAT=local-chat` | Request uses `qwen3:8b` | Unknown profile raises at startup |

</frozen-after-approval>

## Code Map

- `backend/app/platform/model_gateway/` (new) -- `port.py` (request, result, errors), `profiles.py`, `ollama.py` (adapter, using `httpx.AsyncClient`), `semaphore.py`, `models.py` (the table), `gateway.py` (ties together the semaphore, adapter, retries and the call row), `smoke.py` (`python -m app.platform.model_gateway.smoke`: one tiny structured call against the live configured profile, printing outcome, tokens and latency only).
- `backend/app/platform/jobs/registry.py` (from Story 2.2 Part A) -- reuse `Priority`. Branch `story/2-4-model-gateway` from `story/2-2a-job-queue`.
- `backend/app/platform/config.py` -- add `ollama_url` (default `http://127.0.0.1:11434`), `model_profile_chat`, `model_slots`, `model_max_retries` and `model_timeout_s`.
- `backend/app/platform/uow.py` -- `unit_of_work(engine)` for the call-row write.
- `backend/migrations/versions/` -- the next revision, `platform_model_calls`, with grants, following `0005`.
- `backend/app/agents/__init__.py` exists and is empty -- add `contract.py`. Import contracts already forbid `app.platform` from importing `app.agents`.
- `backend/pyproject.toml` -- move `httpx` (pinned 0.28.1) into runtime dependencies and update `uv.lock`.
- `compose.yaml`, `.env.example` -- `PSA_OLLAMA_URL=http://host.docker.internal:11434` for `api` and `worker` (with `extra_hosts: host-gateway`), plus the data note.
- Tests -- stub Ollama with `httpx.MockTransport`. Write the call rows with the Postgres fixtures in `tests/conftest.py`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/model_gateway/*`, `config.py`, `pyproject.toml`, `uv.lock` -- the port, adapter, profiles, semaphore and gateway
- [x] migration -- `platform_model_calls`
- [x] `backend/app/agents/contract.py` -- `AgentResult`, `Agent`, `AgentConfig`
- [x] `backend/tests/test_model_gateway.py`, `test_agent_contract.py` -- every matrix row
- [x] `compose.yaml`, `.env.example` -- the Ollama URL and the cloud-data note

**Acceptance Criteria:**
- Given host Ollama running and signed in, when `uv run python -m app.platform.model_gateway.smoke` runs with the default profile, then it prints `ok` with token counts and a call row exists. If the cloud model ignores `format`, record that in Implementation Notes: validation and retries still apply.
- Given CI, when it runs, then `ruff`, `mypy`, `lint-imports`, `alembic check` and `pytest` all pass with no live model needed.

## Implementation Notes

- Smoke (2026-10-04, host Ollama 0.33.3, `demo-chat`): `ok`, attempts 1, 103 in / 72 out tokens, ~0.9 s, digest found in `/api/tags`, call row written. `gpt-oss:120b-cloud` honoured `format` on this tiny schema; larger schemas are untested (Story 2.5 spike).
- `request.profile` is optional: `None` resolves to `PSA_MODEL_PROFILE_CHAT`. The configured name is validated when `Settings` loads, so an unknown profile fails at process start.
- `timeout_s` applies per attempt (each `/api/chat` request), not across retries; the wait for a slot is not timed. `latency_ms` covers all attempts, not the slot wait. Tokens are summed over attempts.
- A retry sends the original messages plus the latest invalid reply (as `assistant`) and a corrective user message naming the failing field paths; earlier retries are not accumulated, and neither is logged or stored. A `done_reason: "length"` reply fails at once as `invalid_output` / `truncated`. A failed call-row write is logged as `model_call.record_failed` and doesn't replace the call's result or error. Field-path parts that are not identifier-like (e.g. dict keys the model invented) are masked as `<key>`.
- Non-2xx statuses (4xx included, e.g. an unpulled model's 404) and a malformed envelope are `ModelUnavailableError` with `error_code` `http_<status>` / `bad_envelope`; connection failures are `connection` / `connect_timeout`.
- A caller cancelled mid-call releases its slot but writes no row (the outcome check allows only the four outcomes).
- `app/platform/model_gateway/__init__.py` re-exports nothing, because `config.py` imports `profiles` and an eager import would be circular.
- `[post-demo]` entries for the Never list were added to `deferred-work.md`.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | VG, BH, ECH | `AgentResult.extensions` (`SerializeAsAny[BaseModel]`) can't be validated from a dict or JSON. The payload is dropped, then dump and `repr` crash | high | VG reproduced `TypeError: 'MockValSer'…` after `model_validate`; the "round_trips" test only dumps | patch |
| 2 | BH, ECH | When `_record` fails (DB), its exception replaces the model result or the typed error, so a paid result is lost | medium | `complete_structured` awaits `_record` unguarded before returning or raising | patch |
| 3 | BH, ECH | `done_reason="length"` (truncated output or context overflow) is retried as invalid JSON with the same prompt, wasting every attempt | medium | The adapter ignores `done_reason`; Story 2.5 extraction outputs are large | patch |
| 4 | ECH | httpx errors that aren't `TransportError` (`DecodingError`, `TooManyRedirects`, `InvalidURL`) escape untyped, with no row | low | The adapter catches only transport and timeout classes; direct widening to `httpx.HTTPError` | patch |
| 5 | ECH, BH | `AgentConfig.profile` accepts any non-empty name, which fails only at the first call | low | `__post_init__` checks non-empty only; direct `get_profile` check | patch |
| 6 | BH | The corrective retry refers to "your previous reply", but the reply isn't in the conversation, which weakens self-correction | low | Stateless `/api/chat`; adding the assistant turn sends nothing new off-box and logs nothing | patch |
| 7 | BH, ECH | An `unknown` digest is never cached, so `/api/tags` is re-queried every call (up to 5 s while Ollama hangs) | low | `digest()` caches only found digests; direct short-TTL cache | patch |
| 8 | VG | The Ollama-down path for the digest lookup is untested | medium | The stub's `/api/tags` always returns 200 | patch (test) |
| 9 | VG | Malformed envelope (`bad_envelope`) and httpx timeout mappings are untested | low | No test hits these codes | patch (test) |
| 10 | VG | No test asserts that a cancelled call writes no row | low | The cancellation test checks only the semaphore | patch (test) |
| 11 | BH | `field_paths` masking, the 20-path cap and over-release are untested | low | Direct tests | patch (test) |
| 12 | BH | The priority and timeout tests rely on sleeps and may flake | low | Waiting on `semaphore.waiting()` is a direct change | patch (test) |
| 13 | BH | No import contract keeps `app.main_api` away from the gateway | low | AD-8 / spec: no model call from `api`; direct contract | patch |
| 14 | BH | README doesn't mention `OLLAMA_NUM_PARALLEL` or `OLLAMA_HOST` for containers on Linux, and host shells that source `.env` get `host.docker.internal` | low | Direct doc lines | patch |
| 15 | BH, ECH, VG | Migration `0007` clashes with Story 2.2 Part B's `0007` (two heads) | low | Known, and planned: re-parent the second at merge time | reject |
| 16 | BH | The cloud profile is the default with no technical enforcement of the anonymised-data rule | false | The user decided on cloud for the demo (frozen block) | reject |
| 17 | BH | No retry on transient errors | low | Job-level retries cover them | reject |
| 18 | BH | No overall time limit across attempts (3 × 120 s) | low | The calling job's timeout bounds it; Story 2.5 Part A must size its job timeout above it | reject |
| 19 | BH | The `connect_timeout` code is effectively unreachable | low | Code naming only | reject |
| 20 | BH | Slot wait time isn't recorded | low | Not in scope; one slot in R1 | reject |
| 21 | BH | A cancelled call leaves no audit row | low | Documented in the spec notes; the outcome set has no `cancelled` | reject |
| 22 | ECH | Token counts as bool or huge ints | low | Ollama returns ints | reject |
| 23 | ECH | Model-invented identifier-like keys pass through `field_paths` | low | Paths go only to the same model and onto the error; not logged by the gateway | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `ollama serve` (if not running), `ollama signin`, then `uv run python -m app.platform.model_gateway.smoke` -- expected: `ok`
