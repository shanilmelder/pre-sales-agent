"""The eval harness and reference set (Story 7.6).

- Pure scoring: recall, citation validity, irrelevant and mandatory Gaps, Evidence support and
  pending pairs, stage failures, cost, and the gate (regression delta, first eval).
- The reference set: 10 Opportunities whose quotes are in their Sources, and anonymised.
- The I/O matrix against a migrated Postgres as psa_app: same-database refusal, unknown
  config, timeout (nothing stored), non-admin 403, the insert-only grant, the trace event.
- A harness smoke test on one reference Opportunity with a fake ModelGateway, which needs a
  second, scratch database in `PSA_EVAL_DATABASE_URL` / `PSA_EVAL_MIGRATIONS_DATABASE_URL`
  (skipped without them; the harness resets it).
"""

import ast
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.evals import __main__ as cli
from app.evals import harness
from app.evals.annotations import (
    REFERENCE_DIR,
    Annotations,
    ReferenceSetError,
    anonymisation_problems,
    find_span,
    find_spans,
    load_reference_set,
    reference_set_digest,
)
from app.evals.report import build_report, render, signed
from app.evals.scoring import (
    CriticSummary,
    DetectedGap,
    ExtractedRequirement,
    Finding,
    ModelCallStats,
    OpportunityOutput,
    Span,
    StageFailure,
    aggregate,
    cost,
    match_requirements,
    score_opportunity,
)
from app.modules.registry.application import public as registry
from app.modules.registry.domain import evals as gate
from app.platform.config import Settings, get_settings
from app.platform.db import create_engine
from app.platform.model_gateway.port import StructuredRequest, StructuredResult
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_role_admin import _admin, _signed_in

URL = "/api/v1/registry/evals"
REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "demo-data"
SOURCE = "s1.txt"
TEXT = (
    "We need a goods-to-person picking system for the ambient area. "
    "Orders come from SAP as IDocs. Confirmations go back within 5 minutes."
)


# --- pure scoring ----------------------------------------------------------------------------


def annotations(**overrides: Any) -> Annotations:
    data: dict[str, Any] = {
        "slug": "t",
        "title": "T",
        "customer": "[CUSTOMER]",
        "annotator": "draft",
        "requirements": [
            {"id": "R1", "text": "GTP", "source": SOURCE, "quote": "goods-to-person picking"},
            {"id": "R2", "text": "SAP", "source": SOURCE, "quote": "Orders come from SAP"},
            {"id": "R3", "text": "Conf", "source": SOURCE, "quote": "within 5 minutes"},
        ],
        "gaps": [
            {"id": "G1", "keywords": ["SAP version"], "mandatory": True},
            {"id": "G2", "keywords": ["IDoc", "integration method"]},
        ],
        "irrelevant_gaps": [{"label": "noise", "keywords": ["canteen"]}],
        "integration_risks": [{"id": "I1", "keywords": ["IDoc"]}],
        "evidence": [{"requirement": "R2", "finding_keywords": ["sap"], "supported": True}],
    }
    data.update(overrides)
    return Annotations.model_validate(data)


def span(quote: str) -> Span:
    found = find_span(TEXT, quote)
    assert found is not None
    return Span(SOURCE, *found)


def output(**overrides: Any) -> OpportunityOutput:
    data: dict[str, Any] = {
        "slug": "t",
        "source_texts": {SOURCE: TEXT},
        "requirements": [
            ExtractedRequirement("a", "GTP picking", (span("picking system for the ambient"),)),
            ExtractedRequirement("b", "SAP orders", (span("SAP as IDocs"),)),
        ],
        "valid_citations": 2,
        "dropped_citations": 0,
        "gaps": [
            DetectedGap("g1", "SAP version at go-live", "Changes the interface."),
            DetectedGap("g2", "Canteen opening hours", "Irrelevant."),
        ],
        "findings": [
            Finding("f1", "engineering_agent", "risk", "SAP interface unclear", "IDoc", ("b",)),
            Finding("f2", "pm_agent", "dependency", "Picking hours", "x", ("a",)),
        ],
    }
    data.update(overrides)
    return OpportunityOutput(**data)


def test_find_span_ignores_case_and_whitespace() -> None:
    assert find_span("Hello\n  big   World", "big world") == (8, 19)
    assert find_span("Hello", "absent") is None


def test_extraction_recall_counts_annotated_requirements_whose_quote_a_passage_overlaps() -> None:
    score = score_opportunity(annotations(), output())
    assert (score.extraction_recall.hit, score.extraction_recall.total) == (2, 3)
    assert score.missed_requirements == ["R3"]
    assert score.metrics()["extraction_recall"] == pytest.approx(66.7)


def test_a_passage_in_another_source_does_not_match() -> None:
    elsewhere = ExtractedRequirement("a", "GTP", (Span("other.txt", 0, 200),))
    score = score_opportunity(annotations(), output(requirements=[elsewhere]))
    assert score.extraction_recall.hit == 0


def test_a_quote_matches_at_any_of_its_occurrences() -> None:
    text = "Use SAP here. Later: use SAP here too."
    assert find_spans(text, "use sap here") == [(0, 12), (21, 33)]
    second = ExtractedRequirement("a", "SAP", (Span(SOURCE, 21, 33),))
    matched = match_requirements(
        annotations(
            requirements=[{"id": "R1", "text": "t", "source": SOURCE, "quote": "use SAP here"}]
        ),
        output(source_texts={SOURCE: text}, requirements=[second]),
    )
    assert matched == {"a": {"R1"}}


def test_keywords_match_whole_words_only() -> None:
    timeline = [DetectedGap("g", "Timeline", "The go-live timeline is tight.")]
    labels = annotations(irrelevant_gaps=[{"label": "noise", "keywords": ["line"]}])
    assert score_opportunity(labels, output(gaps=timeline)).metrics()["irrelevant_gaps"] == 0.0
    production = [DetectedGap("g", "Line speed", "The production line is unknown.")]
    assert score_opportunity(labels, output(gaps=production)).metrics()["irrelevant_gaps"] == 100.0


def test_citation_validity_is_valid_over_valid_plus_dropped() -> None:
    assert score_opportunity(annotations(), output()).metrics()["citation_validity"] == 100.0
    score = score_opportunity(annotations(), output(valid_citations=3, dropped_citations=1))
    assert score.metrics()["citation_validity"] == 75.0


def test_gap_recall_irrelevant_and_mandatory() -> None:
    metrics = score_opportunity(annotations(), output()).metrics()
    assert metrics["gap_recall"] == 50.0  # G1 by "SAP version"; G2 missed
    assert metrics["mandatory_gap_recall"] == 100.0
    assert metrics["irrelevant_gaps"] == 50.0  # the canteen Gap, of two


def test_gap_keywords_match_why_it_matters_too() -> None:
    gaps = [DetectedGap("g", "Interfaces", "The integration method is open.")]
    assert score_opportunity(annotations(), output(gaps=gaps)).metrics()["gap_recall"] == 50.0  # G2


def test_unjudged_pairs_are_pending_never_passes() -> None:
    score = score_opportunity(annotations(evidence=[]), output())
    assert len(score.pending) == 2
    assert score.metrics()["evidence_support"] is None
    pair = next(p for p in score.pending if p.agent_id == "engineering_agent")
    assert (pair.requirement_id, pair.annotated_requirements) == ("b", ("R2",))


def test_judged_pairs_score_evidence_support_per_agent() -> None:
    judged = [
        {"requirement": "R2", "finding_keywords": ["sap"], "supported": True},
        {"requirement": "R1", "finding_keywords": ["picking"], "supported": False},
    ]
    score = score_opportunity(annotations(evidence=judged), output())
    assert (score.evidence["engineering_agent"].hit, score.evidence["engineering_agent"].total) == (
        1,
        1,
    )
    assert (score.evidence["pm_agent"].hit, score.evidence["pm_agent"].total) == (0, 1)
    assert score.metrics()["evidence_support"] == 50.0
    assert score.pending == []


def test_integration_risk_recall_uses_risks_and_integration_findings() -> None:
    assert score_opportunity(annotations(), output()).metrics()["integration_risk_recall"] == 100.0
    other = [Finding("f", "engineering_agent", "constraint", "IDoc", "", ())]
    score = score_opportunity(annotations(), output(findings=other))
    assert score.metrics()["integration_risk_recall"] == 0.0


def test_a_failed_extraction_scores_every_later_metric_zero() -> None:
    failed = output(
        requirements=[],
        valid_citations=0,
        gaps=[],
        findings=[],
        failures=[StageFailure("extraction", "model_timeout")],
    )
    metrics = score_opportunity(annotations(), failed).metrics()
    assert metrics["extraction_recall"] == 0.0
    assert metrics["citation_validity"] == 0.0
    assert metrics["gap_recall"] == 0.0
    assert metrics["mandatory_gap_recall"] == 0.0
    assert metrics["irrelevant_gaps"] == 100.0


def test_a_failed_specialists_stage_with_no_findings_scores_evidence_and_risks_zero() -> None:
    failed = output(findings=[], failures=[StageFailure("specialists", "failed")])
    score = score_opportunity(annotations(evidence=[]), failed)
    metrics = score.metrics()
    assert metrics["evidence_support"] == 0.0
    assert metrics["integration_risk_recall"] == 0.0
    for agent in ("engineering_agent", "pm_agent", "security_agent", "red_team_agent"):
        assert (score.evidence[agent].hit, score.evidence[agent].total) == (0, 1)
    assert metrics["gap_recall"] == 50.0  # earlier stages keep their scores


def test_a_failed_red_team_keeps_the_earlier_metrics() -> None:
    judged = [{"requirement": "R2", "finding_keywords": ["sap"], "supported": True}]
    findings = [Finding("f", "red_team_agent", "integration_harder", "SAP", "", ("b",))]
    score = score_opportunity(
        annotations(evidence=judged),
        output(findings=findings, failures=[StageFailure("red_team", "output_invalid")]),
    )
    metrics = score.metrics()
    assert metrics["extraction_recall"] == pytest.approx(66.7)
    assert metrics["evidence_support"] == 0.0


def test_aggregate_micro_averages_and_reports_per_agent() -> None:
    first = score_opportunity(annotations(), output())
    second = score_opportunity(annotations(), output(requirements=[]))
    calls = [ModelCallStats("intake_agent", 4, 1, 1000, 2000, ("sha256:a",))]
    scores = aggregate([first, second], calls)
    assert scores.overall["extraction_recall"] == pytest.approx(33.3)  # 2 of 6
    assert scores.overall["schema_valid_rate"] == 75.0
    assert scores.per_agent["intake_agent"]["schema_valid_rate"] == 75.0
    assert set(scores.per_agent["clarification_agent"]) == {
        "gap_recall",
        "irrelevant_gaps",
        "mandatory_gap_recall",
    }
    assert "evidence_support" in scores.per_agent["red_team_agent"]


def test_cost_is_integer_minor_units_from_gpu_seconds_and_tokens() -> None:
    calls = [
        ModelCallStats("a", 1, 0, 1500, 2500, ()),
        ModelCallStats("b", 1, 0, 500, 500, ()),
    ]
    spent = cost(calls, per_gpu_second_minor=2, per_1k_tokens_minor=3, currency="EUR")
    assert (spent.gpu_seconds, spent.tokens, spent.amount_minor) == (3.0, 2000, 12)


# --- the gate --------------------------------------------------------------------------------

PASSING = {
    "extraction_recall": 95.0,
    "citation_validity": 100.0,
    "gap_recall": 91.0,
    "irrelevant_gaps": 10.0,
    "mandatory_gap_recall": 100.0,
    "evidence_support": None,
}


def _bar(results: list[gate.BarResult], metric: str) -> gate.BarResult:
    return next(r for r in results if r.spec.metric == metric)


def test_first_eval_checks_thresholds_only_with_null_deltas() -> None:
    results, passed = gate.judge(PASSING, None)
    assert passed
    assert all(r.delta is None for r in results)
    assert _bar(results, "evidence_support").status == gate.BarStatus.NOT_MEASURED


def test_a_regression_of_more_than_5_points_fails_even_above_the_threshold() -> None:
    results, passed = gate.judge({**PASSING, "gap_recall": 84.0}, PASSING)
    bar = _bar(results, "gap_recall")
    assert (bar.delta, bar.status, bar.regressed) == (-7.0, gate.BarStatus.FAIL, True)
    assert not passed


def test_a_drop_of_5_points_or_less_passes() -> None:
    results, passed = gate.judge({**PASSING, "gap_recall": 86.0}, PASSING)
    assert _bar(results, "gap_recall").status == gate.BarStatus.PASS
    assert passed


def test_irrelevant_gaps_regress_upwards() -> None:
    results, passed = gate.judge({**PASSING, "irrelevant_gaps": 16.0}, PASSING)
    bar = _bar(results, "irrelevant_gaps")
    assert (bar.delta, bar.status) == (6.0, gate.BarStatus.FAIL)
    assert not passed


def test_a_missed_threshold_or_a_stage_failure_fails() -> None:
    assert not gate.judge({**PASSING, "citation_validity": 99.9}, None)[1]
    assert not gate.judge(PASSING, None, failure_count=1)[1]


def test_signed_deltas_use_a_real_minus_sign() -> None:
    assert (signed(-7.0), signed(1.5), signed(None)) == ("\u22127.0", "+1.5", "\u2014")


def test_the_report_names_a_failed_stage() -> None:
    failed = score_opportunity(
        annotations(), output(failures=[StageFailure("extraction", "model_timeout")])
    )
    scores = aggregate([failed], [])
    bars, passed = registry.judge_eval(
        registry.EvalScores(overall=scores.overall, per_agent=scores.per_agent),
        None,
        failure_count=1,
    )
    meta = {
        "reference_set_version": "0123456789ab",
        "opportunity_count": 1,
        "draft_count": 1,
        "tokens": 0,
        "gpu_seconds": 0.0,
        "cost": {"amount_minor": 0, "currency": "EUR"},
    }
    built = build_report(result=None, bars=bars, passed=passed, scores=scores, meta=meta)
    printed = render(built)
    assert not passed
    assert "Eval FAILED" in printed
    assert "t: extraction failed (model_timeout)" in printed
    assert "Critic: 0/1 Opportunities reviewed, 0 Findings" in printed


def test_the_critic_stage_is_reported_and_its_failure_zeroes_nothing() -> None:
    """Story 6.4: the placeholder became the real stage, with no bar."""
    reviewed = score_opportunity(
        annotations(),
        output(
            failures=[StageFailure("critic", "output_invalid")],
            critic=CriticSummary(version=2, critical=1, medium=2),
        ),
    )
    clean = score_opportunity(annotations(), output())
    assert reviewed.metrics() == clean.metrics()
    scores = aggregate([reviewed, clean], [])
    built = build_report(
        result=None,
        bars=[],
        passed=False,
        scores=scores,
        meta={
            "reference_set_version": "0123456789ab",
            "opportunity_count": 2,
            "draft_count": 0,
            "tokens": 0,
            "gpu_seconds": 0.0,
            "cost": {"amount_minor": 0, "currency": "EUR"},
        },
    )
    assert built["stages"]["not_available"] == []
    assert built["critic"] == {
        "reviewed": 1,
        "opportunities": 2,
        "finding_count": 3,
        "critical": 1,
        "high": 0,
        "medium": 2,
        "low": 0,
    }
    assert built["opportunities"][0]["critic"]["version"] == 2
    printed = render(built)
    assert "Critic: 1/2 Opportunities reviewed, 3 Findings (1 critical, 0 high, 2 medium" in printed
    assert "t: critic failed (output_invalid)" in printed


# --- the reference set -----------------------------------------------------------------------


def test_the_reference_set_has_10_annotated_opportunities_with_their_quotes() -> None:
    reference = load_reference_set()  # raises when a quote is not in its Source
    assert len(reference) >= 10
    assert all(r.annotations.requirements and r.annotations.gaps for r in reference)
    version = registry.reference_set_version(reference_set_digest())
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    every = [r.slug for r in reference]
    assert reference_set_digest(REFERENCE_DIR, every) == reference_set_digest()
    subset = reference_set_digest(REFERENCE_DIR, ["parcel-hub-sortation"])
    assert subset != reference_set_digest()
    assert subset == reference_set_digest(REFERENCE_DIR, ["parcel-hub-sortation"])


def _reference(tmp_path: Path, annotations_yaml: str, source: str = "Some source text.") -> Path:
    folder = tmp_path / "x" / "sources"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text(source, encoding="utf-8")
    (tmp_path / "x" / "annotations.yaml").write_text(annotations_yaml, encoding="utf-8")
    return tmp_path


def test_check_quotes_rejects_bad_references(tmp_path: Path) -> None:
    root = _reference(
        tmp_path,
        "slug: x\ntitle: T\ncustomer: C\nannotator: draft\n"
        "requirements:\n"
        "  - {id: R1, text: t, source: a.txt, quote: not in the source at all}\n"
        "  - {id: R2, text: t, source: missing.txt, quote: Some source text}\n"
        "gaps:\n  - {id: G1, keywords: [a]}\n  - {id: G1, keywords: [b]}\n"
        "evidence:\n  - {requirement: R9, finding_keywords: [x], supported: true}\n",
    )
    with pytest.raises(ReferenceSetError) as raised:
        load_reference_set(root)
    message = str(raised.value)
    assert "R1 quote is not in a.txt" in message
    assert "R2 names unknown source missing.txt" in message
    assert "evidence names unknown requirement R9" in message
    assert "duplicate gap ids" in message
    with pytest.raises(ReferenceSetError, match="unknown reference Opportunities: nope"):
        load_reference_set(root, ["nope"])


def _demo_names() -> set[str]:
    """Names in the original demo scenarios: email display names and local parts, VTT
    speakers, the email domains' stems and the companies and sites they describe."""
    names = {"Meridian", "Riverside", "Harbourline", "Elmbridge"}
    for path in DEMO.rglob("*"):
        if path.suffix not in (".eml", ".vtt", ".txt"):
            continue
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r"^(?:From|To|Cc): (.*)$", text, flags=re.MULTILINE))
        names |= set(re.findall(r"<v ([^>]+)>", text))
        names |= set(re.findall(r"([a-z]+\.[a-z]+)@\w", text))
        names |= {d.split(".")[0] for d in re.findall(r"@([\w.]+)", text)}
    split = set()
    for entry in names:
        for part in re.split(r",\s*", entry):
            split.add(re.sub(r"\s*<.*?>", "", part).strip())
    return {n for n in split if n and n not in {"vendor", "example"} and not n.startswith("[")}


def test_reference_sources_are_anonymised() -> None:
    reference = load_reference_set()
    names = _demo_names()
    assert {"Priya Raman", "Marcus Bell", "meridianfresh"} <= names
    assert anonymisation_problems(reference, names) == []


def test_the_anonymisation_check_catches_real_domains_and_names(tmp_path: Path) -> None:
    root = _reference(
        tmp_path,
        "slug: x\ntitle: T\ncustomer: C\nannotator: draft\nrequirements: []\n",
        "Mail jane@acme.com about Riverside.",
    )
    problems = anonymisation_problems(load_reference_set(root), ["Riverside"])
    assert {kind for _, kind, _ in problems} == {"email", "name", "placeholder"}


def test_the_harness_imports_business_modules_only_through_public_apis() -> None:
    for path in (REPO / "backend" / "app" / "evals").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.modules."):
                        assert alias.name.endswith(".application.public"), alias.name
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app.modules."
            ):
                module = node.module or ""
                if module.endswith(".application"):
                    imported = [a.name for a in node.names]
                    assert imported == ["public"], f"{path.name}: {module} {imported}"
                else:
                    assert module.endswith(".application.public"), f"{path.name}: {module}"


# --- refusals and the I/O matrix -------------------------------------------------------------


def _settings(db_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": db_url,
        "migrations_database_url": os.environ.get("PSA_MIGRATIONS_DATABASE_URL"),
        "eval_database_url": os.environ.get("PSA_EVAL_DATABASE_URL")
        or db_url.rsplit("/", 1)[0] + "/psa_eval_unused",
        "eval_migrations_database_url": os.environ.get("PSA_EVAL_MIGRATIONS_DATABASE_URL")
        or db_url.rsplit("/", 1)[0] + "/psa_eval_unused",
    }
    values.update(overrides)
    return Settings(**values)


def test_the_harness_refuses_the_main_database(tmp_path: Path) -> None:
    main = "postgresql+psycopg://psa_app:x@127.0.0.1:5432/psa"
    same = Settings(
        database_url=main,
        eval_database_url="postgresql+psycopg://psa_app:x@127.0.0.1:5432/psa",
        eval_migrations_database_url="postgresql+psycopg://psa:y@127.0.0.1:5432/psa",
    )
    with pytest.raises(harness.EvalRefusedError, match="must differ"):
        run_async(harness.run_eval(harness.EvalOptions(), settings=same))
    with pytest.raises(harness.EvalRefusedError, match="must both be set"):
        harness.eval_urls(
            Settings(database_url=main, eval_database_url=None, eval_migrations_database_url=None)
        )


def test_the_cli_exits_2_when_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PSA_DATABASE_URL", "postgresql+psycopg://a:b@127.0.0.1:5432/psa")
    monkeypatch.setenv("PSA_EVAL_DATABASE_URL", "postgresql+psycopg://a:b@127.0.0.1:5432/psa")
    monkeypatch.setenv("PSA_EVAL_MIGRATIONS_DATABASE_URL", "postgresql+psycopg://c:d@127.0.0.1/psa")
    get_settings.cache_clear()
    try:
        assert cli.main(["run"]) == cli.EXIT_REFUSED
    finally:
        get_settings.cache_clear()
    assert "must differ" in capsys.readouterr().err
    with pytest.raises(harness.EvalRefusedError):
        harness.parse_configs(["security_agent"])
    with pytest.raises(harness.EvalRefusedError):
        harness.parse_configs(["security_agent=\u00b2"])  # a Unicode digit, not [0-9]
    assert harness.parse_configs(["security_agent=12"]) == {"security_agent": 12}


@pytest.mark.parametrize("eval_host", ["127.0.0.1", "[::1]", "LOCALHOST"])
def test_loopback_spellings_of_the_main_database_are_refused(eval_host: str) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://psa_app:x@localhost:5432/psa",
        migrations_database_url="postgresql+psycopg://psa:y@localhost:5432/psa",
        eval_database_url=f"postgresql+psycopg://psa_app:x@{eval_host}:5432/psa",
        eval_migrations_database_url=f"postgresql+psycopg://psa:y@{eval_host}:5432/psa",
    )
    with pytest.raises(harness.EvalRefusedError, match="must differ"):
        harness.eval_urls(settings)


class _Outcome:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.report = {"passed": passed}
        self.out_dir = Path("out")


@pytest.mark.parametrize(("passed", "code"), [(True, 0), (False, cli.EXIT_FAILED)])
def test_the_cli_exits_0_when_passed_and_1_when_failed(
    monkeypatch: pytest.MonkeyPatch, passed: bool, code: int
) -> None:
    async def fake_run(*_: Any, **__: Any) -> _Outcome:
        return _Outcome(passed)

    monkeypatch.setattr(cli, "run_eval", fake_run)
    monkeypatch.setattr(cli, "render", lambda report: "report")
    assert cli.main(["run"]) == code


@pytest.mark.parametrize(
    "error",
    [ReferenceSetError("unknown reference Opportunities: nope"), RuntimeError("alembic failed")],
)
def test_the_cli_exits_2_without_a_traceback_when_it_cannot_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    async def failing(*_: Any, **__: Any) -> None:
        raise error

    monkeypatch.setattr(cli, "run_eval", failing)
    assert cli.main(["run"]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert str(error) in err and "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_an_unknown_config_version_or_agent_refuses_before_anything_runs(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_reset(*_: Any) -> None:
        raise AssertionError("the eval database must not be reset")

    monkeypatch.setattr(harness, "reset_eval_database", no_reset)
    for configs, message in (
        ({"security_agent": 9}, "no config version 9"),
        ({"nobody_agent": 1}, "Unknown Agent"),
    ):
        options = harness.EvalOptions(configs=configs, only=("parcel-hub-sortation",))
        with pytest.raises(harness.EvalRefusedError, match=message):
            run_async(harness.run_eval(options, settings=_settings(db_url)))


def _result_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(sa.text("SELECT count(*) FROM registry_eval_results")).scalar_one())


def test_a_timeout_stores_nothing(
    db_url: str, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_reset(*_: Any) -> None:
        import time

        time.sleep(1.0)

    monkeypatch.setattr(harness, "reset_eval_database", slow_reset)
    before = _result_count(sync_engine)
    options = harness.EvalOptions(only=("parcel-hub-sortation",), timeout_s=0.2)
    with pytest.raises(harness.EvalTimedOutError, match="Eval timed out — GPU busy"):
        run_async(harness.run_eval(options, settings=_settings(db_url)))
    assert _result_count(sync_engine) == before


def _scores(**overall: float | None) -> registry.EvalScores:
    return registry.EvalScores(overall={**PASSING, **overall}, per_agent={})


def _new(
    scores: registry.EvalScores, failures: int = 0, version: str = "0123456789ab"
) -> registry.NewEvalResult:
    return registry.NewEvalResult(
        reference_set_version=version,
        config_version_ids={"pm_agent": str(uuid4())},
        model_digests={"pm_agent": ["fake"]},
        prompt_versions={"pm_agent": 1},
        scores=scores,
        failures=[
            registry.EvalFailure(slug="x", stage="extraction", code="model_timeout")
            for _ in range(failures)
        ],
        opportunity_count=1,
        draft_count=1,
        pending_count=3,
        tokens=10,
        gpu_seconds=1.5,
        cost=registry.EvalCost(amount_minor=7, currency="EUR"),
    )


def _record(db_url: str, new: registry.NewEvalResult) -> registry.EvalResult:
    async def scenario() -> registry.EvalResult:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await registry.record_eval_result(uow, harness.HARNESS_ACTOR, new)
        finally:
            await engine.dispose()

    return run_async(scenario())


def test_a_regression_is_stored_not_passed_with_its_delta(db_url: str, sync_engine: Engine) -> None:
    version = uuid4().hex[:12]
    accepted = _record(db_url, _new(_scores(), version=version))
    assert (accepted.passed, accepted.accepted) == (True, True)

    regressed = _record(db_url, _new(_scores(gap_recall=84.0), version=version))
    bar = next(b for b in regressed.bars if b.metric == "gap_recall")
    assert (bar.delta, bar.status, bar.regressed) == (-7.0, "fail", True)
    assert (regressed.passed, regressed.accepted) == (False, False)
    evidence = next(b for b in regressed.bars if b.metric == "evidence_support")
    assert evidence.status == "not_measured"

    failed = _record(db_url, _new(_scores(), failures=1, version=version))
    assert (failed.passed, failed.accepted) == (False, False)
    assert failed.failures[0].stage == "extraction"


def test_an_accepted_result_of_another_reference_set_version_is_ignored(db_url: str) -> None:
    _record(db_url, _new(_scores(gap_recall=91.0), version=uuid4().hex[:12]))
    subset = _record(db_url, _new(_scores(gap_recall=84.0), version=uuid4().hex[:12]))
    assert all(b.delta is None and not b.regressed for b in subset.bars)  # a first eval
    assert (subset.passed, subset.accepted) == (True, True)


def test_recording_appends_the_trace_event_with_ids_and_counts_only(
    db_url: str, sync_engine: Engine
) -> None:
    result = _record(db_url, _new(_scores()))
    with sync_engine.connect() as conn:
        events = [
            dict(r)
            for r in conn.execute(
                sa.text("SELECT * FROM platform_trace_events WHERE subject_id = :s"),
                {"s": UUID(result.id)},
            ).mappings()
        ]
    assert len(events) == 1
    event = events[0]
    assert (event["event_type"], event["opportunity_id"]) == ("registry.eval.completed", None)
    assert (event["actor_type"], event["actor_id"], event["subject_type"]) == (
        "system",
        "eval_harness",
        "registry.eval_result",
    )
    assert set(event["payload"]) == {
        "result_id",
        "reference_set_version",
        "config_version_ids",
        "opportunity_count",
        "failed_bar_count",
        "not_measured_bar_count",
        "pending_count",
        "failure_count",
        "passed",
        "accepted",
    }
    assert event["payload"]["not_measured_bar_count"] == 1


def test_psa_app_cannot_update_or_delete_eval_results(db_url: str, sync_engine: Engine) -> None:
    result = _record(db_url, _new(_scores()))
    for statement in (
        "UPDATE registry_eval_results SET accepted = false WHERE id = :i",
        "DELETE FROM registry_eval_results WHERE id = :i",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement), {"i": UUID(result.id)})


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def test_only_admins_read_eval_results(db_url: str, client: TestClient) -> None:
    result = _record(db_url, _new(_scores()))
    engineer, _ = _signed_in(client, "Engineer Person", "presales_engineer")
    for path in (URL, f"{URL}/{result.id}"):
        resp = client.get(path, headers=engineer)
        assert resp.status_code == 403, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert_problem(resp.json(), 403, "forbidden")

    admin, _ = _admin(client)
    listed = client.get(URL, headers=admin)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items[0]["id"] == result.id  # newest first
    one = client.get(f"{URL}/{result.id}", headers=admin)
    assert one.status_code == 200
    assert one.json()["cost"] == {"amount_minor": 7, "currency": "EUR"}
    missing = client.get(f"{URL}/{uuid4()}", headers=admin)
    assert_problem(missing.json(), 404, "not_found")


def test_no_write_routes_for_eval_results(client: TestClient) -> None:
    admin, _ = _admin(client)
    for method in ("post", "put", "patch", "delete"):
        resp = getattr(client, method)(f"{URL}/{uuid4()}", headers=admin)
        assert resp.status_code == 405, (method, resp.status_code)


# --- the harness, end to end on one Opportunity ---------------------------------------------


class ChainGateway:
    """Answers each Agent of the chain by agent id. Records the agents called."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.agents: list[str] = []

    async def complete_structured(self, request: StructuredRequest[Any]) -> StructuredResult[Any]:
        agent = request.caller.agent_id
        self.agents.append(agent)
        reply = self.replies[agent]
        value: BaseModel = reply if isinstance(reply, BaseModel) else reply(request)
        return StructuredResult(
            value=value,
            call_id=uuid4(),
            profile="demo-chat",
            model="fake",
            model_digest="fake",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            attempts=1,
        )


def _chain_replies() -> dict[str, Any]:
    from tests.test_assessments_red_team import finding as red_finding
    from tests.test_assessments_red_team import findings_out
    from tests.test_assessments_specialists import ENGINEERING, NO_CRITIC_FINDINGS, PM, SECURITY
    from tests.test_gaps_detection import gap, gaps_out
    from tests.test_intake_extraction import out

    notes = "S1"
    return {
        "intake_agent": out(
            ("Cross-belt sorter", "functional", [(notes, "a cross-belt sorter for 18,000")]),
            ("Scan and weigh", "functional", [(notes, "scanned, weighed and dimensioned")]),
            ("Host interface", "integration", [(notes, "receive sort plans from the carrier")]),
            ("Video coding", "functional", [(notes, "a video-coding station")]),
            ("Power", "non_functional", [(notes, "one 1,600 kVA transformer")]),
        ),
        "clarification_agent": gaps_out(
            gap("Host interface specification missing", ["R3"]),
            gap("Canteen opening hours", ["R1"]),
        ),
        "engineering_agent": ENGINEERING,
        "pm_agent": PM,
        "security_agent": SECURITY,
        "red_team_agent": findings_out(red_finding("Host socket protocol is undocumented", ["R3"])),
        "critic_agent": NO_CRITIC_FINDINGS,
    }


@pytest.fixture
def eval_settings(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    url = os.environ.get("PSA_EVAL_DATABASE_URL")
    owner = os.environ.get("PSA_EVAL_MIGRATIONS_DATABASE_URL")
    if not url or not owner:
        pytest.skip("PSA_EVAL_DATABASE_URL / PSA_EVAL_MIGRATIONS_DATABASE_URL not set")
    storage = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(storage))
    get_settings.cache_clear()
    yield _settings(db_url, storage_dir=storage, model_profile_chat="demo-chat")
    get_settings.cache_clear()


def _counts(engine: Engine) -> dict[str, int]:
    tables = (
        "opportunities_opportunities",
        "intake_sources",
        "platform_jobs",
        "registry_agent_config_versions",
        "registry_eval_results",
    )
    with engine.connect() as conn:
        return {
            t: int(conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one()) for t in tables
        }


def test_the_harness_runs_one_opportunity_through_the_chain_and_stores_the_result(
    eval_settings: Settings, sync_engine: Engine, tmp_path: Path
) -> None:
    before = _counts(sync_engine)
    fake = ChainGateway(_chain_replies())
    options = harness.EvalOptions(
        only=("parcel-hub-sortation",), out_dir=tmp_path / "out", poll_s=0.2, timeout_s=300
    )

    outcome = run_async(harness.run_eval(options, settings=eval_settings, gateway=fake))

    assert set(fake.agents) >= {
        "intake_agent",
        "clarification_agent",
        "engineering_agent",
        "pm_agent",
        "security_agent",
        "critic_agent",
        "red_team_agent",
    }
    report = outcome.report
    assert report["stored"] and report["opportunity_count"] == 1 and report["draft_count"] == 1
    assert report["stages"]["not_available"] == []
    assert "critic" in report["stages"]["run"]
    # Story 6.4: the Critic reviewed the run; its Review is reported, with no bar.
    assert report["critic"]["reviewed"] == 1
    assert report["opportunities"][0]["critic"]["version"] == 1
    overall = report["scores"]["overall"]
    assert overall["extraction_recall"] == 40.0  # R1-R4 of the 10 annotated
    assert overall["citation_validity"] == 100.0
    assert overall["gap_recall"] == pytest.approx(16.7)  # G1 of 6
    assert overall["mandatory_gap_recall"] == pytest.approx(33.3)  # G1 of G1-G3
    assert overall["irrelevant_gaps"] == 50.0  # the canteen Gap hits a label
    assert overall["evidence_support"] == 100.0  # the Red Team's host Finding is judged
    assert report["pending_count"] > 0
    assert not outcome.passed  # recall bars missed
    assert (outcome.out_dir / "report.json").is_file()
    assert "pending:" in (outcome.out_dir / "review-pending.yaml").read_text(encoding="utf-8")
    assert json.loads((outcome.out_dir / "report.json").read_text(encoding="utf-8"))["result_id"]

    # The main database gained only the result row (and its trace event).
    after = _counts(sync_engine)
    assert after == {**before, "registry_eval_results": before["registry_eval_results"] + 1}
    assert outcome.result is not None and outcome.result.passed is False
    assert set(outcome.result.config_version_ids) >= {"intake_agent", "red_team_agent"}
    assert outcome.result.prompt_versions["intake_agent"] >= 1
    # The fake gateway writes no model calls: no digest is reported, none is made up.
    assert all(v == [] for v in outcome.result.model_digests.values())
    printed = render(report)
    assert "Eval FAILED" in printed and "Critic: 1/1 Opportunities reviewed" in printed
    assert "Gap recall" in printed and "Evidence pairs pending review" in printed


def test_collect_names_failed_and_dead_stages_once_each(eval_settings: Settings) -> None:
    url = eval_settings.eval_database_url
    owner = eval_settings.eval_migrations_database_url
    assert url and owner
    harness.reset_eval_database(url, owner)
    opportunity = uuid4()
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO intake_extractions (id, opportunity_id, status, error_code) "
                    "VALUES (:i, :o, 'failed', 'model_timeout')"
                ),
                {"i": uuid4(), "o": opportunity},
            )
            for job_type in ("intake.extract_requirements", "gaps.detect_gaps", "gaps.detect_gaps"):
                conn.execute(
                    sa.text(
                        "INSERT INTO platform_jobs (id, job_type, payload, priority, status, "
                        "attempts, run_after, opportunity_id) "
                        "VALUES (:i, :t, '{}', 1, 'dead', 3, now(), :o)"
                    ),
                    {"i": uuid4(), "t": job_type, "o": opportunity},
                )
    finally:
        engine.dispose()

    async def scenario() -> OpportunityOutput:
        db = create_engine(eval_settings.model_copy(update={"database_url": url}))
        try:
            return await harness.collect(db, "x", opportunity, BlobStore(eval_settings.storage_dir))
        finally:
            await db.dispose()

    output = run_async(scenario())
    assert list(output.failures) == [
        StageFailure("extraction", "model_timeout"),
        StageFailure("gap_detection", "job_dead"),
    ]
    assert output.requirements == [] and output.findings == []


def test_collect_names_only_the_critic_when_its_task_failed(
    db_url: str, sync_engine: Engine, tmp_path: Path
) -> None:
    """Story 6.4: a failed Critic task (its job dead) is the `critic` stage's failure only:
    the specialists succeeded and the Estimate was built."""
    from app.modules.registry.domain.registry import seed_config_version_id

    opportunity, run = uuid4(), uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO workflows_runs (id, opportunity_id, status) "
                "VALUES (:r, :o, 'partially_failed')"
            ),
            {"r": run, "o": opportunity},
        )
        for agent in ("engineering_agent", "pm_agent", "security_agent", "critic_agent"):
            failed = agent == "critic_agent"
            conn.execute(
                sa.text(
                    "INSERT INTO workflows_tasks (id, run_id, agent, status, error_code, "
                    "config_version_id) VALUES (:i, :r, :a, :s, :e, :c)"
                ),
                {
                    "i": uuid4(),
                    "r": run,
                    "a": agent,
                    "s": "failed" if failed else "succeeded",
                    "e": "output_invalid" if failed else None,
                    "c": seed_config_version_id(agent),
                },
            )
        conn.execute(
            sa.text(
                "INSERT INTO platform_jobs (id, job_type, payload, priority, status, attempts, "
                "run_after, opportunity_id) "
                "VALUES (:i, 'workflows.execute', '{}', 1, 'dead', 2, now(), :o)"
            ),
            {"i": uuid4(), "o": opportunity},
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
                "template_version, uncovered_count, dropped_count, row_version, source, "
                "source_run_id) VALUES (:i, :o, 1, 'draft', 't1', 0, 0, 1, 'assessments', :r)"
            ),
            {"i": uuid4(), "o": opportunity, "r": run},
        )

    async def scenario() -> OpportunityOutput:
        db = create_engine(Settings(database_url=db_url))
        try:
            return await harness.collect(db, "x", opportunity, BlobStore(tmp_path))
        finally:
            await db.dispose()

    output = run_async(scenario())
    assert list(output.failures) == [StageFailure("critic", "output_invalid")]
