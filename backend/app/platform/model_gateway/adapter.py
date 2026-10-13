"""What every model adapter shares: the `ChatAdapter` Protocol, the `ChatReply` it returns,
and the httpx-transport → typed-error mapping (`post_json`).

An adapter sends one chat request per attempt and parses its provider's envelope; validating
the reply against the output model is the gateway's job. Error messages and codes never
include prompt or response text (or credentials).
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.platform.model_gateway.port import Message, ModelTimeoutError, ModelUnavailableError
from app.platform.model_gateway.profiles import ModelProfile

UNKNOWN_DIGEST = "unknown"


@dataclass(frozen=True, slots=True)
class ChatReply:
    content: str = field(repr=False)
    input_tokens: int
    output_tokens: int
    truncated: bool = False
    """The reply was cut off at the length limit (`done_reason` / `finish_reason` `length`)."""


class ChatAdapter(Protocol):
    async def chat(
        self,
        profile: ModelProfile,
        messages: list[Message],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> ChatReply: ...

    async def digest(self, model: str) -> str:
        """The model's digest, or `unknown`; never raises."""
        ...


def as_count(value: Any) -> int:
    """A token count from a provider envelope; anything that isn't a non-negative int is 0."""
    return value if isinstance(value, int) and value >= 0 else 0


def bad_envelope() -> ModelUnavailableError:
    return ModelUnavailableError(
        "The model server returned a malformed reply.", error_code="bad_envelope"
    )


async def post_json(
    client: httpx.AsyncClient, path: str, body: dict[str, Any], timeout_s: float
) -> httpx.Response:
    """POST `body` to `path`; a 2xx response, or a typed error.

    Connection failures are `ModelUnavailableError` (`connection`, `connect_timeout`,
    `transport`), any non-2xx status (redirects aren't followed) is `http_<status>`, and a
    slow request `ModelTimeoutError`.
    """
    try:
        async with asyncio.timeout(timeout_s):
            response = await client.post(path, json=body, timeout=httpx.Timeout(timeout_s))
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
        raise ModelUnavailableError("The model request failed.", error_code="transport") from None
    if response.status_code >= 300:
        raise ModelUnavailableError(
            f"The model server answered HTTP {response.status_code}.",
            error_code=f"http_{response.status_code}",
        )
    return response
