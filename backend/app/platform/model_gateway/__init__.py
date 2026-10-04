"""The ModelGateway (AD-8): the only path from this codebase to a model.

- `port` — the request, result and typed errors (`complete_structured(request)`).
- `gateway` — `ModelGateway`: semaphore, adapter, retries and the `platform_model_calls` row.
- `ollama` — the Ollama adapter (native `/api/chat` with `format` = the JSON Schema).
- `profiles` — named model profiles; `PSA_MODEL_PROFILE_CHAT` picks the chat one.
- `semaphore` — the per-process, priority-aware slot limit.

This package deliberately re-exports nothing: `app.platform.config` imports `profiles`, so
an eager import of `gateway` here would be circular.
"""
