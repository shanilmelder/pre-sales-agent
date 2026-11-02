"""The ModelGateway (AD-8): the only path from this codebase to a model.

- `port` — the request, result and typed errors (`complete_structured(request)`).
- `gateway` — `ModelGateway`: semaphore, adapter, retries and the `platform_model_calls` row.
- `adapter` — what adapters share: the `ChatAdapter` Protocol, `ChatReply`, error mapping.
- `ollama` — the Ollama adapter (native `/api/chat` with `format` = the JSON Schema).
- `openai_compat` — the OpenAI-compatible adapter (`/chat/completions` with `response_format`
  = the JSON Schema), for vLLM or any `/v1` server; a profile picks it with provider `openai`.
- `anthropic_adapter` — the Anthropic adapter (the official SDK, with `output_config.format` =
  the JSON Schema); a profile picks it with provider `anthropic`. Chat only, no embeddings.
- `profiles` — named model profiles; each Agent's config version pins one.
- `semaphore` — the per-process, priority-aware slot limit.

This package deliberately re-exports nothing: `app.platform.config` imports `profiles`, so
an eager import of `gateway` here would be circular.
"""
