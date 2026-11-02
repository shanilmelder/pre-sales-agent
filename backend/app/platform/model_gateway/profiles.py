"""Named model profiles. An Agent's config version pins one, so changing an Agent's model is
a registry change, never a code change at the call site: callers name a profile, not a model.

`ollama-cloud-chat` (`gpt-oss:120b-cloud`) sends prompt text to Ollama's cloud. `openai-chat`
(`gpt-4.1-mini`) is OpenAI's cloud API (`PSA_OPENAI_BASE_URL=https://api.openai.com/v1` plus
`PSA_OPENAI_API_KEY`). Both send prompt text off the host: until IT approves that data
handling, only sample or anonymised Opportunities may use them.

Each profile names its provider: `ollama` (native `/api/chat`, the default) or `openai`
(any `/v1/chat/completions` server at `PSA_OPENAI_BASE_URL`). `anthropic-chat`
(`claude-opus-5-5`) has provider `anthropic`: Anthropic's API through the official SDK, with
`PSA_ANTHROPIC_API_KEY`. It too sends prompt text off the host, so the same data rule applies.

Embedding profiles (Story 3.3) live apart, in `EMBED_PROFILES`, picked by
`PSA_MODEL_PROFILE_EMBED`: `bge-m3` (1024 dims) on host Ollama's `/api/embed`. An embedding
profile's name is what `knowledge_chunks.embedding_model` stores, and each one has its own
partial HNSW index, so changing it is a re-embed, not just a config change.

This module has no imports from the app: `app.platform.config` validates the configured
profile names against `MODEL_PROFILES` and `EMBED_PROFILES` at startup.

`MODEL_PROFILES` holds the built-ins. Platform administrators add custom chat profiles to the
database (`app.modules.registry`), which this package can't import: the worker injects a
`ProfileResolver` into its ModelGateway instead. `PSA_MODEL_PROFILE_CHAT` names a built-in.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

STRUCTURED_TEMPERATURE = 0.1

Provider = Literal["ollama", "openai", "anthropic"]


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    model: str
    """The model name the provider serves: an Ollama tag, or an OpenAI model id."""
    num_ctx: int
    """Context window. `ollama`: set explicitly on every request (Ollama's default is much
    smaller). `openai`: OpenAI-style endpoints can't set it per request, so this declares
    what the server must be configured with (vLLM `--max-model-len`, Ollama
    `OLLAMA_CONTEXT_LENGTH` or a Modelfile); it is not sent. `anthropic`: not sent either; it
    sizes intake's extraction chunks."""
    temperature: float = STRUCTURED_TEMPERATURE
    provider: Provider = "ollama"
    """Which adapter serves the profile: `ollama` (`/api/chat`), `openai`
    (`/chat/completions` at `PSA_OPENAI_BASE_URL`) or `anthropic` (the Anthropic SDK)."""
    reasoning_effort: str | None = None
    """`openai`: set for a reasoning model (OpenAI's o-series, GPT-5), which rejects
    `temperature`. The request then sends `reasoning_effort` (e.g. `low`, `medium`, `high`) and
    no `temperature`. None: a regular model, sent `temperature`. `anthropic`: sent as
    `output_config.effort`; None leaves it to the model's default. `anthropic` requests never
    send `temperature`."""
    max_tokens: int = 16000
    """`anthropic` provider only: the output limit every request must state. Thinking counts
    against it."""
    refusal_fallback: bool = False
    """`anthropic` provider only: let the API rerun a declined request on its default fallback
    model."""

    def options(self) -> dict[str, float | int]:
        """The `options` object of an Ollama `/api/chat` request (Ollama provider only)."""
        return {"temperature": self.temperature, "num_ctx": self.num_ctx}


OLLAMA_CLOUD_CHAT = ModelProfile(
    name="ollama-cloud-chat", model="gpt-oss:120b-cloud", num_ctx=32768
)
# OpenAI's cloud API. A non-reasoning model: the adapter always sends `temperature`, which
# OpenAI's reasoning models reject unless it is 1. `num_ctx` is not sent (the model's own
# window is far larger); it sizes intake's extraction chunks, kept equal to `ollama-cloud-chat`.
OPENAI_CHAT = ModelProfile(
    name="openai-chat", model="gpt-4.1-mini", num_ctx=32768, provider="openai"
)

# Anthropic's API. `num_ctx` is not sent (the model's own window is far larger); it sizes
# intake's extraction chunks, kept equal to `ollama-cloud-chat`.
ANTHROPIC_CHAT = ModelProfile(
    name="anthropic-chat",
    model="claude-opus-5-5",
    num_ctx=32768,
    provider="anthropic",
    reasoning_effort="medium",
    refusal_fallback=True,
)

MODEL_PROFILES: Mapping[str, ModelProfile] = MappingProxyType(
    {profile.name: profile for profile in (OLLAMA_CLOUD_CHAT, OPENAI_CHAT, ANTHROPIC_CHAT)}
)


@dataclass(frozen=True, slots=True)
class EmbedProfile:
    """A named embedding model. `dims` is the length of every vector it returns; the
    gateway rejects a reply of any other length."""

    name: str
    model: str
    """The model name the provider serves (an Ollama tag, or an OpenAI model id)."""
    dims: int
    provider: Provider = "ollama"
    batch_size: int = 16
    """Texts per embedding request."""


BGE_M3 = EmbedProfile(name="bge-m3", model="bge-m3", dims=1024)

EMBED_PROFILES: Mapping[str, EmbedProfile] = MappingProxyType({BGE_M3.name: BGE_M3})


type ProfileResolver = Callable[[str], Awaitable[ModelProfile | None]]
"""Finds a chat profile by name outside `MODEL_PROFILES`; None when there is no such profile."""


class UnknownModelProfileError(LookupError):
    """A profile name that is not defined. A programming or config error."""


def get_profile(name: str) -> ModelProfile:
    try:
        return MODEL_PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(MODEL_PROFILES))
        raise UnknownModelProfileError(f"model profile {name!r} is not defined ({known})") from None


def get_embed_profile(name: str) -> EmbedProfile:
    try:
        return EMBED_PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(EMBED_PROFILES))
        raise UnknownModelProfileError(
            f"embedding profile {name!r} is not defined ({known})"
        ) from None
