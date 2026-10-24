"""The eval report (Story 7.6): `evals/out/<ts>/report.json`, `review-pending.yaml` and the
printed summary. The JSON and printed report carry ids, counts and scores; the pending file
also carries the Finding titles and Requirement texts an expert needs to judge each pair
(anonymised reference data; `evals/out/` is not committed)."""

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from app.evals.scoring import OpportunityScore, PendingPair, SetScores
from app.modules.registry.application.public import EvalBar, EvalResult

MINUS = "−"  # noqa: RUF001 - the real minus sign on purpose


def signed(value: float | None) -> str:
    """`+1.5`, `-7.0` with a real minus sign (U+2212), an em dash for none."""
    if value is None:
        return "—"
    if value == 0:
        return "0.0"
    return f"+{value:.1f}" if value > 0 else f"{MINUS}{abs(value):.1f}"


def _value(value: float | None) -> str:
    return "not measured" if value is None else f"{value:.1f}%"


def _bar_line(bar: EvalBar) -> str:
    comparator = "≥" if bar.comparator == "min" else "≤"
    status = {"pass": "PASS", "fail": "FAIL", "not_measured": "NOT MEASURED"}[bar.status]
    regressed = "  (regressed)" if bar.regressed else ""
    return (
        f"  {status:<13} {bar.label:<22} {_value(bar.value):>13}  "
        f"{comparator} {bar.threshold:g}%  delta {signed(bar.delta)}{regressed}"
        f"  [{bar.requirement}]"
    )


def critic_stage(opportunities: Sequence[OpportunityScore]) -> dict[str, Any]:
    """The Critic stage (Story 6.4): how many Opportunities got a Critic Review and its
    Findings per severity, summed. Reported, no bar."""
    reviewed = [o.critic for o in opportunities if o.critic is not None]
    return {
        "reviewed": len(reviewed),
        "opportunities": len(opportunities),
        "finding_count": sum(c.finding_count for c in reviewed),
        "critical": sum(c.critical for c in reviewed),
        "high": sum(c.high for c in reviewed),
        "medium": sum(c.medium for c in reviewed),
        "low": sum(c.low for c in reviewed),
    }


def critic_line(stage: dict[str, Any]) -> str:
    return (
        f"Critic: {stage['reviewed']}/{stage['opportunities']} Opportunities reviewed, "
        f"{stage['finding_count']} Findings ({stage['critical']} critical, {stage['high']} high, "
        f"{stage['medium']} medium, {stage['low']} low) (no bar)"
    )


def build_report(
    *,
    result: EvalResult | None,
    bars: Sequence[EvalBar],
    passed: bool,
    scores: SetScores,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """The JSON report. `result` is the stored row (None when it could not be stored)."""
    return {
        "result_id": None if result is None else result.id,
        "stored": result is not None,
        "passed": passed,
        "accepted": passed,
        **meta,
        "stages": {
            "run": [
                "parse",
                "extraction",
                "gap_detection",
                "specialists",
                "critic",
                "estimate",
                "red_team",
            ],
            "not_available": [],
        },
        "critic": critic_stage(scores.opportunities),
        "bars": [bar.model_dump(mode="json") for bar in bars],
        "scores": {"overall": scores.overall, "per_agent": scores.per_agent},
        "opportunities": [
            {
                "slug": s.slug,
                "metrics": s.metrics(),
                "missed_requirements": s.missed_requirements,
                "missed_gaps": s.missed_gaps,
                "pending_count": len(s.pending),
                "failures": [asdict(f) for f in s.failures],
                "critic": None if s.critic is None else asdict(s.critic),
            }
            for s in scores.opportunities
        ],
        "pending_count": len(scores.pending),
    }


def render(report: dict[str, Any]) -> str:
    """The printed summary."""
    lines = [
        f"Eval {'PASSED' if report['passed'] else 'FAILED'}"
        f"  reference set {report['reference_set_version']}"
        f"  ({report['opportunity_count']} Opportunities, {report['draft_count']} with draft "
        "annotations)",
        f"Stored: {report['result_id'] or 'no'}"
        + ("  (accepted)" if report["stored"] and report["accepted"] else ""),
        "",
        "Bars:",
        *[_bar_line(EvalBar.model_validate(b)) for b in report["bars"]],
        "",
        "Per Agent:",
    ]
    for agent, metrics in report["scores"]["per_agent"].items():
        shown = ", ".join(f"{k} {_value(v)}" for k, v in metrics.items())
        lines.append(f"  {agent:<26} {shown}")
    overall = report["scores"]["overall"]
    lines += [
        "",
        f"Schema-valid rate: {_value(overall.get('schema_valid_rate'))} (no bar)",
        f"Integration-risk recall: {_value(overall.get('integration_risk_recall'))} (no bar)",
        f"Evidence pairs pending review: {report['pending_count']}",
        f"Tokens: {report['tokens']:,}  GPU seconds: {report['gpu_seconds']:.1f}  "
        f"Cost: {report['cost']['amount_minor']} minor units {report['cost']['currency']}",
        critic_line(report["critic"]),
    ]
    failures = [
        f"  {o['slug']}: {f['stage']} failed ({f['code']})"
        for o in report["opportunities"]
        for f in o["failures"]
    ]
    if failures:
        lines += ["", "Stage failures (later metrics scored 0):", *failures]
    return "\n".join(lines)


def pending_yaml(pending: Sequence[PendingPair]) -> str:
    """`review-pending.yaml`: each unjudged pair, ready to copy into `evidence:` once an
    expert has judged it."""
    items = [
        {
            "slug": p.slug,
            "agent_id": p.agent_id,
            "finding_id": p.finding_id,
            "finding_title": p.finding_title,
            "requirement_id": p.requirement_id,
            "requirement_text": p.requirement_text,
            "annotated_requirements": list(p.annotated_requirements),
            "supported": None,
        }
        for p in pending
    ]
    return yaml.safe_dump({"pending": items}, sort_keys=False, allow_unicode=True)


def write(out_dir: Path, report: dict[str, Any], pending: Sequence[PendingPair]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "review-pending.yaml").write_text(pending_yaml(pending), encoding="utf-8")
