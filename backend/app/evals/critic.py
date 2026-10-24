"""`make eval-critic` (Story 6.4): the baseline of the Critic, as the share of seeded defects
it finds.

Each `evals/critic/<name>.yaml` case holds synthetic active Requirements, the specialists'
Findings and effort rows of one run, and the defects seeded in them: at least one uncovered
Requirement (no Finding and no effort row cites it), an unsupported claim (Finding keys) and
an inconsistent timeline (Finding keys). The runner builds the Critic's inputs with the
task's own pure code (`assessments.critic_inputs`, which computes the uncovered
Requirements; a case whose computed set differs from the seeded one is refused), sends them
to `critic_agent` (prompt 1) on the live ModelGateway without a database, and scores the
agent's own reply, **before the coverage backstop**:

- an uncovered Requirement is found when a valid `coverage` Finding cites it;
- the unsupported claim when a valid `unsupported_claim` Finding cites one of its Findings;
- the timeline when a valid `timeline` Finding cites one of its Findings.

It writes the share of seeded defects found (per kind and overall) and each case's detail to
`evals/out/critic-<timestamp>/report.json`. It passes only when the uncovered Requirements
are reported in **every** case (`make` exits 1 otherwise). A case whose model call fails
counts as finding nothing and is listed under `errors`. Nothing is stored.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.assessments.application import public as assessments
from app.modules.conflicts.application import public as conflicts
from app.modules.intake.application import public as intake
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.logging import get_logger
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import ModelGatewayError, ModelGatewayPort

_log = get_logger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
CASES_DIR = BACKEND_DIR.parent / "evals" / "critic"
OUT_DIR = BACKEND_DIR.parent / "evals" / "out"
AGENTS: tuple[str, ...] = ("engineering_agent", "pm_agent", "security_agent")
KINDS: tuple[str, ...] = ("risk", "constraint", "dependency", "opportunity")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
DEFECTS: tuple[str, ...] = ("uncovered", "unsupported_claim", "timeline")
NAMESPACE = UUID("8d2f4c61-0b7a-5e93-a1c4-6f0e2b9d3a57")
"""The namespace of the cases' deterministic Requirement, Assessment and Finding ids."""


class CaseError(ValueError):
    """A case file that doesn't fit the format (see `evals/README.md`)."""


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    inputs: assessments.CriticInputs = field(repr=False)
    keys: Mapping[UUID, str] = field(repr=False)
    """Finding id to its key in the case file."""
    uncovered: tuple[int, ...] = ()
    """The seeded uncovered Requirement numbers."""
    unsupported_claim: frozenset[str] = frozenset()
    timeline: frozenset[str] = frozenset()

    @property
    def seeded(self) -> int:
        return len(self.uncovered) + 2


def _str(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CaseError(f"{where}: `{key}` must be a non-empty string")
    return value.strip()


def _numbers(value: Any, where: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in value
    ):
        raise CaseError(f"{where}: must be a list of Requirement numbers")
    return list(value)


def _requirement_id(name: str, number: int) -> UUID:
    return uuid5(NAMESPACE, f"{name}/R{number}")


def _requirements(name: str, data: Mapping[str, Any]) -> list[intake.RequirementSnapshot]:
    raw = data.get("requirements")
    if not isinstance(raw, list) or not raw:
        raise CaseError(f"{name}: `requirements` must be a non-empty list")
    found: list[intake.RequirementSnapshot] = []
    for n, item in enumerate(raw, start=1):
        where = f"{name}/requirements#{n}"
        if not isinstance(item, dict):
            raise CaseError(f"{where}: must be a mapping")
        (number,) = _numbers([item.get("number")], f"{where}: `number`")
        if any(r.number == number for r in found):
            raise CaseError(f"{where}: duplicate number {number}")
        found.append(
            intake.RequirementSnapshot(
                id=_requirement_id(name, number),
                version=1,
                number=number,
                classification=_str(item, "classification", where),
                text=_str(item, "text", where),
            )
        )
    return found


def _effort(
    name: str, agent: str, raw: Any, known: set[int]
) -> tuple[conflicts.EffortSnapshot, ...]:
    where = f"{name}/effort/{agent}"
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise CaseError(f"{where}: must map Requirement numbers to hours")
    rows: list[conflicts.EffortSnapshot] = []
    for number, hours in raw.items():
        if not isinstance(number, int) or number not in known:
            raise CaseError(f"{where}: unknown Requirement {number!r}")
        try:
            value = Decimal(str(hours))
        except InvalidOperation:
            raise CaseError(f"{where}: hours must be a number") from None
        rows.append(
            conflicts.EffortSnapshot(
                requirement_id=_requirement_id(name, number), requirement_version=1, hours=value
            )
        )
    return tuple(rows)


def parse_case(name: str, data: Any) -> Case:
    """A case from its parsed YAML. Raises `CaseError` when it doesn't fit."""
    if not isinstance(data, dict):
        raise CaseError(f"{name}: the file must be a mapping")
    requirements = _requirements(name, data)
    known = {r.number for r in requirements}
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, dict) or not raw_findings:
        raise CaseError(f"{name}: `findings` must map agents to lists of Findings")
    raw_effort = data.get("effort") or {}
    if not isinstance(raw_effort, dict) or not set(raw_effort) <= set(raw_findings):
        raise CaseError(f"{name}: `effort` must map the agents with Findings to hours")
    keys: dict[UUID, str] = {}
    reads: list[assessments.RunAssessment] = []
    for agent, items in raw_findings.items():
        if agent not in AGENTS:
            raise CaseError(f"{name}: unknown agent {agent!r}")
        if not isinstance(items, list) or not items:
            raise CaseError(f"{name}: {agent} needs a list of Findings")
        assessment_id = uuid5(NAMESPACE, f"{name}/{agent}")
        snapshots: list[conflicts.FindingSnapshot] = []
        for position, item in enumerate(items, start=1):
            where = f"{name}/{agent}#{position}"
            if not isinstance(item, dict):
                raise CaseError(f"{where}: a Finding must be a mapping")
            key = _str(item, "key", where)
            if key in keys.values():
                raise CaseError(f"{where}: duplicate key {key!r}")
            kind, severity = item.get("kind", "risk"), item.get("severity", "medium")
            if kind not in KINDS or severity not in SEVERITIES:
                raise CaseError(f"{where}: unknown kind or severity")
            cited = _numbers(item.get("requirements", []), f"{where}: `requirements`")
            if not set(cited) <= known:
                raise CaseError(f"{where}: cites an unknown Requirement")
            finding_id = uuid5(NAMESPACE, f"{name}/{key}")
            keys[finding_id] = key
            snapshots.append(
                conflicts.FindingSnapshot(
                    finding_id=finding_id,
                    assessment_id=assessment_id,
                    assessment_version=1,
                    agent=agent,
                    position=position,
                    kind=kind,
                    severity=severity,
                    title=_str(item, "title", where),
                    detail=_str(item, "detail", where),
                    requirements=tuple((_requirement_id(name, n), 1) for n in cited),
                )
            )
        reads.append(
            assessments.RunAssessment(
                assessment=conflicts.AssessmentSnapshot(
                    assessment_id=assessment_id,
                    agent=agent,
                    version=1,
                    recommendation="proceed_with_conditions",
                    effort=_effort(name, agent, raw_effort.get(agent), known),
                ),
                findings=tuple(snapshots),
            )
        )
    inputs = assessments.critic_inputs(requirements, reads)
    seeded = data.get("seeded")
    if not isinstance(seeded, dict):
        raise CaseError(f"{name}: `seeded` must list the defects")
    uncovered = _numbers(seeded.get("uncovered"), f"{name}/seeded: `uncovered`")
    if not uncovered or [f"R{n}" for n in uncovered] != list(inputs.uncovered):
        raise CaseError(
            f"{name}/seeded: `uncovered` must be exactly the Requirements no Finding or effort "
            f"row cites ({', '.join(inputs.uncovered) or 'none'})"
        )
    defects: dict[str, frozenset[str]] = {}
    for kind in ("unsupported_claim", "timeline"):
        cited_keys = seeded.get(kind)
        if (
            not isinstance(cited_keys, list)
            or not cited_keys
            or not set(cited_keys) <= set(keys.values())
        ):
            raise CaseError(f"{name}/seeded: `{kind}` must name the case's Finding keys")
        defects[kind] = frozenset(cited_keys)
    return Case(
        name=name,
        inputs=inputs,
        keys=keys,
        uncovered=tuple(uncovered),
        unsupported_claim=defects["unsupported_claim"],
        timeline=defects["timeline"],
    )


def load_cases(cases_dir: Path = CASES_DIR, only: Sequence[str] = ()) -> list[Case]:
    """Every case in `cases_dir` (sorted by name), or only the named ones."""
    paths = sorted(cases_dir.glob("*.yaml"))
    unknown = sorted(set(only) - {p.stem for p in paths})
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


@dataclass(frozen=True, slots=True)
class Reported:
    """One valid Finding the agent itself reported (no backstop): its category, the cited
    Finding keys and Requirement numbers."""

    category: str
    findings: frozenset[str] = frozenset()
    requirements: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class CaseScore:
    uncovered_found: tuple[int, ...]
    unsupported_claim_found: bool
    timeline_found: bool

    def found(self) -> int:
        return len(self.uncovered_found) + self.unsupported_claim_found + self.timeline_found


def score_case(case: Case, reported: Sequence[Reported]) -> CaseScore:
    """Which seeded defects the reported Findings find (see the module docstring)."""

    def cites(category: str, keys: frozenset[str]) -> bool:
        return any(r.category == category and r.findings & keys for r in reported)

    covered = {n for r in reported if r.category == "coverage" for n in r.requirements}
    return CaseScore(
        uncovered_found=tuple(n for n in case.uncovered if n in covered),
        unsupported_claim_found=cites("unsupported_claim", case.unsupported_claim),
        timeline_found=cites("timeline", case.timeline),
    )


def _share(found: int, seeded: int) -> float | None:
    return None if seeded == 0 else found / seeded


# --- running --------------------------------------------------------------------------------


class _UnrecordedGateway(ModelGateway):
    """The live gateway without its `platform_model_calls` row: the eval needs no database."""

    async def _record(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True, slots=True)
class CriticEvalOutcome:
    report: dict[str, Any]
    out_dir: Path

    @property
    def passed(self) -> bool:
        return bool(self.report["passed"])


async def _reported(
    gateway: ModelGatewayPort, case: Case, profile: str
) -> tuple[list[Reported], int, str | None]:
    try:
        validation = await assessments.evaluate_critic(gateway, case.inputs, profile=profile)
    except ModelGatewayError as exc:
        _log.warning(
            "evals.critic_case_failed", extra={"case": case.name, "exc_type": type(exc).__name__}
        )
        return [], 0, type(exc).__name__
    numbers = {r.requirement_id: int(r.label[1:]) for r in case.inputs.requirements}
    reported = [
        Reported(
            category=f.category.value,
            findings=frozenset(case.keys[s.finding_id] for s in f.findings),
            requirements=frozenset(numbers[rid] for rid, _ in f.requirements),
        )
        for f in validation.findings
        if not f.backstop
    ]
    return reported, validation.dropped, None


async def run_critic_eval(
    settings: Settings,
    *,
    only: Sequence[str] = (),
    profile: str | None = None,
    gateway: ModelGatewayPort | None = None,
    cases_dir: Path = CASES_DIR,
    out_dir: Path = OUT_DIR,
) -> CriticEvalOutcome:
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
    per_case: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    totals = dict.fromkeys(DEFECTS, 0)
    seeded = {"uncovered": 0, "unsupported_claim": 0, "timeline": 0}
    try:
        for case in cases:
            reported, dropped, error = await _reported(gateway, case, chosen)
            if error is not None:
                errors[case.name] = error
            score = score_case(case, reported)
            totals["uncovered"] += len(score.uncovered_found)
            totals["unsupported_claim"] += score.unsupported_claim_found
            totals["timeline"] += score.timeline_found
            seeded["uncovered"] += len(case.uncovered)
            seeded["unsupported_claim"] += 1
            seeded["timeline"] += 1
            per_case.append(
                {
                    "case": case.name,
                    "uncovered": [f"R{n}" for n in case.uncovered],
                    "uncovered_found": [f"R{n}" for n in score.uncovered_found],
                    "unsupported_claim_found": score.unsupported_claim_found,
                    "timeline_found": score.timeline_found,
                    "found": score.found(),
                    "seeded": case.seeded,
                    "reported": [
                        {
                            "category": r.category,
                            "findings": sorted(r.findings),
                            "requirements": [f"R{n}" for n in sorted(r.requirements)],
                        }
                        for r in reported
                    ],
                    "dropped": dropped,
                }
            )
    finally:
        if live is not None:
            await live.aclose()
        if engine is not None:
            await engine.dispose()
    found_total = sum(totals.values())
    seeded_total = sum(seeded.values())
    every_uncovered = all(c["uncovered_found"] == c["uncovered"] for c in per_case)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report: dict[str, Any] = {
        "kind": "critic",
        "created_at": datetime.now(UTC).isoformat(),
        "agent_id": "critic_agent",
        "prompt_version": 1,
        "profile": chosen,
        "case_count": len(cases),
        "passed": bool(cases) and every_uncovered,
        "per_defect": {
            kind: {
                "found": totals[kind],
                "seeded": seeded[kind],
                "share": _share(totals[kind], seeded[kind]),
            }
            for kind in DEFECTS
        },
        "overall": {
            "found": found_total,
            "seeded": seeded_total,
            "share": _share(found_total, seeded_total),
        },
        "cases": per_case,
        "errors": errors,
    }
    out = out_dir / f"critic-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log.info("evals.critic_completed", extra={"case_count": len(cases)})
    return CriticEvalOutcome(report=report, out_dir=out)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render(report: Mapping[str, Any]) -> str:
    """The report as a short table for the console."""
    verdict = "PASSED" if report["passed"] else "FAILED"
    lines = [
        f"Critic eval {verdict}: {report['case_count']} case(s), {report['profile']}",
    ]
    rows = [*report["per_defect"].items(), ("overall", report["overall"])]
    for name, tally in rows:
        lines.append(
            f"  {name:<18} found {tally['found']}/{tally['seeded']}  ({_percent(tally['share'])})"
        )
    for case in report["cases"]:
        if case["uncovered_found"] != case["uncovered"]:
            missed = sorted(set(case["uncovered"]) - set(case["uncovered_found"]))
            lines.append(
                f"  {case['case']}: uncovered Requirement not reported ({', '.join(missed)})"
            )
    for name, error in report["errors"].items():
        lines.append(f"  {name}: model call failed ({error})")
    return "\n".join(lines)
