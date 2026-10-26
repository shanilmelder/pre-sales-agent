"""Review Decisions (Story 9.3; AD-28): what a reviewer decides on a Review Request, the
status each decision leaves the request in, and the reason rule. Pure, no I/O.

Decisions are append-only. A request's status follows from its latest decision through the
request state machine (`requests.transition`): Approve and Reject close it, Request evidence,
Request alternative and Escalate leave it `pending` (an escalation hands it to another
reviewer). `challenged` is recorded only by raising a Challenge (Story 9.5), never through
`reviews.decide`.
"""

from enum import StrEnum

from app.modules.reviews.domain.requests import REASON_MAX, RequestStatus


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHALLENGED = "challenged"
    EVIDENCE_REQUESTED = "evidence_requested"
    ALTERNATIVE_REQUESTED = "alternative_requested"
    ESCALATED = "escalated"


DECISION_LABELS: dict[Decision, str] = {
    Decision.APPROVED: "Approved",
    Decision.REJECTED: "Rejected",
    Decision.CHALLENGED: "Challenged",
    Decision.EVIDENCE_REQUESTED: "Evidence requested",
    Decision.ALTERNATIVE_REQUESTED: "Alternative requested",
    Decision.ESCALATED: "Escalated",
}

OUTCOME_VERBS: dict[Decision, str] = {
    Decision.APPROVED: "approved",
    Decision.REJECTED: "rejected",
    Decision.CHALLENGED: "challenged",
    Decision.EVIDENCE_REQUESTED: "requested evidence on",
    Decision.ALTERNATIVE_REQUESTED: "requested an alternative to",
    Decision.ESCALATED: "escalated",
}
"""Story 9.4: how an outcome Inbox item words the decision, e.g. "Ana Ruiz rejected Estimate
v3: …"."""


def outcome_summary(reviewer: str, decision: Decision, target: str, reason: str | None) -> str:
    """Story 9.4: "{Reviewer} {decision} {target}: {reason}" (no colon without a reason)."""
    head = f"{reviewer} {OUTCOME_VERBS[decision]} {target}"
    return f"{head}: {reason}" if reason else head


RECORDABLE = frozenset(Decision) - {Decision.CHALLENGED}
"""What `reviews.decide` records; `challenged` is recorded by `reviews.raise_challenge`."""

_STATUS_AFTER: dict[Decision, RequestStatus | None] = {
    Decision.APPROVED: RequestStatus.APPROVED,
    Decision.REJECTED: RequestStatus.REJECTED,
    Decision.CHALLENGED: RequestStatus.CHALLENGED,
    Decision.EVIDENCE_REQUESTED: None,
    Decision.ALTERNATIVE_REQUESTED: None,
    Decision.ESCALATED: None,
}


def status_after(decision: Decision) -> RequestStatus | None:
    """The status the decision moves its request to, or None when it stays `pending`."""
    return _STATUS_AFTER[decision]


def reason_required(decision: Decision) -> bool:
    """Every decision but Approve needs a reason."""
    return decision is not Decision.APPROVED


def clean_decision_reason(decision: Decision, raw: str | None) -> str | None:
    """The trimmed reason, None when blank (only allowed for Approve). `ValueError` when a
    required reason is blank or any reason is over `REASON_MAX` code points."""
    text = (raw or "").strip()
    if len(text) > REASON_MAX or (not text and reason_required(decision)):
        raise ValueError("reason")
    return text or None
