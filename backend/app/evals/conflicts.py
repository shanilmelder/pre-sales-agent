"""`make eval-conflicts` (Story 6.2): the precision/recall baseline of semantic Conflict
detection, per Conflict type.

Each `evals/conflicts/<name>.yaml` case holds synthetic Findings per specialist agent and the
Conflicts a reviewer expects (type and Finding keys); decoy cases expect none. The runner sends
each case's Findings to `conflict_agent` (prompt 1) on the live ModelGateway, without a
database (no call rows are recorded), validates the reply with the job's own pure validation
(`conflicts.evaluate_semantic`), and matches each predicted Conflict to an unmatched expected
one of the same type that shares at least two Findings. It writes precision and recall per
type (and overall) to `evals/out/conflicts-<timestamp>/report.json`.

A case whose model call fails counts as predicting nothing and is listed under `errors`.
Nothing is stored in the Agent Registry and there is no gate.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.conflicts.application import public as conflicts
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.logging import get_logger
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import ModelGatewayError, ModelGatewayPort

_log = get_logger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
CASES_DIR = BACKEND_DIR.parent / "evals" / "conflicts"
OUT_DIR = BACKEND_DIR.parent / "evals" / "out"
TYPES: tuple[str, ...] = ("architecture", "assumption", "evidence", "scope")
AGENTS: tuple[str, ...] = ("engineering_agent", "pm_agent", "security_agent")
KINDS: tuple[str, ...] = ("risk", "constraint", "dependency", "opportunity")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
NAMESPACE = UUID("3b0c8a52-6f0e-5d2a-9c51-1f6a0e2d7b44")
"""The namespace of the cases' deterministic Finding, Assessment and Requirement ids."""


class CaseError(ValueError):
    """A case file that doesn't fit the format (see `evals/README.md`)."""


@dataclass(frozen=True, slots=True)
class Expected:
    type: str
    findings: frozenset[str]
    """Finding keys."""


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    findings: tuple[conflicts.FindingSnapshot, ...] = field(repr=False)
    keys: Mapping[UUID, str] = field(repr=False)
    """Finding id to its key in the case file."""
    requirement_numbers: Mapping[UUID, int] = field(repr=False)
    expected: tuple[Expected, ...] = ()


@dataclass(frozen=True, slots=True)
class Predicted:
    type: str
    findings: frozenset[str]


def _str(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CaseError(f"{where}: `{key}` must be a non-empty string")
    return value.strip()


def parse_case(name: str, data: Any) -> Case:
    """A case from its parsed YAML. Raises `CaseError` when it doesn't fit."""
    if not isinstance(data, dict):
        raise CaseError(f"{name}: the file must be a mapping")
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, dict) or not raw_findings:
        raise CaseError(f"{name}: `findings` must map agents to lists of Findings")
    snapshots: list[conflicts.FindingSnapshot] = []
    keys: dict[UUID, str] = {}
    agent_of: dict[str, str] = {}
    numbers: dict[UUID, int] = {}
    for agent, items in raw_findings.items():
        if agent not in AGENTS:
            raise CaseError(f"{name}: unknown agent {agent!r}")
        if not isinstance(items, list) or not items:
            raise CaseError(f"{name}: {agent} needs a list of Findings")
        for position, item in enumerate(items, start=1):
            where = f"{name}/{agent}#{position}"
            if not isinstance(item, dict):
                raise CaseError(f"{where}: a Finding must be a mapping")
            key = _str(item, "key", where)
            if key in keys.values():
                raise CaseError(f"{where}: duplicate key {key!r}")
            kind = item.get("kind", "risk")
            severity = item.get("severity", "medium")
            if kind not in KINDS or severity not in SEVERITIES:
                raise CaseError(f"{where}: unknown kind or severity")
            labels = item.get("requirements", [])
            if not isinstance(labels, list) or not all(
                isinstance(r, int) and not isinstance(r, bool) and r >= 1 for r in labels
            ):
                raise CaseError(f"{where}: `requirements` must be Requirement numbers")
            cited: list[tuple[UUID, int]] = []
            for number in labels:
                rid = uuid5(NAMESPACE, f"{name}/R{number}")
                numbers[rid] = number
                cited.append((rid, 1))
            finding_id = uuid5(NAMESPACE, f"{name}/{key}")
            keys[finding_id] = key
            agent_of[key] = agent
            snapshots.append(
                conflicts.FindingSnapshot(
                    finding_id=finding_id,
                    assessment_id=uuid5(NAMESPACE, f"{name}/{agent}"),
                    assessment_version=1,
                    agent=agent,
                    position=position,
                    kind=kind,
                    severity=severity,
                    title=_str(item, "title", where),
                    detail=_str(item, "detail", where),
                    requirements=tuple(cited),
                )
            )
    expected: list[Expected] = []
    raw_expected = data.get("expected", [])
    if not isinstance(raw_expected, list):
        raise CaseError(f"{name}: `expected` must be a list")
    known = set(keys.values())
    for n, item in enumerate(raw_expected, start=1):
        where = f"{name}/expected#{n}"
        if not isinstance(item, dict):
            raise CaseError(f"{where}: must be a mapping")
        type_ = _str(item, "type", where)
        cited_keys = item.get("findings")
        if type_ not in TYPES:
            raise CaseError(f"{where}: unknown type {type_!r}")
        if (
            not isinstance(cited_keys, list)
            or not all(isinstance(k, str) for k in cited_keys)
            or len(set(cited_keys)) < 2
            or not set(cited_keys) <= known
        ):
            raise CaseError(f"{where}: `findings` must name at least two of the case's keys")
        if len({agent_of[k] for k in cited_keys}) < 2:
            raise CaseError(f"{where}: `findings` must cite at least two agents")
        expected.append(Expected(type_, frozenset(cited_keys)))
    return Case(
        name=name,
        findings=tuple(snapshots),
        keys=keys,
        requirement_numbers=numbers,
        expected=tuple(expected),
    )


def load_cases(cases_dir: Path = CASES_DIR, only: Sequence[str] = ()) -> list[Case]:
    """Every case in `cases_dir` (sorted by name), or only the named ones."""
    paths = sorted(cases_dir.glob("*.yaml"))
    names = {p.stem for p in paths}
    unknown = sorted(set(only) - names)
    if unknown:
        raise CaseError(f"no such case: {', '.join(unknown)}")
    cases: list[Case] = []
    for p in paths:
        if only and p.stem not in only:
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            raise CaseError(f"{p.stem}: the file can't be read ({type(exc).__name__})") from None
        cases.append(parse_case(p.stem, data))
    return cases


# --- scoring --------------------------------------------------------------------------------


@dataclass(slots=True)
class Tally:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float | None:
        predicted = self.true_positives + self.false_positives
        return None if predicted == 0 else self.true_positives / predicted

    @property
    def recall(self) -> float | None:
        expected = self.true_positives + self.false_negatives
        return None if expected == 0 else self.true_positives / expected

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
        }


def match(
    predicted: Sequence[Predicted], expected: Sequence[Expected]
) -> tuple[list[tuple[Predicted, Expected]], list[Predicted], list[Expected]]:
    """Pair each prediction, in order, with the first unmatched expected Conflict of the same
    type that shares at least two Findings. Returns the pairs, the unmatched predictions
    (false positives) and the unmatched expected Conflicts (false negatives)."""
    open_expected = list(expected)
    pairs: list[tuple[Predicted, Expected]] = []
    extra: list[Predicted] = []
    for p in predicted:
        hit = next(
            (e for e in open_expected if e.type == p.type and len(e.findings & p.findings) >= 2),
            None,
        )
        if hit is None:
            extra.append(p)
        else:
            open_expected.remove(hit)
            pairs.append((p, hit))
    return pairs, extra, open_expected


def score(results: Sequence[tuple[Sequence[Predicted], Sequence[Expected]]]) -> dict[str, Tally]:
    """Per type (and `overall`) true and false positives and false negatives over the cases'
    (predicted, expected) pairs."""
    tallies = {t: Tally() for t in (*TYPES, "overall")}
    for predicted, expected in results:
        pairs, extra, missed = match(predicted, expected)
        for p, _ in pairs:
            tallies[p.type].true_positives += 1
            tallies["overall"].true_positives += 1
        for p in extra:
            tallies.setdefault(p.type, Tally()).false_positives += 1
            tallies["overall"].false_positives += 1
        for e in missed:
            tallies[e.type].false_negatives += 1
            tallies["overall"].false_negatives += 1
    return tallies


# --- running --------------------------------------------------------------------------------


class _UnrecordedGateway(ModelGateway):
    """The live gateway without its `platform_model_calls` row: the eval needs no database."""

    async def _record(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ConflictsEvalOutcome:
    report: dict[str, Any]
    out_dir: Path


async def _predict(
    gateway: ModelGatewayPort, case: Case, profile: str
) -> tuple[list[Predicted], int, str | None]:
    try:
        validation = await conflicts.evaluate_semantic(
            gateway, case.findings, profile=profile, requirement_numbers=case.requirement_numbers
        )
    except ModelGatewayError as exc:
        _log.warning(
            "evals.conflicts_case_failed",
            extra={"case": case.name, "exc_type": type(exc).__name__},
        )
        return [], 0, type(exc).__name__
    predicted = [
        Predicted(c.type.value, frozenset(case.keys[i] for i in c.finding_ids))
        for c in validation.conflicts
    ]
    return predicted, validation.dropped, None


async def run_conflicts_eval(
    settings: Settings,
    *,
    only: Sequence[str] = (),
    profile: str | None = None,
    gateway: ModelGatewayPort | None = None,
    cases_dir: Path = CASES_DIR,
    out_dir: Path = OUT_DIR,
) -> ConflictsEvalOutcome:
    """Run the cases and write the report (see the module docstring). `gateway` replaces the
    live one (tests)."""
    cases = load_cases(cases_dir, only)
    chosen = profile or settings.model_profile_chat
    engine: AsyncEngine | None = None
    live: ModelGateway | None = None
    if gateway is None:
        engine = create_engine(settings)  # lazy: never connects, nothing is recorded
        live = _UnrecordedGateway(settings, engine)
        gateway = live
    try:
        results: list[tuple[Sequence[Predicted], Sequence[Expected]]] = []
        per_case: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for case in cases:
            predicted, dropped, error = await _predict(gateway, case, chosen)
            if error is not None:
                errors[case.name] = error
            results.append((predicted, case.expected))
            pairs, extra, missed = match(predicted, case.expected)
            per_case.append(
                {
                    "case": case.name,
                    "expected": [_plain(e.type, e.findings) for e in case.expected],
                    "predicted": [_plain(p.type, p.findings) for p in predicted],
                    "matched": len(pairs),
                    "false_positives": len(extra),
                    "false_negatives": len(missed),
                    "dropped": dropped,
                }
            )
    finally:
        if live is not None:
            await live.aclose()
        if engine is not None:
            await engine.dispose()
    tallies = score(results)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report: dict[str, Any] = {
        "kind": "conflicts",
        "created_at": datetime.now(UTC).isoformat(),
        "agent_id": "conflict_agent",
        "prompt_version": 1,
        "profile": chosen,
        "case_count": len(cases),
        "per_type": {t: tallies[t].as_dict() for t in TYPES},
        "overall": tallies["overall"].as_dict(),
        "cases": per_case,
        "errors": errors,
    }
    out = out_dir / f"conflicts-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log.info("evals.conflicts_completed", extra={"case_count": len(cases)})
    return ConflictsEvalOutcome(report=report, out_dir=out)


def _plain(type_: str, findings: frozenset[str]) -> dict[str, Any]:
    return {"type": type_, "findings": sorted(findings)}


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render(report: Mapping[str, Any]) -> str:
    """The report as a short table for the console."""
    lines = [f"Conflict detection eval: {report['case_count']} case(s), {report['profile']}"]
    rows = [*report["per_type"].items(), ("overall", report["overall"])]
    for name, tally in rows:
        lines.append(
            f"  {name:<13} precision {_percent(tally['precision']):>4}  "
            f"recall {_percent(tally['recall']):>4}  "
            f"(tp {tally['true_positives']}, fp {tally['false_positives']}, "
            f"fn {tally['false_negatives']})"
        )
    for name, error in report["errors"].items():
        lines.append(f"  {name}: model call failed ({error})")
    return "\n".join(lines)
