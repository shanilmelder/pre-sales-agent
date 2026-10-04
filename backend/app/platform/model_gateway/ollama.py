"""The Ollama adapter: one native `POST /api/chat` request per attempt.

Each request sets `stream: false`, `format` to the output model's JSON Schema and `options`
from the profile (`temperature`, `num_ctx`). Token counts come from `prompt_eval_count` and
`eval_count`. The model digest comes from `/api/tags`, cached per adapter (one per process);
a model that isn't listed, or a failed lookup, gives the digest `unknown`, never an error
(`unknown` is cached for 60 s so a hung server doesn't slow every call). A reply with
`done_reason: "length"` is flagged `truncated` (output cut off or context overflow).

Transport problems become `ModelUnavailableError` (connection, error status, malformed
envelope) or `ModelTimeoutError`. Messages and error codes never include prompt or response
text. Validating `message.content` is the gateway's job, not the adapter's.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.platform.logging import get_logger
from app.platform.model_gateway.port import Message, ModelTimeoutError, ModelUnavailableError
from app.platform.model_gateway.profiles import ModelProfile

UNKNOWN_DIGEST = "unknown"
_TAGS_TIMEOUT_S = 5.0
_UNKNOWN_TTL_S = 60.0
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatReply:
    content: str = field(repr=False)
    input_tokens: int
    output_tokens: int
    truncated: bool = False
    """`done_reason` was `length`: the reply was cut off, so it can't be valid."""


def _as_count(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


class OllamaAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        """`client` has `base_url` set to the Ollama server; the caller owns its lifecycle."""
        self._client = client
        self._digests: dict[str, str] = {}
        self._unknown_until: dict[str, float] = {}

    async def chat(
        self,
        profile: ModelProfile,
        messages: list[Message],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> ChatReply:
        body = {
            "model": profile.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "format": schema,
            "options": profile.options(),
        }
        try:
            async with asyncio.timeout(timeout_s):
                response = await self._client.post(
                    "/api/chat", json=body, timeout=httpx.Timeout(timeout_s)
                )
        except TimeoutError:
            raise ModelTimeoutError("The model request timed out.") from None
        except httpx.ConnectTimeout:
            raise ModelUnavailableError(
                "The model server could not be reached.", error_code="connect_timeout"
            ) from None
        except httpx.TimeoutException:
            raise ModelTimeoutError("The model request timed out.") from None
        except httpx.TransportError as exc:
            code = "connection" if isinstance(exc, httpx.ConnectError) else "transport"
            raise ModelUnavailableError(
                "The model server could not be reached.", error_code=code
            ) from None
        except httpx.HTTPError:  # DecodingError, TooManyRedirects, InvalidURL, ...
            raise ModelUnavailableError(
                "The model request failed.", error_code="transport"
            ) from None
        if response.status_code >= 400:
            raise ModelUnavailableError(
                f"The model server answered HTTP {response.status_code}.",
                error_code=f"http_{response.status_code}",
            )
        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError):
            content = None
        if not isinstance(content, str):
            raise ModelUnavailableError(
                "The model server returned a malformed reply.", error_code="bad_envelope"
            )
        return ChatReply(
            content=content,
            input_tokens=_as_count(data.get("prompt_eval_count")),
            output_tokens=_as_count(data.get("eval_count")),
            truncated=data.get("done_reason") == "length",
        )

    async def digest(self, model: str) -> str:
        """The digest `/api/tags` lists for `model`, cached once found; else `unknown`."""
        cached = self._digests.get(model)
        if cached is not None:
            return cached
        if time.monotonic() < self._unknown_until.get(model, 0.0):
            return UNKNOWN_DIGEST
        try:
            response = await self._client.get("/api/tags", timeout=_TAGS_TIMEOUT_S)
            response.raise_for_status()
            entries = response.json().get("models", [])
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            _log.warning(
                "model_gateway.digest_lookup_failed", extra={"exc_type": type(exc).__name__}
            )
            return self._unknown(model)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if model in (entry.get("name"), entry.get("model")):
                digest = entry.get("digest")
                if isinstance(digest, str) and digest:
                    self._digests[model] = digest
                    return digest
        return self._unknown(model)

    def _unknown(self, model: str) -> str:
        self._unknown_until[model] = time.monotonic() + _UNKNOWN_TTL_S
        return UNKNOWN_DIGEST
