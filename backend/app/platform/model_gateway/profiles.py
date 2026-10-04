"""Named model profiles. Changing model is a config change (`PSA_MODEL_PROFILE_CHAT`),
never a code change at the call site: callers name a profile, not a model.

`demo-chat` (`gpt-oss:120b-cloud`) sends prompt text to Ollama's cloud. Until IT approves
that data handling, only sample or anonymised Opportunities may use it. `local-chat`
(`qwen3:8b`) runs fully on the host for when the cloud is unavailable or not allowed.

This module has no imports from the app: `app.platform.config` validates the configured
profile name against `MODEL_PROFILES` at startup.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

STRUCTURED_TEMPERATURE = 0.1


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    model: str
    """The Ollama model tag."""
    num_ctx: int
    """Context window, set explicitly on every request (Ollama's default is much smaller)."""
    temperature: float = STRUCTURED_TEMPERATURE

    def options(self) -> dict[str, float | int]:
        """The `options` object of an Ollama `/api/chat` request."""
        return {"temperature": self.temperature, "num_ctx": self.num_ctx}


DEMO_CHAT = ModelProfile(name="demo-chat", model="gpt-oss:120b-cloud", num_ctx=32768)
LOCAL_CHAT = ModelProfile(name="local-chat", model="qwen3:8b", num_ctx=16384)

MODEL_PROFILES: Mapping[str, ModelProfile] = MappingProxyType(
    {profile.name: profile for profile in (DEMO_CHAT, LOCAL_CHAT)}
)


class UnknownModelProfileError(LookupError):
    """A profile name that is not defined here. A programming or config error."""


def get_profile(name: str) -> ModelProfile:
    try:
        return MODEL_PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(MODEL_PROFILES))
        raise UnknownModelProfileError(f"model profile {name!r} is not defined ({known})") from None
