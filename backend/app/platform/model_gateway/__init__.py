"""The ModelGateway (AD-8): the only path from this codebase to a model.

- `port` — the request, result and typed errors (`complete_structured(request)`).
- `gateway` — `ModelGateway`: semaphore, adapter, retries and the `platform_model_calls` row.
- `adapter` — what adapters share: the `ChatAdapter` Protocol, `ChatReply`, error mapping.
- `ollama` — the Ollama adapter (native `/api/chat` with `format` = the JSON Schema).
- `openai_compat` — the OpenAI-compatible adapter (`/chat/completions` with `response_format`
  = the JSON Schema), for vLLM or any `/v1` server; a profile picks it with provider `openai`.
- `profiles` — named model profiles; `PSA_MODEL_PROFILE_CHAT` picks the chat one.
- `semaphore` — the per-process, priority-aware slot limit.

This package deliberately re-exports nothing: `app.platform.config` imports `profiles`, so
an eager import of `gateway` here would be circular.
"""
