---
title: 'Story 2.4 remainder: OpenAI-compatible adapter'
type: 'feature'
created: '2026-10-12'
status: 'done'
baseline_commit: '17722ea12f602fefd90bb16d3d5243b9c6a8d43e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-4-model-gateway.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The ModelGateway can only talk to Ollama's native `/api/chat`. The architecture keeps an OpenAI-compatible adapter behind the same port so the project can later serve models from vLLM (or any `/v1/chat/completions` server) without changing callers. That adapter was deferred from Story 2.4.

**Approach:** Add an OpenAI-compatible adapter (`POST {base}/chat/completions` with `response_format` set to the JSON schema). Each model profile names its provider (`ollama` by default, or `openai`). The gateway picks the adapter from the profile, and everything else stays the same: the semaphore, retries, typed errors and call rows. The existing gateway contract tests run against both adapters.

## Boundaries & Constraints

**Always:**
- **Profile picks the provider.** `ModelProfile.provider` is `ollama` (the default, so existing profiles are unchanged) or `openai`. Switching provider is a config change (`PSA_MODEL_PROFILE_CHAT`), never a code change at the call site.
- **New profile `local-chat-openai`.** It uses `qwen3:8b` with provider `openai` and `num_ctx` 16384. With the default base URL it is served by host Ollama's own `/v1` endpoint, so the adapter can be smoke-tested live without vLLM. `demo-chat` remains the default.
- **Settings:**
  - `PSA_OPENAI_BASE_URL`, default `http://127.0.0.1:11434/v1`.
  - `PSA_OPENAI_API_KEY` (`SecretStr`, optional). When set, every request sends `Authorization: Bearer <key>`; when unset, no auth header is sent. The key never appears in logs, reprs or errors.
- **Request:** `model`, `messages`, `stream: false`, `temperature` from the profile, and `response_format: {"type": "json_schema", "json_schema": {"name": <output model name, sanitised to [A-Za-z0-9_-]{1,64}>, "schema": T.model_json_schema()}}`. No `num_ctx` and no `options`: OpenAI-style endpoints can't set context size per request. For this provider, the profile's `num_ctx` declares what the server must be configured with (vLLM `--max-model-len`, Ollama `OLLAMA_CONTEXT_LENGTH` or a Modelfile). The profile comment and README say so.
- **Reply:**
  - Content comes from `choices[0].message.content`.
  - Tokens come from `usage.prompt_tokens` and `usage.completion_tokens`; a missing or bad value counts as 0.
  - `finish_reason: "length"` means truncated, the same as Ollama's `done_reason`.
  - Content that isn't a string (including `null` with a `refusal`) is `ModelUnavailableError` / `bad_envelope`.
- **Digest:** always `unknown`, with no network call (`/v1/models` carries no digest).
- **Errors:** the same transport → typed-error mapping and `error_code`s as the Ollama adapter (`connection`, `connect_timeout`, `transport`, `http_<status>`, timeout). Share that mapping rather than copying it.
- **Privacy:** same rule as before. No prompt text, reply text or API key in logs, rows or exceptions.
- **No migration:** `platform_model_calls` already records `profile`, which implies the provider.

**Never:** the following stay deferred (`[post-demo]` in `deferred-work.md`):
- vLLM or `ollama` compose services and GPU wiring;
- Modelfile builds and digest pinning;
- `/api/embed` or embeddings over either provider;
- the DB-owned Agent Registry;
- run budgets;
- the structured-output spike;
- per-profile base URLs (a single OpenAI base URL is used).

Also out of scope: streaming, tool calling, `strict` json_schema mode, and changing the default profile. The `api` process still never imports the gateway or any adapter.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Contract parity | Every existing adapter-facing gateway test (valid, retry with field paths, exhausted, truncated, down, 5xx, timeout, bad envelope, cancelled, privacy, slot release) | Same result, row and typed error for `ollama` and `openai` profiles | As before |
| Request shape | An `openai` profile call | Body has `response_format` json_schema with the schema, `stream: false`, the profile `temperature`, and no `num_ctx` / `options` | N/A |
| Auth | Key set / unset | `Authorization: Bearer <key>` / no header; key absent from captured logs and errors | N/A |
| Digest | An `openai` profile call | Row and result digest `unknown`; no request besides `/chat/completions` | N/A |
| Refusal | `content: null`, `refusal: "..."` | `ModelUnavailableError` `bad_envelope`; row `error` | Raised |
| Profile | `PSA_MODEL_PROFILE_CHAT=local-chat-openai` | Request goes to `{PSA_OPENAI_BASE_URL}/chat/completions` with `qwen3:8b` | Unknown profile still fails at startup |

</frozen-after-approval>

## Code Map

- `backend/app/platform/model_gateway/ollama.py` -- the template. Move `ChatReply`, `UNKNOWN_DIGEST`, `_as_count` and the httpx-exception → typed-error mapping (the `try/except` around `post`) into a new shared `adapter.py` with a `ChatAdapter` Protocol (`chat(profile, messages, schema, timeout_s) -> ChatReply`, `digest(model) -> str`). `ollama.py` keeps its body, envelope parsing and `/api/tags` digest cache, and its behaviour must not change.
- `backend/app/platform/model_gateway/openai_compat.py` (new) -- `OpenAICompatAdapter(client)`.
- `backend/app/platform/model_gateway/profiles.py` -- add the `provider: Literal["ollama", "openai"] = "ollama"` field (after `temperature`, so positional construction still works) and `LOCAL_CHAT_OPENAI`. `options()` remains Ollama-only.
- `backend/app/platform/model_gateway/gateway.py` -- in `__init__`, create one `httpx.AsyncClient` per provider: Ollama with `base_url=settings.ollama_url`, OpenAI with `base_url=settings.openai_base_url` plus the bearer header when the key is set. Both share the test `transport`. Keep `{provider: adapter}` and choose by `profile.provider` in `_attempt_all` and for `digest`. `aclose` closes both. Nothing else in `complete_structured` changes.
- `backend/app/platform/config.py` -- `openai_base_url`, `openai_api_key: SecretStr | None`.
- `backend/pyproject.toml:86` -- add `app.platform.model_gateway.openai_compat` (and `adapter` if it imports httpx) to the forbidden modules of the api contract.
- `backend/app/platform/model_gateway/__init__.py` -- docstring: list `adapter`, `openai_compat`. It still re-exports nothing.
- `backend/tests/test_model_gateway.py` -- `StubOllama` (lines 88-118) only routes `/api/chat` and `/api/tags`. Generalise it to also answer `/v1/chat/completions` with an OpenAI-shaped reply built from the same script (`str` → content). Add a `provider` parametrization that selects `local-chat` vs `local-chat-openai` through `model_profile_chat`. Ollama-only tests (`/api/tags` digest caching, `format`/`options` body) remain single. `_settings` sets `openai_base_url="http://ollama.test/v1"`.
- `.env.example`, `compose.yaml` (worker env, around lines 102-108), `README.md` (around line 138) -- the two new settings, the `local-chat-openai` profile, and the note that context size is server-side for this provider.
- `_bmad-output/implementation-artifacts/deferred-work.md:37` -- drop "OpenAI-compatible adapter passing the same contract tests;" from the 2.4 remainder entry, since it is now done.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/model_gateway/adapter.py`, `ollama.py` -- extract the shared reply type, error mapping and Protocol; no behaviour change
- [x] `backend/app/platform/model_gateway/openai_compat.py` -- the adapter per Boundaries
- [x] `profiles.py`, `config.py`, `gateway.py`, `__init__.py`, `pyproject.toml` -- provider field, new profile, settings, adapter selection, import contract
- [x] `backend/tests/test_model_gateway.py` -- parametrize the contract tests over both providers; add the OpenAI-only matrix rows (request shape, auth, digest without a network call, refusal, profile routing)
- [x] `.env.example`, `compose.yaml`, `README.md`, `deferred-work.md` -- settings, docs, deferred entry

**Acceptance Criteria:**
- Given CI, when it runs, then `ruff`, `mypy`, `lint-imports`, `alembic check` and `pytest` all pass with no live model, and every contract test runs once per provider.
- Given host Ollama with `qwen3:8b` pulled, when `PSA_MODEL_PROFILE_CHAT=local-chat-openai uv run python -m app.platform.model_gateway.smoke` runs, then it prints `ok` with token counts and `digest=unknown`. If Ollama's `/v1` ignores `response_format`, record that in Implementation Notes: validation and retries still apply.

## Implementation Notes

- `adapter.post_json` holds the shared transport → typed-error mapping (including `http_<status>`); `bad_envelope()` and `as_count` are shared too. `ollama.py` behaviour is unchanged (its tests pass as before).
- `json_schema.name` comes from the schema's `title` (Pydantic sets it to the model name), sanitised to `[A-Za-z0-9_-]`, cut to 64, falling back to `output`.
- The adapter posts to the relative path `chat/completions`, so httpx keeps the `/v1` path of `PSA_OPENAI_BASE_URL`.
- An empty `PSA_OPENAI_API_KEY` (as in `.env.example` and the compose default) is treated as unset: no `Authorization` header.
- Smoke (2026-10-13, host Ollama, `local-chat-openai`, `qwen3:8b` pulled for it): `ok`, attempts 1, 43 in / 144 out tokens, ~28 s (cold load), `digest=unknown`, call row written. Ollama's `/v1` honours `response_format` json_schema: a prompt asking for prose still returned schema-shaped JSON. `completion_tokens` include qwen3's hidden thinking tokens.
- Contract tests take a `provider` fixture (`local-chat` / `local-chat-openai`); the stub renders each scripted reply in the envelope of the endpoint that was called. The bad-envelope test now also covers no `choices`, a list body and non-JSON.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG: no gaps found).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | ECH | `post_json` returns 3xx as success; then reported as `bad_envelope` | low | httpx doesn't follow redirects by default; the guard is `>= 400`; direct one-character fix | patch |
| 2 | ECH | A whitespace-padded API key gives a malformed `Bearer` header | low | `gateway.py` uses `get_secret_value()` without stripping; direct `.strip()` | patch |
| 3 | BH | The README smoke for `local-chat-openai` doesn't say to set `OLLAMA_CONTEXT_LENGTH`, so smoke passes while real prompts are silently truncated | medium | Ollama's `/v1` uses the server context and truncates silently; per the frozen intent `num_ctx` is not sent, so the fix is the doc line | patch |
| 4 | BH | The README smoke command is one long line with stray spaces, unlike the example above | low | Direct reformat | patch |
| 5 | ECH, BH | `content_filter` / `tool_calls` `finish_reason` isn't treated specially, so retries are burned | low | vLLM and Ollama don't content-filter, and tools aren't sent; adds a branch | reject |
| 6 | ECH | A non-ASCII API key breaks gateway construction | low | API keys are ASCII in practice; adds a validator | reject |
| 7 | ECH | A malformed `PSA_OPENAI_BASE_URL` fails the gateway even for Ollama-only profiles | false | Failing loudly at startup on bad config is correct behaviour | reject |
| 8 | ECH | The Ollama client leaks if building the OpenAI client raises | low | Only at startup failure, where the process exits; adds a try block | reject |
| 9 | ECH, BH | `aclose()` leaves the second client open if the first close raises | low | httpx `aclose` rarely raises, and only at shutdown; adds error handling | reject |
| 10 | ECH | The shared test transport is closed twice | false | `transport` is passed only by tests; `MockTransport` close is a no-op, and the tests pass | reject |
| 11 | BH | The call row doesn't identify which server answered `openai` calls | low | Out of scope by intent: no migration, and the digest is `unknown` by decision | reject |
| 12 | BH | `openai_base_url` isn't validated at startup | low | A bad value fails on the first call with a typed error and a row; adds a validator | reject |
| 13 | BH | The bearer key can go over plain HTTP to a non-loopback host | low | The deployment uses an internal network only; adds a validator | reject |
| 14 | BH | List-of-parts `message.content` becomes `bad_envelope` | low | vLLM and Ollama return string content for chat; adds a branch | reject |
| 15 | BH | No `strict` json_schema flag | false | `strict` is out of scope by the frozen intent | reject |
| 16 | BH | An unknown provider raises a raw `KeyError` with no row | false | `Provider` is a `Literal` checked by mypy, and profiles are code-defined; a loud failure on an unreachable state | reject |
| 17 | BH | `deferred-work.md` doesn't record the new limitations (digest, strict, context) | false | They are intent decisions documented in the README and profiles, not deferred defects | reject |
| 18 | BH | The key-redaction test doesn't check the 401 call row | false | The row's columns are fixed ids, counts and codes (`http_401`), with no free text that could carry the key | reject |
| 19 | BH | The diff leaves out the spec and epic context; the pytest logs are untracked | false | The spec is reviewed separately by design; the logs are the user's own files, unrelated to this change | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `PSA_OLLAMA_URL=http://127.0.0.1:11434 PSA_MODEL_PROFILE_CHAT=local-chat-openai uv run python -m app.platform.model_gateway.smoke` -- expected: `ok … digest=unknown`
