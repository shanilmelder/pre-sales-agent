"""The Anthropic adapter: one `client.beta.messages.create` call per attempt, through the
official SDK. A profile picks it with provider `anthropic`.

`system` messages go top-level (Claude has no `system` role in `messages`); every other turn
stays in order. The output model's schema goes in `output_config.format` after
`anthropic.transform_schema`, which moves what structured outputs can't enforce (`minimum`,
`maxLength`, ...) into descriptions and sets `additionalProperties: false`; the gateway still
validates each reply against the output model, so the originals hold. `max_tokens`, the effort
(`reasoning_effort`) and the server-side refusal fallback come from the profile. No sampling
or thinking config is sent: the models this provider serves reject them.

The content is the reply's `text` blocks joined (`thinking` and `fallback` blocks are dropped);
tokens come from `usage` (missing or bad = 0); `model` from the reply, as a fallback model may
have served it. `stop_reason` `max_tokens` or `model_context_window_exceeded` means truncated.
`stop_reason: "refusal"`, which after `fallbacks` means every model declined, returns
`refused` with no content; the gateway turns it into `ModelOutputInvalidError` with code
`refusal`. Blank text in any other reply is `bad_envelope`.
Claude publishes no model digest, so the digest is always `unknown`, without a request.
Embeddings aren't offered here (`embed_unsupported`).

The SDK retries 429 and 5xx itself; `timeout_s` bounds each request and, through
`asyncio.timeout`, the whole attempt including those retries. Statuses that remain are
`http_<status>`, connection failures `connection`, and a slow request `ModelTimeoutError`.
Without a client (no `PSA_ANTHROPIC_API_KEY`) `chat` is `missing_api_key` and sends nothing.
"""

import asyncio
import logging
from typing import Any, cast

import anthropic
from anthropic import AsyncAnthropic, omit, transform_schema
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlock,
)

from app.platform.model_gateway.adapter import (
    UNKNOWN_DIGEST,
    ChatReply,
    EmbedReply,
    as_count,
    bad_envelope,
)
from app.platform.model_gateway.port import (
    Message,
    ModelGatewayError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.platform.model_gateway.profiles import EmbedProfile, ModelProfile

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_SYSTEM_SEPARATOR = "\n\n"
_CUT_OFF_STOP_REASONS = ("max_tokens", "model_context_window_exceeded")

# At DEBUG the SDK logs each request's options, prompts included (AD-20). INFO keeps its retry
# lines, which name only the path and delay. Set here so `PSA_LOG_LEVEL` can't lower it.
logging.getLogger("anthropic").setLevel(logging.INFO)


def _typed_error(exc: Exception) -> ModelGatewayError:
    """The gateway's error for a failed call; never quotes `exc`, whose message can carry the
    response body."""
    if isinstance(exc, TimeoutError | anthropic.APITimeoutError):
        return ModelTimeoutError("The model request timed out.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ModelUnavailableError(
            "The model server could not be reached.", error_code="connection"
        )
    if isinstance(exc, anthropic.APIStatusError):
        return ModelUnavailableError(
            f"The model server answered HTTP {exc.status_code}.",
            error_code=f"http_{exc.status_code}",
        )
    if isinstance(exc, anthropic.APIResponseValidationError):
        return bad_envelope()
    return ModelUnavailableError("The model request failed.", error_code="transport")


def _turn(message: Message) -> BetaMessageParam:
    if message.role == "assistant":
        return {"role": "assistant", "content": message.content}
    return {"role": "user", "content": message.content}


def _reply(message: object) -> ChatReply:
    # The SDK doesn't validate strictly: a body that isn't a Message can arrive as plain text,
    # and a Message can be missing any field.
    if not isinstance(message, BetaMessage):
        raise bad_envelope()
    usage = getattr(message, "usage", None)
    input_tokens = as_count(getattr(usage, "input_tokens", None))
    output_tokens = as_count(getattr(usage, "output_tokens", None))
    served_by = getattr(message, "model", None)
    model = served_by if isinstance(served_by, str) else None
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        return ChatReply("", input_tokens, output_tokens, refused=True, model=model)
    blocks = getattr(message, "content", None)
    if not isinstance(blocks, list):
        raise bad_envelope()
    texts = [
        text
        for block in blocks
        if isinstance(block, BetaTextBlock) and isinstance(text := getattr(block, "text", ""), str)
    ]
    content = "".join(texts)
    truncated = stop_reason in _CUT_OFF_STOP_REASONS
    # Output cut off inside thinking has no text, but it is truncated, not malformed.
    if not content.strip() and not truncated:
        raise bad_envelope()
    return ChatReply(content, input_tokens, output_tokens, truncated=truncated, model=model)


class AnthropicAdapter:
    def __init__(self, client: AsyncAnthropic | None) -> None:
        """`client` is None when no key is configured; the caller owns its lifecycle."""
        self._client = client

    async def chat(
        self,
        profile: ModelProfile,
        messages: list[Message],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> ChatReply:
        if self._client is None:
            raise ModelUnavailableError(
                "PSA_ANTHROPIC_API_KEY is not set.", error_code="missing_api_key"
            )
        try:
            strict = transform_schema(schema)
        except ValueError:
            raise ModelUnavailableError(
                "The output schema cannot be sent to the model.", error_code="unsupported_schema"
            ) from None
        system = _SYSTEM_SEPARATOR.join(m.content for m in messages if m.role == "system")
        turns = [_turn(m) for m in messages if m.role != "system"]
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": strict}}
        if profile.reasoning_effort:
            output_config["effort"] = profile.reasoning_effort
        try:
            async with asyncio.timeout(timeout_s):
                message = await self._client.beta.messages.create(
                    model=profile.model,
                    max_tokens=profile.max_tokens,
                    system=system or omit,
                    messages=turns,
                    output_config=cast(BetaOutputConfigParam, output_config),
                    betas=[_FALLBACK_BETA] if profile.refusal_fallback else omit,
                    fallbacks="default" if profile.refusal_fallback else omit,
                    timeout=timeout_s,
                )
        except (TimeoutError, anthropic.AnthropicError) as exc:
            error = _typed_error(exc)
        else:
            return _reply(message)
        # Outside the handler: raised inside it, `__context__` would keep the SDK error, whose
        # message can quote the response body.
        raise error

    async def embed(self, profile: EmbedProfile, texts: list[str], timeout_s: float) -> EmbedReply:
        """Never: embeddings stay on Ollama (`bge-m3`)."""
        raise ModelUnavailableError(
            "This provider does not serve embeddings.", error_code="embed_unsupported"
        )

    async def digest(self, model: str) -> str:
        """Always `unknown`: Claude publishes no model digest."""
        return UNKNOWN_DIGEST
