"""Challenges (Story 9.5; AD-28, FR-38): targets, the state machine, the reason rule and the
deterministic suggestion of the Assessments to rerun. Pure, no I/O.

Someone who disputes an Estimate Version, an Assessment or one of its Findings raises a
Challenge with a reason. The platform suggests which Assessments to rerun; the
Opportunity's owner confirms some of them (a `challenge` Workflow Run starts and the
Challenge is `reassessing`) or declines it with a reason. Only Story 9.6's run writes
`completed` or `failed`. The Critic and the Red Team always rerun and are never toggled.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.reviews.domain.requests import REASON_MAX

SUBJECT_TYPE = "reviews.challenge"
ALWAYS_RERUN: tuple[str, ...] = ("Critic", "Red Team")
"""Listed as rerunning on every Challenge, never toggleable."""


class ChallengeTargetKind(StrEnum):
    ESTIMATE_VERSION = "estimate_version"
    ASSESSMENT = "assessment"
    FINDING = "finding"


class ChallengeStatus(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    REASSESSING = "reassessing"
    COMPLETED = "completed"
    DECLINED = "declined"
    FAILED = "failed"


CHALLENGE_STATUS_LABELS: dict[ChallengeStatus, str] = {
    ChallengeStatus.AWAITING_CONFIRMATION: "Awaiting confirmation",
    ChallengeStatus.REASSESSING: "Reassessing",
    ChallengeStatus.COMPLETED: "Completed",
    ChallengeStatus.DECLINED: "Declined",
    ChallengeStatus.FAILED: "Failed",
}

CHALLENGE_TRANSITIONS: dict[ChallengeStatus, frozenset[ChallengeStatus]] = {
    ChallengeStatus.AWAITING_CONFIRMATION: frozenset(
        {ChallengeStatus.REASSESSING, ChallengeStatus.DECLINED}
    ),
    # Story 9.6's run writes these.
    ChallengeStatus.REASSESSING: frozenset({ChallengeStatus.COMPLETED, ChallengeStatus.FAILED}),
    ChallengeStatus.COMPLETED: frozenset(),
    ChallengeStatus.DECLINED: frozenset(),
    ChallengeStatus.FAILED: frozenset(),
}
"""Every allowed move; anything else is forbidden."""


class InvalidChallengeTransitionError(ValueError):
    """A status change the Challenge state machine forbids."""


def can_transition(current: ChallengeStatus, target: ChallengeStatus) -> bool:
    return target in CHALLENGE_TRANSITIONS[current]


def transition(current: ChallengeStatus, target: ChallengeStatus) -> ChallengeStatus:
    """`target`, or `InvalidChallengeTransitionError` when the move is forbidden."""
    if not can_transition(current, target):
        raise InvalidChallengeTransitionError(
            f"A {current.value} Challenge can't become {target.value}"
        )
    return target


def clean_challenge_reason(raw: str | None) -> str | None:
    """The trimmed reason, or None when blank or over `REASON_MAX` code points."""
    text = (raw or "").strip()
    return text if 1 <= len(text) <= REASON_MAX else None


# --- suggestions ----------------------------------------------------------------------------

SPECIALISTS: tuple[str, ...] = ("engineering_agent", "pm_agent", "security_agent")
AGENT_LABELS: dict[str, str] = {
    "engineering_agent": "Engineering Agent",
    "pm_agent": "PM Agent",
    "security_agent": "Security Agent",
}


class SuggestionTag(StrEnum):
    SUGGESTED = "suggested"
    """Holds the target: pre-ticked."""
    OPTIONAL = "optional"
    """Shares a Requirement or an Integration Type with the target: unticked."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    agent: str
    why: str
    tag: SuggestionTag

    @property
    def preselected(self) -> bool:
        return self.tag is SuggestionTag.SUGGESTED


@dataclass(frozen=True, slots=True)
class CitingAssessment:
    """A current Assessment as the rule sees it: its agent and the Requirements its Findings
    cite."""

    agent: str
    requirement_ids: frozenset[UUID]


def _agent_rank(agent: str) -> int:
    return SPECIALISTS.index(agent) if agent in SPECIALISTS else len(SPECIALISTS)


def suggest(
    *,
    holders: Sequence[tuple[str, str]],
    target_requirements: frozenset[UUID],
    requirement_numbers: Mapping[UUID, int],
    requirement_types: Mapping[UUID, Sequence[tuple[UUID, str]]],
    others: Sequence[CitingAssessment],
) -> list[Suggestion]:
    """The Assessments to suggest rerunning, deterministically:

    - `holders` (agent, why): the Assessments holding the target, **Suggested** (pre-ticked).
    - Every other Assessment whose Findings cite one of `target_requirements` ("Cites R12",
      the lowest number first), else one tagged with one of their Integration Types ("Shares
      the ERP integration type"), **Optional** (unticked).

    Holders first, then the others in agent order; an agent is listed once."""
    seen: set[str] = set()
    found: list[Suggestion] = []
    for agent, reason in holders:
        if agent not in seen:
            seen.add(agent)
            found.append(Suggestion(agent=agent, why=reason, tag=SuggestionTag.SUGGESTED))
    target_types: dict[UUID, str] = {}
    for rid in sorted(target_requirements, key=str):
        for entry_id, name in requirement_types.get(rid, ()):
            target_types.setdefault(entry_id, name)

    def numbered(ids: frozenset[UUID]) -> list[UUID]:
        return sorted(ids, key=lambda r: (requirement_numbers.get(r, 1 << 30), str(r)))

    for other in sorted(others, key=lambda o: _agent_rank(o.agent)):
        if other.agent in seen:
            continue
        shared = numbered(other.requirement_ids & target_requirements)
        why: str | None = None
        if shared:
            number = requirement_numbers.get(shared[0])
            why = f"Cites R{number}" if number is not None else "Cites the same Requirement"
        else:
            for rid in numbered(other.requirement_ids):
                names = [n for e, n in requirement_types.get(rid, ()) if e in target_types]
                if names:
                    why = f"Shares the {names[0]} integration type"
                    break
        if why is not None:
            seen.add(other.agent)
            found.append(Suggestion(agent=other.agent, why=why, tag=SuggestionTag.OPTIONAL))
    return found
