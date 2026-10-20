"""`make eval-conflicts` (Story 6.2) without a model or a database: the committed cases,
matching and per-type precision/recall, and a run with a fake gateway writing the report."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.conflict_agent.schema import ConflictOutput
from app.evals import conflicts as ev
from app.evals.__main__ import main
from app.platform.config import Settings
from app.platform.model_gateway.port import ModelTimeoutError, StructuredRequest
from tests.conftest import run_async
from tests.test_intake_extraction import FakeGateway


def test_the_committed_cases_cover_every_type_and_two_decoys() -> None:
    cases = ev.load_cases()
    assert len(cases) >= 6
    types = {e.type for c in cases for e in c.expected}
    assert types == set(ev.TYPES)
    assert sum(1 for c in cases if not c.expected) >= 2
    for case in cases:
        assert len({f.agent for f in case.findings}) >= 2, case.name


def test_an_invalid_case_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ev.CaseError):
        ev.parse_case("bad", {"findings": {"cto_agent": [{"key": "x"}]}})
    findings = {
        "engineering_agent": [{"key": "a", "title": "A", "detail": "A."}],
        "pm_agent": [{"key": "b", "title": "B", "detail": "B."}],
    }
    with pytest.raises(ev.CaseError):
        ev.parse_case("bad", {"findings": findings, "expected": [{"type": "x", "findings": []}]})
    with pytest.raises(ev.CaseError):
        ev.parse_case(
            "bad", {"findings": findings, "expected": [{"type": "scope", "findings": ["a", "z"]}]}
        )
    with pytest.raises(ev.CaseError, match="no such case"):
        ev.load_cases(tmp_path, only=("nothing",))
    # Expected keys that aren't strings, or that cite a single agent's Findings.
    with pytest.raises(ev.CaseError):
        ev.parse_case(
            "bad", {"findings": findings, "expected": [{"type": "scope", "findings": [["a"], "b"]}]}
        )
    one_agent = {
        "engineering_agent": [
            {"key": "a", "title": "A", "detail": "A."},
            {"key": "c", "title": "C", "detail": "C."},
        ],
        "pm_agent": [{"key": "b", "title": "B", "detail": "B."}],
    }
    with pytest.raises(ev.CaseError, match="two agents"):
        ev.parse_case(
            "bad", {"findings": one_agent, "expected": [{"type": "scope", "findings": ["a", "c"]}]}
        )
    # A boolean is not a Requirement number.
    with pytest.raises(ev.CaseError, match="Requirement numbers"):
        ev.parse_case(
            "bad",
            {
                "findings": {
                    **findings,
                    "pm_agent": [
                        {"key": "b", "title": "B", "detail": "B.", "requirements": [True]}
                    ],
                }
            },
        )


def test_an_unreadable_case_file_is_refused_with_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.yaml").write_text("findings: [unclosed\n", encoding="utf-8")
    with pytest.raises(ev.CaseError, match="can't be read"):
        ev.load_cases(tmp_path)
    (tmp_path / "broken.yaml").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ev.CaseError, match="can't be read"):
        ev.load_cases(tmp_path)
    monkeypatch.setattr(ev, "CASES_DIR", tmp_path)
    monkeypatch.setattr(
        ev.run_conflicts_eval,
        "__kwdefaults__",
        {**ev.run_conflicts_eval.__kwdefaults__, "cases_dir": tmp_path},
    )
    assert main(["conflicts"]) == 2


def P(type_: str, *keys: str) -> ev.Predicted:
    return ev.Predicted(type_, frozenset(keys))


def E(type_: str, *keys: str) -> ev.Expected:
    return ev.Expected(type_, frozenset(keys))


def test_a_prediction_matches_an_expected_conflict_of_its_type_sharing_two_findings() -> None:
    pairs, extra, missed = ev.match(
        [P("scope", "a", "b", "c"), P("scope", "a", "b"), P("evidence", "a", "b")],
        [E("scope", "a", "b"), E("evidence", "a", "c")],
    )
    assert pairs == [(P("scope", "a", "b", "c"), E("scope", "a", "b"))]
    # The second scope prediction finds the expected one taken; evidence shares one Finding.
    assert extra == [P("scope", "a", "b"), P("evidence", "a", "b")]
    assert missed == [E("evidence", "a", "c")]


def test_precision_and_recall_per_type_and_overall() -> None:
    tallies = ev.score(
        [
            ([P("architecture", "a", "b")], [E("architecture", "a", "b")]),
            ([P("scope", "c", "d")], [E("assumption", "c", "d")]),
            ([], []),  # a decoy left alone
        ]
    )
    assert (tallies["architecture"].precision, tallies["architecture"].recall) == (1.0, 1.0)
    assert (tallies["scope"].precision, tallies["scope"].recall) == (0.0, None)
    assert (tallies["assumption"].precision, tallies["assumption"].recall) == (None, 0.0)
    assert (tallies["evidence"].precision, tallies["evidence"].recall) == (None, None)
    assert (tallies["overall"].precision, tallies["overall"].recall) == (0.5, 0.5)


def _labels(request: StructuredRequest[Any], *titles: str) -> list[str]:
    """The `F<n>` labels of the Findings with these titles in the prompt."""
    labels = []
    for block in request.messages[1].content.split("<<<FINDING ")[1:]:
        label = block.split(" ", 1)[0]
        if any(f"title: {t}" in block for t in titles):
            labels.append(label)
    return labels


def test_a_run_with_a_fake_gateway_writes_the_report(tmp_path: Path) -> None:
    def reply(request: StructuredRequest[Any]) -> ConflictOutput:
        labels = _labels(
            request,
            "Single sign-on against the on-premises Active Directory",
            "Cloud identity provider with MFA is mandatory for all logins",
        )
        if not labels:
            return ConflictOutput(conflicts=[])
        return ConflictOutput.model_validate(
            {
                "conflicts": [
                    {
                        "type": "architecture",
                        "severity": "high",
                        "finding_labels": labels,
                        "summary": "On-prem AD versus a cloud IdP.",
                        "stances": [{"finding_label": x, "stance": "Holds."} for x in labels],
                        "mandatory_constraint": False,
                    }
                ]
            }
        )

    fake = FakeGateway()
    fake.replies = [reply]
    outcome = run_async(
        ev.run_conflicts_eval(
            Settings(model_profile_chat="demo-chat"), gateway=fake, out_dir=tmp_path
        )
    )
    written = json.loads((outcome.out_dir / "report.json").read_text(encoding="utf-8"))
    assert outcome.out_dir.name.startswith("conflicts-")
    assert written["per_type"]["architecture"]["precision"] == 1.0
    assert written["per_type"]["architecture"]["recall"] == 1.0
    assert written["per_type"]["scope"]["recall"] == 0.0
    assert written["overall"]["false_positives"] == 0
    assert written["case_count"] == len(ev.load_cases())
    assert written["errors"] == {}
    assert all(r.caller.agent_id == "conflict_agent" for r in fake.requests)
    assert "Report" not in ev.render(written)  # a plain table
    assert "architecture" in ev.render(written)


def test_a_failed_model_call_counts_as_no_prediction(tmp_path: Path) -> None:
    fake = FakeGateway()
    fake.replies = [ModelTimeoutError("slow")]
    outcome = run_async(
        ev.run_conflicts_eval(
            Settings(model_profile_chat="demo-chat"),
            gateway=fake,
            out_dir=tmp_path,
            only=("decoy-unrelated-topics",),
        )
    )
    assert outcome.report["errors"] == {"decoy-unrelated-topics": "ModelTimeoutError"}
    assert outcome.report["overall"]["false_positives"] == 0


def test_an_unknown_case_is_refused_on_the_command_line() -> None:
    assert main(["conflicts", "--only", "no-such-case"]) == 2
