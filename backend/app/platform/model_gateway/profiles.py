"""Named model profiles. Changing model is a config change (`PSA_MODEL_PROFILE_CHAT`),
never a code change at the call site: callers name a profile, not a model.

`demo-chat` (`gpt-oss:120b-cloud`) sends prompt text to Ollama's cloud. Until IT approves
that data handling, only sample or anonymised Opportunities may use it. `local-chat`
(`qwen3:8b`) runs fully on the host for when the cloud is unavailable or not allowed.

Each profile names its provider: `ollama` (native `/api/chat`, the default) or `openai`
(any `/v1/chat/completions` server at `PSA_OPENAI_BASE_URL`, e.g. vLLM). `local-chat-openai`
is `qwen3:8b` over the OpenAI-compatible adapter; with the default base URL it is served by
host Ollama's own `/v1` endpoint. `openai-chat` (`gpt-4.1-mini`) is OpenAI's cloud API
(`PSA_OPENAI_BASE_URL=https://api.openai.com/v1` plus `PSA_OPENAI_API_KEY`); like
`demo-chat` it sends prompt text off the host, so the same data rule applies.

Embedding profiles (Story 3.3) live apart, in `EMBED_PROFILES`, picked by
`PSA_MODEL_PROFILE_EMBED`: `bge-m3` (1024 dims) on host Ollama's `/api/embed`. An embedding
profile's name is what `knowledge_chunks.embedding_model` stores, and each one has its own
partial HNSW index, so changing it is a re-embed, not just a config change.

This module has no imports from the app: `app.platform.config` validates the configured
profile names against `MODEL_PROFILES` and `EMBED_PROFILES` at startup.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

STRUCTURED_TEMPERATURE = 0.1

Provider = Literal["ollama", "openai"]


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    model: str
    """The model name the provider serves: an Ollama tag, or an OpenAI model id."""
    num_ctx: int
    """Context window. `ollama`: set explicitly on every request (Ollama's default is much
    smaller). `openai`: OpenAI-style endpoints can't set it per request, so this declares
    what the server must be configured with (vLLM `--max-model-len`, Ollama
    `OLLAMA_CONTEXT_LENGTH` or a Modelfile); it is not sent."""
    temperature: float = STRUCTURED_TEMPERATURE
    provider: Provider = "ollama"
    """Which adapter serves the profile: `ollama` (`/api/chat`) or `openai`
    (`/chat/completions` at `PSA_OPENAI_BASE_URL`)."""
    reasoning_effort: str | None = None
    """`openai` provider only: set for a reasoning model (OpenAI's o-series, GPT-5), which
    rejects `temperature`. The request then sends `reasoning_effort` (e.g. `low`, `medium`,
    `high`) and no `temperature`. None: a regular model, sent `temperature`."""

    def options(self) -> dict[str, float | int]:
        """The `options` object of an Ollama `/api/chat` request (Ollama provider only)."""
        return {"temperature": self.temperature, "num_ctx": self.num_ctx}


DEMO_CHAT = ModelProfile(name="demo-chat", model="gpt-oss:120b-cloud", num_ctx=32768)
LOCAL_CHAT = ModelProfile(name="local-chat", model="qwen3:8b", num_ctx=16384)
# The server must run qwen3:8b with a 16384-token context (e.g. OLLAMA_CONTEXT_LENGTH=16384).
LOCAL_CHAT_OPENAI = ModelProfile(
    name="local-chat-openai", model="qwen3:8b", num_ctx=16384, provider="openai"
)
# OpenAI's cloud API. A non-reasoning model: the adapter always sends `temperature`, which
# OpenAI's reasoning models reject unless it is 1. `num_ctx` is not sent (the model's own
# window is far larger); it sizes intake's extraction chunks, kept equal to `demo-chat`.
OPENAI_CHAT = ModelProfile(
    name="openai-chat", model="gpt-4.1-mini", num_ctx=32768, provider="openai"
)

MODEL_PROFILES: Mapping[str, ModelProfile] = MappingProxyType(
    {profile.name: profile for profile in (DEMO_CHAT, LOCAL_CHAT, LOCAL_CHAT_OPENAI, OPENAI_CHAT)}
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


class UnknownModelProfileError(LookupError):
    """A profile name that is not defined here. A programming or config error."""


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
