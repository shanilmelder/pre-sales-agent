"""Model profile types. An Agent's config version pins a chat profile by name, so changing an
Agent's model is a registry change, never a code change at the call site: callers name a
profile, not a model.

Every chat profile lives in the database (`registry_model_profiles`, managed under Admin > Model
profiles); none is defined here. `app.modules.registry` stores them, and this package can't
import it: each process that makes chat calls injects a `ProfileResolver` into its
ModelGateway. Migration `0063` seeds `ollama-cloud-chat` (`gpt-oss:120b-cloud`, Ollama's cloud),
`openai-chat` (`gpt-4.1-mini`, OpenAI's cloud API) and `anthropic-chat` (`claude-opus-5-5`).

Each profile names its provider: `ollama` (native `/api/chat`), `openai` (any
`/v1/chat/completions` server at `PSA_OPENAI_BASE_URL`, with `PSA_OPENAI_API_KEY`) or
`anthropic` (Anthropic's API through the official SDK, with `PSA_ANTHROPIC_API_KEY`). Cloud
providers send prompt text off the host: until IT approves that data handling, only sample or
anonymised Opportunities may use them.

Embedding profiles (Story 3.3) are still built in, in `EMBED_PROFILES`, picked by
`PSA_MODEL_PROFILE_EMBED`: `bge-m3` (1024 dims) on host Ollama's `/api/embed`. An embedding
profile's name is what `knowledge_chunks.embedding_model` stores, and each one has its own
partial HNSW index, so changing it is a re-embed, not just a config change.

This module has no imports from the app: `app.platform.config` validates the configured
embedding profile name against `EMBED_PROFILES` at startup.
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
    """The model name the provider serves: an Ollama tag, or an OpenAI or Anthropic model id."""
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
"""Finds a chat profile by name in the registry; None when there is no such profile."""


class UnknownModelProfileError(LookupError):
    """A profile name that is not defined. A programming or config error."""


def get_embed_profile(name: str) -> EmbedProfile:
    try:
        return EMBED_PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(EMBED_PROFILES))
        raise UnknownModelProfileError(
            f"embedding profile {name!r} is not defined ({known})"
        ) from None
