"""The agent contract (Story 2.4): `AgentResult`, `AgentConfig` and the `Agent` Protocol."""

from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.contract import (
    Agent,
    AgentConfig,
    AgentResult,
    EvidenceRef,
    Finding,
    Risk,
    Span,
    Unknown,
)
from app.platform.model_gateway.profiles import UnknownModelProfileError
from tests.conftest import run_async

PASSAGE = UUID("01920000-0000-7000-8000-0000000000aa")


class IntakeExtension(BaseModel):
    requirement_count: int


def _result(**overrides: object) -> AgentResult:
    fields: dict[str, object] = {
        "findings": [
            Finding(
                statement="Needs 400 totes/hour",
                evidence=[
                    EvidenceRef(
                        kind="source_passage", id=PASSAGE, version=2, span=Span(start=3, end=9)
                    )
                ],
            )
        ],
        "unknowns": [Unknown(question="Peak season volume?")],
        "risks": [Risk(statement="Tight timeline", severity="high")],
        "recommendation": "Confirm throughput",
        "confidence": 0.8,
        "confidence_basis": "Explicit figures in two sources",
        "needs_human_review": True,
        "extensions": {"intake_agent": IntakeExtension(requirement_count=3)},
    }
    fields.update(overrides)
    return AgentResult.model_validate(fields)


def test_agent_result_round_trips_with_extensions() -> None:
    result = _result()
    assert result.contract_version == "1"
    dumped = result.model_dump(mode="json")
    assert dumped["extensions"] == {"intake_agent": {"requirement_count": 3}}
    assert dumped["findings"][0]["evidence"][0] == {
        "kind": "source_passage",
        "id": str(PASSAGE),
        "version": 2,
        "span": {"start": 3, "end": 9},
    }
    assert AgentResult.model_validate_json(result.model_dump_json()) == result
    assert repr(result)
    assert set(dumped) >= {
        "findings",
        "evidence",
        "assumptions",
        "unknowns",
        "risks",
        "recommendation",
        "confidence",
        "confidence_basis",
        "needs_human_review",
        "extensions",
    }


def test_extensions_accept_plain_dicts_and_owner_revalidates() -> None:
    from_dict = _result(extensions={"intake_agent": {"requirement_count": 3}})
    assert from_dict == _result()
    assert from_dict.extensions == {"intake_agent": {"requirement_count": 3}}
    assert IntakeExtension.model_validate(from_dict.extensions["intake_agent"]) == (
        IntakeExtension(requirement_count=3)
    )
    via_json = AgentResult.model_validate_json(from_dict.model_dump_json())
    assert via_json.extensions == {"intake_agent": {"requirement_count": 3}}


def test_evidence_ref_version_and_span_are_optional() -> None:
    ref = EvidenceRef(kind="source_passage", id=PASSAGE)
    assert ref.version is None
    assert ref.span is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_version": "2"},
        {"confidence": 1.5},
        {"confidence_basis": ""},
        {"extensions": {"Not An Agent": IntakeExtension(requirement_count=1)}},
        {"surprise": True},
    ],
    ids=["version", "confidence", "basis", "extension_key", "extra_field"],
)
def test_agent_result_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _result(**overrides)


def test_span_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Span(start=5, end=4)


def test_agent_config_actor_id_and_validation() -> None:
    config = AgentConfig(
        agent_id="intake_agent", semver="1.2.0", prompt_version=1, profile="demo-chat"
    )
    assert config.actor_id == "intake_agent@1.2.0"
    with pytest.raises(ValueError, match="snake_case"):
        AgentConfig(agent_id="IntakeAgent", semver="1.0.0", prompt_version=1, profile="demo-chat")
    with pytest.raises(ValueError, match="semver"):
        AgentConfig(agent_id="intake_agent", semver="v1", prompt_version=1, profile="demo-chat")
    with pytest.raises(UnknownModelProfileError):
        AgentConfig(agent_id="intake_agent", semver="1.0.0", prompt_version=1, profile="gpt-9")
    with pytest.raises(ValueError, match="prompt_version"):
        AgentConfig(agent_id="intake_agent", semver="1.0.0", prompt_version=0, profile="demo-chat")


class _EchoAgent:
    def __init__(self) -> None:
        self._config = AgentConfig(
            agent_id="echo_agent", semver="0.1.0", prompt_version=1, profile="local-chat"
        )

    @property
    def config(self) -> AgentConfig:
        return self._config

    async def run(self, task: str) -> AgentResult:
        return AgentResult(
            findings=[Finding(statement=task)],
            confidence=0.5,
            confidence_basis="echo",
            needs_human_review=False,
        )


def test_an_agent_implements_the_protocol() -> None:
    agent: Agent[str] = _EchoAgent()
    result = run_async(agent.run("hello"))
    assert result.findings[0].statement == "hello"
    assert agent.config.actor_id == "echo_agent@0.1.0"
