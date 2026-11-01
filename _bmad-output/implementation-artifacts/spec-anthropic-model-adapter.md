---
title: 'Native Anthropic (Claude) adapter for the ModelGateway'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_commit: '075a8780347d77054aa079a6a05bcb6c1a2164b6'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The ModelGateway can only call Ollama and OpenAI-compatible servers, so no Agent can run on Claude. The OpenAI adapter can't serve it: it shares one base URL and key, and sends `temperature` and no `max_tokens`.

**Approach:** Add a third provider, `anthropic`, with an adapter built on the official `anthropic` Python SDK, plus an `anthropic-chat` profile on `claude-opus-5-5`. Agents then move to Claude through the existing profile mechanisms, with no call-site changes.

## Boundaries & Constraints

**Always:** The adapter honours the `ChatAdapter` Protocol and raises only the gateway's typed errors. Error messages, codes and logs never contain prompt text, response text or the key. Every call stays bounded by `timeout_s`. The gateway still validates every reply against the output model. Existing `ollama` and `openai` behaviour is unchanged.

**Never:** No embeddings on this provider (`bge-m3` stays on Ollama). No OpenAI-compatibility shim. No raw `httpx` calls to Anthropic. No `temperature`, `top_p`, `top_k` or `thinking` config in requests. No default Agent moves to Claude (seeded and pinned profiles stay as they are). No database migration. No prompt changes.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid reply | `anthropic-chat`, system + user messages | `system` sent top-level, schema in `output_config.format`, reply text and usage returned | N/A |
| Validation retry | Assistant + corrective user messages | Sent in order after the original turns | Gateway retry loop unchanged |
| Thinking blocks | Reply has `thinking` then `text` | Only `text` blocks form `content` | N/A |
| No text | No `text` block in a non-refusal reply | Nothing returned | `bad_envelope` |
| Truncated | `stop_reason: max_tokens` | `ChatReply(truncated=True)` | Gateway `truncated`, not retried |
| Refusal | `stop_reason: refusal` after fallbacks | No content used | `ModelOutputInvalidError`, code `refusal`, not retried |
| Missing key | `PSA_ANTHROPIC_API_KEY` empty or whitespace | No request sent | `ModelUnavailableError`, code `missing_api_key`; startup unaffected |
| API error | Non-2xx after SDK retries | No content used | `ModelUnavailableError`, code `http_<status>` |
| Slow or down | Timeout / connection failure | No content used | `ModelTimeoutError` / `connection` |
| Embed | Any embed call | No request sent | `ModelUnavailableError`, code `embed_unsupported` |

</frozen-after-approval>

## Code Map

- `backend/app/platform/model_gateway/adapter.py` -- `ChatAdapter`, `ChatReply`, `as_count`, `bad_envelope`, `UNKNOWN_DIGEST`: reuse. `post_json` is httpx-only: do not use.
- `backend/app/platform/model_gateway/openai_compat.py` -- pattern to mirror (docstring style, envelope handling).
- `backend/app/platform/model_gateway/profiles.py` -- `Provider`, `ModelProfile`, `MODEL_PROFILES`. `resolve_profile` touches `openai` profiles only: leave it.
- `backend/app/platform/model_gateway/gateway.py:111` -- builds clients and `_adapters`; `aclose` closes `_clients`.
- `backend/app/platform/model_gateway/port.py` -- typed errors. `ModelOutputInvalidError` takes `error_code`.
- `backend/app/platform/config.py:169` -- `openai_api_key` is the pattern for the new key.
- `backend/app/agents/manifest.py` -- generated `manifest.json`; CI fails on drift.
- `backend/tests/test_model_gateway.py` -- `_call`, stubs, `test_profiles_are_defined`.
- `backend/pyproject.toml:119` -- import-linter contract keeping chat adapters out of the api process.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- pin `anthropic==2.3.0` (already added); add the adapter to the AD-8 forbidden list -- keeps the contract true.
- [x] `backend/app/platform/model_gateway/profiles.py` -- add `"anthropic"` to `Provider`; add `max_tokens: int = 16000` and `refusal_fallback: bool = False`; widen the `reasoning_effort` doc; add `ANTHROPIC_CHAT` (`anthropic-chat`, `claude-opus-5-5`, `num_ctx=32768`, `reasoning_effort="medium"`, `refusal_fallback=True`) -- the profile carries all model-specific settings.
- [x] `backend/app/platform/model_gateway/anthropic_adapter.py` -- new `AnthropicAdapter` per the Matrix and Design Notes.
- [x] `backend/app/platform/config.py` -- add `anthropic_api_key: SecretStr | None`.
- [x] `backend/app/platform/model_gateway/gateway.py` -- build the SDK client when a key is set, register the adapter, close it in `aclose`; add keyword-only `anthropic_transport: httpx2.AsyncBaseTransport | None = None` for tests.
- [x] `backend/app/platform/model_gateway/__init__.py`, `.env.example`, `compose.yaml`, `compose.nexus.yaml` -- document the provider and pass `PSA_ANTHROPIC_API_KEY` to api and worker, with the same cloud-data warning as the other cloud profiles.
- [x] `backend/app/agents/manifest.json` -- regenerate.
- [x] `backend/tests/test_model_gateway_anthropic.py` -- cover every Matrix row through `ModelGateway` using `httpx2.MockTransport`; assert the request carries `max_tokens`, `output_config`, top-level `system`, and no `temperature`; assert every registered agent output schema passes `transform_schema`.
- [x] `backend/tests/test_model_gateway.py` -- extend `test_profiles_are_defined`.

**Acceptance Criteria:**
- Given `anthropic-chat` is pinned on an Agent's config version or set as `PSA_MODEL_PROFILE_CHAT`, when the Agent runs, then its calls reach Claude with no change to the Agent's code.
- Given an Anthropic call, when it completes, then `platform_model_calls` records profile, model, tokens, outcome and digest `unknown`, as for other providers.
- Given no Anthropic key, when the api and worker start and run other profiles, then they behave as before.

## Implementation Notes

- `PSA_ANTHROPIC_API_KEY` is on the worker only, not api as the task above says: the api never makes a chat call (review finding).
- Beyond the spec: `ChatReply` gained `refused` and `model`, so refused calls keep their tokens and a fallback reply is recorded under the model that served it. Added the `unsupported_schema` code, an `anthropic` logger floor at INFO, an explicit `base_url`, and a pinned `httpx2`.
- A cut-off reply with no text is `truncated`, not `bad_envelope`. `model_context_window_exceeded` also counts as truncated.
- Verification: 162 tests in the two gateway test files passed after the review fixes, with ruff, mypy and compose config clean. The user stopped the final run, so the full suite, `lint-imports` and `manifest --check` were not re-run after those fixes (the last two were clean before them). The live smoke check has not been run: no key.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| `transport=None` drops SDK keepalive | medium | Measured on SDK 2.3.0; patched |
| Ambient `ANTHROPIC_BASE_URL` redirects prompts | low | `_client.py` reads it; compose doesn't pass it, host runs can; patched |
| `model_context_window_exceeded` not truncated | medium | Member of `BetaStopReason`; patched |
| Empty text passes the no-text check | medium | `[""]` is truthy; patched |
| Refusal loses tokens | medium | Raised before usage was read; patched |
| Fallback reply recorded under `profile.model` | medium | Gateway recorded only the profile model; patched |
| API key on the api service | medium | Worker-only for OpenAI; removed from api; patched |
| `httpx2` undeclared | medium | Direct import of a transitive dependency; patched |
| Schema test can't fail for `pattern` | low | Value is a string; patched |
| README and smoke docs omit the provider | low | Manual check relies on them; patched |
| Deterministic failures retried by the job runner | medium | `runner.py` retries non-permanent errors, as for existing providers; deferred |
| `aclose` closure untested | low | Same gap for other clients; deferred |
| `bad_envelope` calls record 0 tokens | low | Rare; fix adds branches; rejected |
| Declined fallback attempt tokens not counted | maybe-false | Needs a live fallback reply to inspect `usage.iterations`; deferred |
| No env override for `max_tokens`; empty-message guard; implicit SDK retries; untested `transport` branch; matrix additions | low/false | Profile edit suffices; callers always send a user turn; approved design; spec-only; rejected |

## Design Notes

**SDK and transport:** SDK 2.3.0 depends on `httpx2`, not the repo's `httpx`, so `httpx.MockTransport` can't reach it; that is why the gateway gets a separate `anthropic_transport`. Both libraries coexist.

**Schemas:** send `anthropic.transform_schema(schema)`. It moves `minimum`/`maxLength` into descriptions and sets `additionalProperties: false`; Pydantic still enforces the originals. All 12 agent output models were audited and pass.

**Request:**
```python
await client.beta.messages.create(
    model=profile.model, max_tokens=profile.max_tokens, system=system, messages=turns,
    output_config={"effort": effort, "format": {"type": "json_schema", "schema": strict}},
    betas=["server-side-fallback-2026-07-01"], fallbacks="default",  # only if refusal_fallback
)
```
Omit `system`, `effort` and the fallback fields when unset. Wrap the call in `asyncio.timeout(timeout_s)` and also pass `timeout=timeout_s`, which bounds the SDK's default retries of 429 and 5xx.

**Why non-streaming:** one request per attempt matches the other adapters, and `max_tokens=16000` stays within non-streaming limits. Claude may need more than the default `PSA_MODEL_TIMEOUT_S=120`; that is an env setting.

## Verification

**Environment:** work only inside `D:/Projects/Office/pre-sales-agent-claude` (a git worktree; never touch the main checkout). Run pytest with `PSA_DATABASE_URL` and `PSA_MIGRATIONS_DATABASE_URL` built from the two values in `.env`, with host and database swapped to `127.0.0.1:5432/psa_test_claude`. Extract only those two values (grep); do not source `.env`. Never run tests against the `psa` database. Hand-format at ~100 columns; do not commit.

**Commands:**
- `cd backend && uv run pytest tests/test_model_gateway.py tests/test_model_gateway_anthropic.py tests/test_registry.py` against `psa_test_claude` -- expected: pass.
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports` -- expected: clean.
- `cd backend && uv run python -m app.agents.manifest --check` -- expected: exit 0.

**Manual checks (if no CLI):**
- With a real `PSA_ANTHROPIC_API_KEY`, run `python -m app.platform.model_gateway.smoke` with `PSA_MODEL_PROFILE_CHAT=anthropic-chat`. Requires the user's key; not possible in this session without one.
