"""The trace event catalogue (AD-12): one Pydantic payload model per `event_type`.

Event names follow `<module>.<entity>.<past_tense_verb>`, e.g. `identity.user.provisioned`.
Payloads reject unknown fields and hold IDs and technical values, never customer content.
Register a new event by subclassing `TracePayload` and decorating it with `@register`.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
EVENT_TYPE_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}\.{_SEGMENT}$")
# Past tense check on the verb's last word: regular verbs end in "ed"; list irregular
# past participles here when an event needs one. This is a heuristic, not a guarantee:
# non-past words that end in "ed" (need, seed) also pass, so reviewers still check names.
_IRREGULAR_PAST_TENSE = frozenset({"built", "done", "lost", "made", "run", "sent", "won"})


def is_valid_event_type(name: str) -> bool:
    """Shape check plus the past-tense heuristic above (not a grammatical guarantee)."""
    if not EVENT_TYPE_RE.match(name):
        return False
    last_word = name.rsplit(".", 1)[1].rsplit("_", 1)[-1]
    return last_word.endswith("ed") or last_word in _IRREGULAR_PAST_TENSE


class TracePayload(BaseModel):
    """Base for event payloads. Subclasses set `event_type`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: ClassVar[str]


_CATALOGUE: dict[str, type[TracePayload]] = {}
CATALOGUE: Mapping[str, type[TracePayload]] = MappingProxyType(_CATALOGUE)


def register[P: type[TracePayload]](cls: P) -> P:
    name = getattr(cls, "event_type", None)
    if not isinstance(name, str) or not is_valid_event_type(name):
        raise ValueError(f"{cls.__name__}.event_type must match <module>.<entity>.<past_verb>")
    if name in _CATALOGUE:
        raise ValueError(f"event_type {name!r} is already registered")
    if cls.model_config.get("extra") != "forbid":
        raise ValueError(f"{cls.__name__} must forbid extra fields")
    _CATALOGUE[name] = cls
    return cls


# --- identity -----------------------------------------------------------------------------


@register
class IdentityUserProvisioned(TracePayload):
    """A platform user was created from a first valid sign-in (Story 1.4 Part B may extend)."""

    event_type: ClassVar[str] = "identity.user.provisioned"


@register
class IdentityUserRoleAssigned(TracePayload):
    """An administrator assigned a role. Actor: the administrator; subject: the user."""

    event_type: ClassVar[str] = "identity.user.role_assigned"

    role: str


@register
class IdentityUserRoleRemoved(TracePayload):
    """An administrator removed a role. Actor: the administrator; subject: the user."""

    event_type: ClassVar[str] = "identity.user.role_removed"

    role: str


# --- opportunities ------------------------------------------------------------------------
# Subject: the Opportunity (`opportunities.opportunity`), and `opportunity_id` is set.
# Payloads hold ids only, never customer content.


@register
class OpportunitiesOpportunityCreated(TracePayload):
    """A presales engineer created an Opportunity. Actor: the creator (its owner)."""

    event_type: ClassVar[str] = "opportunities.opportunity.created"


@register
class OpportunitiesOpportunityUpdated(TracePayload):
    """The owner edited the Opportunity. `fields`: the names of the fields that changed,
    never their values."""

    event_type: ClassVar[str] = "opportunities.opportunity.updated"

    fields: list[Literal["title", "target_proposal_date"]]


@register
class OpportunitiesCollaboratorAdded(TracePayload):
    """The owner added a collaborator. `user_id`: the collaborator."""

    event_type: ClassVar[str] = "opportunities.collaborator.added"

    user_id: str


@register
class OpportunitiesCollaboratorRemoved(TracePayload):
    """The owner removed a collaborator. `user_id`: the former collaborator."""

    event_type: ClassVar[str] = "opportunities.collaborator.removed"

    user_id: str


# --- intake -------------------------------------------------------------------------------
# Subject: the Source (`intake.source`), and `opportunity_id` is set. Payloads hold ids,
# kinds and sizes only, never filenames or content.


@register
class IntakeSourceAdded(TracePayload):
    """A version of a Source was added (a new Source is version 1; the same bytes uploaded
    again to the Opportunity are its next version). Actor: the uploader."""

    event_type: ClassVar[str] = "intake.source.added"

    version: int
    kind: str
    size_bytes: int


@register
class IntakeSourceParsed(TracePayload):
    """A Source version's text was extracted and stored (Story 2.2 Part B). Actor: the
    worker (`system`). `char_count` is in Unicode code points."""

    event_type: ClassVar[str] = "intake.source.parsed"

    version: int
    char_count: int


@register
class IntakeSourceParseRetried(TracePayload):
    """A collaborator queued a failed Source version's parse again (Story 2.2 Part B).
    `error_code`: the failure being retried."""

    event_type: ClassVar[str] = "intake.source.parse_retried"

    version: int
    error_code: str


@register
class IntakeExtractionCompleted(TracePayload):
    """A Requirement extraction finished and its Requirements were stored (Story 2.5 Part A).
    Subject: the extraction (`intake.extraction`). Actor: the agent (`intake_agent@<semver>`).
    Counts only: Requirements stored, dropped (no citation resolved), and Sources read."""

    event_type: ClassVar[str] = "intake.extraction.completed"

    requirement_count: int
    dropped_count: int
    source_count: int


@register
class IntakeRequirementEdited(TracePayload):
    """A person changed a Requirement's text and/or classification (Story 2.6), making a new
    version and locking it against re-extraction. Subject: the Requirement
    (`intake.requirement`), at its new version. Field names only, never the text."""

    event_type: ClassVar[str] = "intake.requirement.edited"

    fields: list[Literal["text", "classification"]]
    version: int


@register
class IntakeRequirementConfirmed(TracePayload):
    """A person confirmed a Requirement (Story 2.6), on its own or with **Confirm all**,
    locking it against re-extraction. Subject: the Requirement (`intake.requirement`)."""

    event_type: ClassVar[str] = "intake.requirement.confirmed"

    version: int


# --- gaps ---------------------------------------------------------------------------------
# Story 4.3. Payloads hold ids, categories, impacts and counts only, never Gap, question or
# Requirement text.


@register
class GapsGapRaised(TracePayload):
    """A detection raised a Gap. Subject: the Gap (`gaps.gap`). Actor: the agent
    (`clarification_agent@<semver>`). `requirement_ids`: the Requirements it relates to."""

    event_type: ClassVar[str] = "gaps.gap.raised"

    detection_id: str
    category: str
    impact: str
    requirement_ids: list[str]


@register
class GapsClarificationQuestionDrafted(TracePayload):
    """A Clarification Question was drafted for a Gap. Subject: the question
    (`gaps.clarification_question`). Actor: the agent."""

    event_type: ClassVar[str] = "gaps.clarification_question.drafted"

    gap_id: str


@register
class GapsDetectionCompleted(TracePayload):
    """A Gap detection finished and its Gaps were stored. Subject: the detection
    (`gaps.detection`). Actor: the agent. Counts only: Gaps stored, candidates dropped,
    Requirements read, and earlier open Gaps superseded."""

    event_type: ClassVar[str] = "gaps.detection.completed"

    gap_count: int
    dropped_count: int
    requirement_count: int
    superseded_count: int


@register
class GapsGapConverted(TracePayload):
    """An open Gap was converted into an Assumption (Story 8.4): the Assumption was accepted.
    Subject: the Gap (`gaps.gap`). Actor: the accepting person. `assumption_kind`:
    `condition` or `contingency`."""

    event_type: ClassVar[str] = "gaps.gap.converted"

    assumption_kind: Literal["condition", "contingency"]
    row_version: int


# --- estimates ----------------------------------------------------------------------------
# Story 8.1. Payloads hold the version number and counts only, never line or Requirement
# text.


@register
class EstimatesEstimateVersionCreated(TracePayload):
    """An accepted draft created an Estimate Version. Subject: the version
    (`estimates.estimate_version`). Actor: the agent (`estimating_agent@<semver>`). Counts
    only: lines stored, lines dropped, active Requirements no line covers, Requirements read,
    and earlier draft versions superseded."""

    event_type: ClassVar[str] = "estimates.estimate_version.created"

    version: int
    template_version: str
    line_count: int
    dropped_count: int
    uncovered_count: int
    requirement_count: int
    superseded_count: int


# Story 8.4. Payloads hold ids, kinds and hours only, never Assumption wording or Gap text.


@register
class EstimatesAssumptionProposed(TracePayload):
    """`estimating_agent`'s Assumption proposals for an Estimate Version were stored, all
    unaccepted. Subject: the version (`estimates.estimate_version`). Actor: the agent. Counts
    only: proposals stored (by kind), proposals dropped (invalid or a second one for a Gap),
    and open Gaps left without a proposal."""

    event_type: ClassVar[str] = "estimates.assumption.proposed"

    count: int
    condition_count: int
    contingency_count: int
    dropped_count: int
    duplicate_count: int
    unconverted_count: int


@register
class EstimatesAssumptionAccepted(TracePayload):
    """An Assumption was accepted. Subject: the Assumption (`estimates.assumption`). Actor: the
    accepting person, also named in `accepted_by`. `amount_hours` is null for a Condition."""

    event_type: ClassVar[str] = "estimates.assumption.accepted"

    version_id: str
    kind: Literal["condition", "contingency"]
    amount_hours: float | None
    line_id: str | None
    gap_id: str
    accepted_by: str
