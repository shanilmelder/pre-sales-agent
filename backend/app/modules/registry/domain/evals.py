"""Evaluation gate rules (Story 7.6): the bars, how a result is judged against them and
against the last accepted result. Pure, no I/O.

Values are percentages (0-100). A bar is `not_measured` when its metric had nothing to
measure (no denominator): a warning that never fails the gate. A bar `fail`s when it misses
its threshold, or when it is more than `REGRESSION_POINTS` worse than the last accepted
result (for a `max` bar, such as irrelevant Gaps, worse means higher). `delta` is the value
minus the last accepted value, null on the first eval or when either side is unmeasured.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

SUBJECT_TYPE = "registry.eval_result"
REGRESSION_POINTS = 5.0
"""How far a bar may move the wrong way from the last accepted result before it fails."""

Comparator = Literal["min", "max"]


class BarStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - a status, not a password
    FAIL = "fail"
    NOT_MEASURED = "not_measured"


class Metric(StrEnum):
    EXTRACTION_RECALL = "extraction_recall"
    CITATION_VALIDITY = "citation_validity"
    GAP_RECALL = "gap_recall"
    IRRELEVANT_GAPS = "irrelevant_gaps"
    MANDATORY_GAP_RECALL = "mandatory_gap_recall"
    EVIDENCE_SUPPORT = "evidence_support"
    SCHEMA_VALID_RATE = "schema_valid_rate"
    """Reported, no bar."""
    INTEGRATION_RISK_RECALL = "integration_risk_recall"
    """Reported for Story 7.7, no bar."""


@dataclass(frozen=True, slots=True)
class BarSpec:
    metric: Metric
    label: str
    requirement: str
    agent_ids: tuple[str, ...]
    comparator: Comparator
    threshold: float


SPECIALIST_AGENTS = ("engineering_agent", "pm_agent", "security_agent")
EVIDENCE_AGENTS = (*SPECIALIST_AGENTS, "red_team_agent")

_INTAKE = ("intake_agent",)
_GAPS = ("clarification_agent",)

BARS: tuple[BarSpec, ...] = (
    BarSpec(Metric.EXTRACTION_RECALL, "Extraction recall", "FR-5", _INTAKE, "min", 90),
    BarSpec(Metric.CITATION_VALIDITY, "Citation validity", "FR-5", _INTAKE, "min", 100),
    BarSpec(Metric.GAP_RECALL, "Gap recall", "FR-11", _GAPS, "min", 80),
    BarSpec(Metric.IRRELEVANT_GAPS, "Irrelevant Gaps", "FR-11", _GAPS, "max", 20),
    BarSpec(
        Metric.MANDATORY_GAP_RECALL,
        "Mandatory-item Gaps",
        "FR-11",
        _GAPS,
        "min",
        100,
    ),
    BarSpec(Metric.EVIDENCE_SUPPORT, "Evidence support", "FR-25", EVIDENCE_AGENTS, "min", 95),
)


@dataclass(frozen=True, slots=True)
class BarResult:
    spec: BarSpec
    value: float | None
    status: BarStatus
    delta: float | None
    regressed: bool


def _meets(spec: BarSpec, value: float) -> bool:
    return value >= spec.threshold if spec.comparator == "min" else value <= spec.threshold


def _worsened_by(spec: BarSpec, delta: float) -> float:
    return -delta if spec.comparator == "min" else delta


def judge_bar(spec: BarSpec, value: float | None, previous: float | None) -> BarResult:
    """One bar against its threshold and the last accepted value (`previous`)."""
    if value is None:
        return BarResult(spec, None, BarStatus.NOT_MEASURED, None, regressed=False)
    delta = None if previous is None else round(value - previous, 1)
    regressed = delta is not None and _worsened_by(spec, delta) > REGRESSION_POINTS
    status = BarStatus.PASS if _meets(spec, value) and not regressed else BarStatus.FAIL
    return BarResult(spec, value, status, delta, regressed)


def judge(
    values: Mapping[str, float | None],
    previous: Mapping[str, float | None] | None,
    *,
    failure_count: int = 0,
) -> tuple[list[BarResult], bool]:
    """Every bar, and whether the result passes: every measured bar passes, none regressed,
    and no stage failed. `previous` is the last accepted result's overall values (None on
    the first eval)."""
    results = [
        judge_bar(
            spec,
            values.get(spec.metric.value),
            None if previous is None else previous.get(spec.metric.value),
        )
        for spec in BARS
    ]
    passed = failure_count == 0 and all(r.status != BarStatus.FAIL for r in results)
    return results, passed


def reference_set_version(digest_hex: str) -> str:
    """The reference-set version: the first 12 hex characters of its sha256."""
    version = digest_hex[:12].lower()
    if len(version) != 12 or any(c not in "0123456789abcdef" for c in version):
        raise ValueError("The reference-set version must be 12 hex characters.")
    return version
