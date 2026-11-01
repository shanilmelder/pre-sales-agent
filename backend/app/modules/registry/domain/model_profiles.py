"""Custom chat model profile rules: states, field validation and the gateway profile a stored
definition becomes. Pure, no I/O.

A profile moves `untested` -> `verified` or `failed` through its live test; `failed` ->
`untested` to test again; and any state but `retired` -> `retired`. Its definition never
changes. Only `verified` profiles can be newly pinned; every state keeps resolving for the
versions and runs already pinned to it.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.platform.model_gateway.profiles import (
    STRUCTURED_TEMPERATURE,
    ModelProfile,
    Provider,
)

SUBJECT_TYPE = "registry.model_profile"
APPROVED_SUBJECT_TYPE = "registry.approved_model"
NAME_MAX = 64
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MODEL_MAX = 128
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
NUM_CTX_MIN = 16_384
"""Below this, intake's reserves leave no room for Source text (`input_budget_chars`)."""
NUM_CTX_MAX = 2_097_152
TEMPERATURE_MAX = 2.0


class ProfileState(StrEnum):
    UNTESTED = "untested"
    VERIFIED = "verified"
    FAILED = "failed"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class CustomProfile:
    """One stored profile. `error_code`, `latency_ms` and `tested_at` are its latest test
    result; the test's prompt and reply are never kept."""

    id: UUID
    name: str
    provider: Provider
    model: str
    num_ctx: int
    temperature: float | None
    reasoning_effort: str | None
    state: ProfileState
    error_code: str | None
    latency_ms: int | None
    tested_at: datetime | None
    created_by: UUID | None
    created_at: datetime

    @property
    def definition(self) -> ModelProfile:
        """What the ModelGateway calls. A reasoning profile stores no temperature, and the
        adapter doesn't send one."""
        return ModelProfile(
            name=self.name,
            model=self.model,
            num_ctx=self.num_ctx,
            temperature=STRUCTURED_TEMPERATURE if self.temperature is None else self.temperature,
            provider=self.provider,
            reasoning_effort=self.reasoning_effort,
        )


@dataclass(frozen=True, slots=True)
class ApprovedModel:
    """A provider and model a custom profile may name."""

    id: UUID
    provider: Provider
    model: str
    created_by: UUID | None
    created_at: datetime


def profile_name(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("The name is required.")
    if len(trimmed) > NAME_MAX:
        raise ValueError(f"The name must be at most {NAME_MAX} characters.")
    if not NAME_RE.match(trimmed):
        raise ValueError(
            "The name must use lowercase letters, digits, dots, hyphens or underscores, "
            "e.g. `openai-gpt-5`."
        )
    return trimmed


def model_id(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("The model ID is required.")
    if len(trimmed) > MODEL_MAX:
        raise ValueError(f"The model ID must be at most {MODEL_MAX} characters.")
    if not MODEL_RE.match(trimmed):
        raise ValueError("The model ID contains characters a model ID can't have.")
    return trimmed


def sampling(
    provider: Provider, temperature: float | None, reasoning_effort: str | None
) -> tuple[float | None, str | None]:
    """The stored `(temperature, reasoning_effort)`: one or the other, as the adapter sends
    them. A profile that sets neither gets the structured-output temperature."""
    if reasoning_effort is None:
        return (STRUCTURED_TEMPERATURE if temperature is None else temperature), None
    if temperature is not None:
        raise ValueError("Set a temperature or a reasoning effort, not both.")
    if provider != "openai":
        raise ValueError("Reasoning effort needs the `openai` provider.")
    return None, reasoning_effort
