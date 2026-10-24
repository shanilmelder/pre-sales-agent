"""Review Requests (Story 9.1; AD-28): types, targets, the state machine and the input rules.
Pure, no I/O.

A request asks one named reviewer to review one target, an Estimate Version or one of its
Assessments at a version, for one review type. Its status follows the state machine below:
9.1 uses only `pending → cancelled`; the decisions (9.3) and superseding (9.4) use the rest.
"""

from enum import StrEnum

MESSAGE_MAX = 2000
REASON_MAX = 1000
"""Limits in Unicode code points, on the trimmed text."""
REVIEWERS_MAX = 20
SUBJECT_TYPE = "reviews.review_request"


class ReviewType(StrEnum):
    ENGINEERING = "engineering"
    PM = "pm"
    SECURITY = "security"


REVIEW_TYPE_LABELS: dict[ReviewType, str] = {
    ReviewType.ENGINEERING: "Engineering",
    ReviewType.PM: "PM",
    ReviewType.SECURITY: "Security",
}


class TargetKind(StrEnum):
    ESTIMATE_VERSION = "estimate_version"
    ASSESSMENT = "assessment"


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


STATUS_LABELS: dict[RequestStatus, str] = {
    RequestStatus.PENDING: "Pending",
    RequestStatus.APPROVED: "Approved",
    RequestStatus.REJECTED: "Rejected",
    RequestStatus.CHALLENGED: "Challenged",
    RequestStatus.SUPERSEDED: "Superseded",
    RequestStatus.CANCELLED: "Cancelled",
}

TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.PENDING: frozenset(
        {
            RequestStatus.APPROVED,
            RequestStatus.REJECTED,
            RequestStatus.CHALLENGED,
            RequestStatus.SUPERSEDED,
            RequestStatus.CANCELLED,
        }
    ),
    # A decided request is replaced only when a newer version supersedes it (9.4).
    RequestStatus.APPROVED: frozenset({RequestStatus.SUPERSEDED}),
    RequestStatus.REJECTED: frozenset({RequestStatus.SUPERSEDED}),
    RequestStatus.CHALLENGED: frozenset({RequestStatus.SUPERSEDED}),
    RequestStatus.SUPERSEDED: frozenset(),
    RequestStatus.CANCELLED: frozenset(),
}
"""Every allowed move; anything else is forbidden."""

OPEN_STATUSES = frozenset({RequestStatus.PENDING, RequestStatus.REJECTED, RequestStatus.CHALLENGED})
"""The requests that stand between a version and its Baseline (`to_baseline`)."""


class InvalidTransitionError(ValueError):
    """A status change the state machine forbids."""


def can_transition(current: RequestStatus, target: RequestStatus) -> bool:
    return target in TRANSITIONS[current]


def transition(current: RequestStatus, target: RequestStatus) -> RequestStatus:
    """`target`, or `InvalidTransitionError` when the move is forbidden."""
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"A {current.value} Review Request can't become {target.value}"
        )
    return target


def clean_message(raw: str | None) -> str | None:
    """The trimmed message, None when blank; `ValueError` when over `MESSAGE_MAX`."""
    text = (raw or "").strip()
    if len(text) > MESSAGE_MAX:
        raise ValueError("message too long")
    return text or None


def clean_reason(raw: str) -> str | None:
    """The trimmed cancel reason, or None when blank or over `REASON_MAX`."""
    text = raw.strip()
    return text if 1 <= len(text) <= REASON_MAX else None
