"""`make eval-critic` (Story 6.4) without a model or a database: the committed fixtures, their
validation, the scoring before the backstop, and runs with a fake gateway writing the report
and setting the exit code."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.critic_agent.schema import CriticOutput
from app.evals import critic as ev
from app.evals.__main__ import main
from app.platform.config import Settings
from app.platform.model_gateway.port import ModelTimeoutError, StructuredRequest
from tests.conftest import run_async
from tests.test_intake_extraction import FakeGateway

SETTINGS = Settings(model_profile_chat="demo-chat")


def test_the_committed_fixtures_seed_the_three_defects() -> None:
    cases = ev.load_cases()
    assert len(cases) >= 3
    for case in cases:
        assert case.uncovered, case.name
        assert case.unsupported_claim and case.timeline, case.name
        assert list(case.inputs.uncovered) == [f"R{n}" for n in case.uncovered]
        assert len({f.snapshot.agent for f in case.inputs.findings}) >= 2, case.name


def _case(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "requirements": [
            {"number": 1, "classification": "functional", "text": "Pick fast."},
            {"number": 2, "classification": "commercial", "text": "Go live in May."},
        ],
        "findings": {
            "engineering_agent": [
                {"key": "a", "title": "A", "detail": "A.", "requirements": [1]},
            ],
            "pm_agent": [{"key": "b", "title": "B", "detail": "B.", "requirements": [1]}],
        },
        "seeded": {"uncovered": [2], "unsupported_claim": ["a"], "timeline": ["b"]},
    }
    data.update(overrides)
    return data


def test_a_valid_case_parses() -> None:
    case = ev.parse_case("ok", _case())
    assert case.uncovered == (2,)
    assert case.seeded == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"requirements": []},
        {"findings": {"cto_agent": [{"key": "a", "title": "A", "detail": "A."}]}},
        {"seeded": {"uncovered": [1], "unsupported_claim": ["a"], "timeline": ["b"]}},
        {"seeded": {"uncovered": [], "unsupported_claim": ["a"], "timeline": ["b"]}},
        {"seeded": {"uncovered": [2], "unsupported_claim": ["z"], "timeline": ["b"]}},
        {"seeded": {"uncovered": [2], "unsupported_claim": ["a"]}},
        {"effort": {"engineering_agent": {9: 10}}},
        {"effort": {"security_agent": {1: 10}}},
    ],
)
def test_an_invalid_case_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ev.CaseError):
        ev.parse_case("bad", _case(**overrides))


def test_effort_counts_as_coverage() -> None:
    covered = _case(effort={"pm_agent": {2: 40}})
    with pytest.raises(ev.CaseError, match="none"):
        ev.parse_case("bad", covered)  # R2 is sized now: nothing is uncovered


def test_an_unknown_or_unreadable_case_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ev.CaseError, match="no such case"):
        ev.load_cases(tmp_path, only=("nothing",))
    (tmp_path / "broken.yaml").write_text("requirements: [unclosed\n", encoding="utf-8")
    with pytest.raises(ev.CaseError, match="can't be read"):
        ev.load_cases(tmp_path)
    assert main(["critic", "--only", "no-such-case"]) == 2


def test_scoring_counts_only_matching_categories() -> None:
    case = ev.parse_case("ok", _case())
    score = ev.score_case(
        case,
        [
            ev.Reported("coverage", requirements=frozenset({2})),
            ev.Reported("timeline", findings=frozenset({"a"})),  # not the seeded timeline
            ev.Reported("unsupported_claim", findings=frozenset({"a"})),
        ],
    )
    assert score.uncovered_found == (2,)
    assert (score.unsupported_claim_found, score.timeline_found) == (True, False)
    assert score.found() == 2


def _labels(request: StructuredRequest[Any], *titles: str) -> list[str]:
    """The `F<n>` labels of the Findings with these titles in the prompt."""
    labels = []
    for block in request.messages[1].content.split("<<<FINDING ")[1:]:
        label = block.split(" ", 1)[0]
        if any(f"title: {t}" in block for t in titles):
            labels.append(label)
    return labels


def _uncovered(request: StructuredRequest[Any]) -> list[str]:
    block = request.messages[1].content.split("<<<UNCOVERED requirements ")[1]
    return block.split("\n")[1].split(", ")


def test_a_run_that_reports_every_uncovered_requirement_passes(tmp_path: Path) -> None:
    claims = (
        "Standard SAP connector already proven",
        "Customer validation team signs off within one week",
        "Customer identity provider supports SCIM provisioning",
    )

    def reply(request: StructuredRequest[Any]) -> CriticOutput:
        findings: list[dict[str, Any]] = [
            {
                "category": "coverage",
                "severity": "medium",
                "title": f"Nobody covers {label}",
                "argument": "No Finding or effort row cites it.",
                "requirements": [label],
            }
            for label in _uncovered(request)
        ]
        findings.append(
            {
                "category": "unsupported_claim",
                "severity": "high",
                "title": "A claim with nothing behind it",
                "argument": "No source.",
                "findings": _labels(request, *claims),
            }
        )
        findings.append(  # coverage on a covered Requirement: dropped, not scored
            {
                "category": "coverage",
                "severity": "low",
                "title": "R1 is not covered",
                "argument": "It is.",
                "requirements": ["R1"],
            }
        )
        return CriticOutput.model_validate({"findings": findings})

    fake = FakeGateway()
    fake.replies = [reply]
    outcome = run_async(ev.run_critic_eval(SETTINGS, gateway=fake, out_dir=tmp_path))

    written = json.loads((outcome.out_dir / "report.json").read_text(encoding="utf-8"))
    assert outcome.out_dir.name.startswith("critic-")
    cases = len(ev.load_cases())
    assert written["passed"] is True and outcome.passed
    assert written["per_defect"]["uncovered"] == {"found": cases, "seeded": cases, "share": 1.0}
    assert written["per_defect"]["unsupported_claim"]["share"] == 1.0
    assert written["per_defect"]["timeline"]["found"] == 0
    assert written["overall"]["share"] == pytest.approx(2 / 3)
    assert all(c["dropped"] == 1 for c in written["cases"])
    assert all(r.caller.agent_id == "critic_agent" for r in fake.requests)
    assert "Critic eval PASSED" in ev.render(written)


def test_a_missed_uncovered_requirement_fails_the_run_even_with_the_backstop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGateway()
    fake.replies = [CriticOutput(findings=[])]  # the code backstops; the agent found nothing
    outcome = run_async(
        ev.run_critic_eval(SETTINGS, gateway=fake, out_dir=tmp_path, only=("erp-golive-crunch",))
    )
    assert outcome.report["passed"] is False
    assert outcome.report["overall"]["found"] == 0
    assert "uncovered Requirement not reported (R4)" in ev.render(outcome.report)

    monkeypatch.setattr(
        ev.run_critic_eval,
        "__kwdefaults__",
        {**ev.run_critic_eval.__kwdefaults__, "gateway": fake, "out_dir": tmp_path},
    )
    monkeypatch.setattr("app.evals.__main__.get_settings", lambda: SETTINGS)
    assert main(["critic", "--only", "erp-golive-crunch"]) == 1


def test_a_failed_model_call_finds_nothing(tmp_path: Path) -> None:
    fake = FakeGateway()
    fake.replies = [ModelTimeoutError("slow")]
    outcome = run_async(
        ev.run_critic_eval(SETTINGS, gateway=fake, out_dir=tmp_path, only=("parcel-hub-sso",))
    )
    assert outcome.report["errors"] == {"parcel-hub-sso": "ModelTimeoutError"}
    assert outcome.report["passed"] is False
