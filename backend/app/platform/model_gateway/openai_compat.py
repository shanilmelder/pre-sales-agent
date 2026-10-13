"""The OpenAI-compatible adapter: one `POST {PSA_OPENAI_BASE_URL}/chat/completions` request
per attempt, for vLLM or any server speaking `/v1/chat/completions` (Ollama's `/v1` too).

Each request sets `stream: false`, the profile's `temperature` (or, for a reasoning model,
its `reasoning_effort` and no `temperature`) and `response_format` to a `json_schema`
carrying the output model's JSON Schema. There is no `num_ctx` and no
`options`: OpenAI-style endpoints can't set the context size per request, so for this
provider the profile's `num_ctx` states what the server must be configured with (vLLM
`--max-model-len`, Ollama `OLLAMA_CONTEXT_LENGTH` or a Modelfile).

The content comes from `choices[0].message.content` (anything but a string, including a
`null` content with a `refusal`, is `bad_envelope`); tokens from `usage.prompt_tokens` and
`usage.completion_tokens` (missing or bad = 0); `finish_reason: "length"` means truncated.
`/v1/models` carries no digest, so the digest is always `unknown`, without a request.

Transport problems map to typed errors exactly as for Ollama (`adapter.post_json`). The
bearer key, if any, is set on the client by the gateway; it never reaches logs or errors.
"""

import re
from typing import Any

import httpx

from app.platform.model_gateway.adapter import (
    UNKNOWN_DIGEST,
    ChatReply,
    as_count,
    bad_envelope,
    post_json,
)
from app.platform.model_gateway.port import Message
from app.platform.model_gateway.profiles import ModelProfile

_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_DEFAULT_NAME = "output"


def schema_name(schema: dict[str, Any]) -> str:
    """The `json_schema.name`: the output model's name (the schema `title`), limited to
    `[A-Za-z0-9_-]{1,64}`."""
    title = schema.get("title")
    name = _NAME_UNSAFE.sub("_", title)[:64] if isinstance(title, str) else ""
    return name or _DEFAULT_NAME


class OpenAICompatAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        """`client` has `base_url` set to the `/v1` root (and any auth header); the caller
        owns its lifecycle."""
        self._client = client

    async def chat(
        self,
        profile: ModelProfile,
        messages: list[Message],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> ChatReply:
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name(schema), "schema": schema},
            },
        }
        # Reasoning models reject any `temperature` but the default.
        if profile.reasoning_effort:
            body["reasoning_effort"] = profile.reasoning_effort
        else:
            body["temperature"] = profile.temperature
        response = await post_json(self._client, "chat/completions", body, timeout_s)
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, TypeError, IndexError):
            content = None
        if not isinstance(content, str):
            raise bad_envelope()
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return ChatReply(
            content=content,
            input_tokens=as_count(usage.get("prompt_tokens")),
            output_tokens=as_count(usage.get("completion_tokens")),
            truncated=choice.get("finish_reason") == "length",
        )

    async def digest(self, model: str) -> str:
        """Always `unknown`: OpenAI-style servers publish no model digest."""
        return UNKNOWN_DIGEST
