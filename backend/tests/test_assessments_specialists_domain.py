"""Specialist Assessment rules (Epic 5 slice 5A), without a database: the run status from
its tasks', the reply validation (recommendation, confidence, Findings, effort) and hours."""

from decimal import Decimal

import pytest

from app.modules.assessments.domain.assessments import (
    AssessmentCandidate,
    AssessmentFindingCandidate,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    Confidence,
    EffortCandidate,
    FindingKind,
    Recommendation,
    hours_value,
    run_status,
    total_hours,
    validate_assessment,
)
from app.modules.assessments.domain.reviews import Severity

Q, R, S, F = (
    AssessmentTaskStatus.QUEUED,
    AssessmentTaskStatus.RUNNING,
    AssessmentTaskStatus.SUCCEEDED,
    AssessmentTaskStatus.FAILED,
)
LABELS = {"R1": "req-1", "R2": "req-2"}


@pytest.mark.parametrize(
    ("tasks", "expected"),
    [
        ((Q, Q, Q), AssessmentRunStatus.QUEUED),
        ((S, Q, Q), AssessmentRunStatus.RUNNING),
        ((R, S, F), AssessmentRunStatus.RUNNING),
        ((S, S, S), AssessmentRunStatus.SUCCEEDED),
        ((S, F, S), AssessmentRunStatus.PARTIALLY_FAILED),
        ((F, F, F), AssessmentRunStatus.FAILED),
    ],
)
def test_the_run_status_follows_its_tasks(
    tasks: tuple[AssessmentTaskStatus, ...], expected: AssessmentRunStatus
) -> None:
    assert run_status(tasks) is expected


def _finding(
    title: str = "SAP custom fields",
    requirements: tuple[str, ...] = ("R1",),
    *,
    kind: str = "risk",
    severity: str = "high",
    detail: str = "Not specified.",
) -> AssessmentFindingCandidate:
    return AssessmentFindingCandidate(
        kind=kind, severity=severity, title=title, detail=detail, requirements=requirements
    )


def _reply(
    *findings: AssessmentFindingCandidate,
    effort: tuple[EffortCandidate, ...] = (),
    recommendation: str = "proceed",
    confidence: str = "high",
    basis: str = "Clear scope.",
) -> AssessmentCandidate:
    return AssessmentCandidate(
        recommendation=recommendation,
        confidence=confidence,
        confidence_basis=basis,
        findings=findings,
        effort=effort,
    )


def test_a_valid_reply_keeps_everything_trimmed_and_resolved() -> None:
    validation = validate_assessment(
        _reply(
            _finding(" SAP custom fields ", (" R2", "R1", "R2", "G1")),
            effort=(EffortCandidate("R2", 12.25, " Two interfaces. "),),
            recommendation=" proceed_with_conditions ",
            confidence="low",
            basis=" Interfaces unknown. ",
        ),
        LABELS,
    )

    assert validation is not None
    assert validation.recommendation is Recommendation.PROCEED_WITH_CONDITIONS
    assert validation.confidence is Confidence.LOW
    assert validation.confidence_basis == "Interfaces unknown."
    (finding,) = validation.findings
    assert (finding.kind, finding.severity, finding.title) == (
        FindingKind.RISK,
        Severity.HIGH,
        "SAP custom fields",
    )
    assert finding.requirements == ("req-2", "req-1")
    (row,) = validation.effort
    assert (row.requirement, row.hours, row.basis) == ("req-2", Decimal("12.3"), "Two interfaces.")
    assert validation.dropped == 0


@pytest.mark.parametrize(
    "bad",
    [
        _finding(requirements=("R99",)),
        _finding(requirements=("G1",)),
        _finding(requirements=()),
        _finding(kind="worry"),
        _finding(severity="urgent"),
        _finding(title="   "),
        _finding(title="x" * 161),
        _finding(detail=""),
        _finding(detail="x" * 801),
    ],
    ids=["label", "gap-label", "none", "kind", "severity", "blank", "title", "no-detail", "detail"],
)
def test_an_invalid_finding_is_dropped_and_counted(bad: AssessmentFindingCandidate) -> None:
    validation = validate_assessment(_reply(_finding(), bad), LABELS)

    assert validation is not None
    assert len(validation.findings) == 1
    assert (validation.dropped_findings, validation.dropped) == (1, 1)


@pytest.mark.parametrize(
    "bad",
    [
        EffortCandidate("R99", 4, "x"),
        EffortCandidate("R1", 0, "x"),
        EffortCandidate("R1", 0.4, "x"),
        EffortCandidate("R1", 2000.1, "x"),
        EffortCandidate("R1", float("nan"), "x"),
        EffortCandidate("R1", float("inf"), "x"),
        EffortCandidate("R1", 4, " "),
        EffortCandidate("R1", 4, "x" * 301),
    ],
    ids=["label", "zero", "small", "large", "nan", "inf", "blank-basis", "basis"],
)
def test_an_invalid_effort_row_is_dropped_and_counted(bad: EffortCandidate) -> None:
    validation = validate_assessment(
        _reply(_finding(), effort=(EffortCandidate("R2", 8, "Sized."), bad)), LABELS
    )

    assert validation is not None
    assert [row.requirement for row in validation.effort] == ["req-2"]
    assert (validation.dropped_effort, validation.dropped) == (1, 1)


def test_a_requirement_sized_twice_keeps_the_first_row() -> None:
    validation = validate_assessment(
        _reply(
            _finding(),
            effort=(EffortCandidate("R1", 8, "First."), EffortCandidate("R1", 9, "Second.")),
        ),
        LABELS,
    )

    assert validation is not None
    assert [(r.hours, r.basis) for r in validation.effort] == [(Decimal("8.0"), "First.")]
    assert validation.dropped_effort == 1


@pytest.mark.parametrize(
    "reply",
    [
        _reply(_finding(), recommendation="maybe"),
        _reply(_finding(), recommendation=""),
        _reply(_finding(), confidence="certain"),
        _reply(_finding(), basis="  "),
        _reply(_finding(), basis="x" * 501),
    ],
    ids=["recommendation", "no-recommendation", "confidence", "blank-basis", "long-basis"],
)
def test_an_invalid_recommendation_or_confidence_makes_the_reply_invalid(
    reply: AssessmentCandidate,
) -> None:
    assert validate_assessment(reply, LABELS) is None


def test_a_reply_without_a_valid_finding_has_none() -> None:
    validation = validate_assessment(_reply(_finding(requirements=("R9",))), LABELS)

    assert validation is not None
    assert validation.findings == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.5, Decimal("0.5")),
        (0.45, Decimal("0.5")),
        (0.44, None),
        (2000, Decimal("2000.0")),
        (2000.04, Decimal("2000.0")),
        (2000.05, None),
        (12.25, Decimal("12.3")),
        (-1, None),
    ],
)
def test_hours_are_rounded_to_a_tenth_and_bounded(raw: float, expected: Decimal | None) -> None:
    assert hours_value(raw) == expected


def test_the_total_is_the_sum_to_a_tenth() -> None:
    assert total_hours([Decimal("24.3"), Decimal("40.0"), Decimal("0.5")]) == Decimal("64.8")
    assert total_hours([]) == Decimal("0.0")
