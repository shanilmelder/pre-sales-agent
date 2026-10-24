"""The trace event catalogue (AD-12): one Pydantic payload model per `event_type`.

Event names follow `<module>.<entity>.<past_tense_verb>`, e.g. `identity.user.provisioned`.
Payloads reject unknown fields and hold IDs and technical values, never customer content.
Register a new event by subclassing `TracePayload` and decorating it with `@register`.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
EVENT_TYPE_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}\.{_SEGMENT}$")
# Past tense check on the verb's last word: regular verbs end in "ed"; list irregular
# past participles here when an event needs one. This is a heuristic, not a guarantee:
# non-past words that end in "ed" (need, seed) also pass, so reviewers still check names.
_IRREGULAR_PAST_TENSE = frozenset(
    {"built", "done", "lost", "made", "overridden", "run", "sent", "split", "won"}
)
# State events: names that report a state entered rather than a past-tense verb. Kept to the
# few the architecture names verbatim (Story 5.5: AD-7's `workflows.run.waiting_for_human`).
_STATE_EVENTS = frozenset({"workflows.run.waiting_for_human"})


def is_valid_event_type(name: str) -> bool:
    """Shape check plus the past-tense heuristic above (not a grammatical guarantee), or one
    of the allow-listed state events."""
    if not EVENT_TYPE_RE.match(name):
        return False
    if name in _STATE_EVENTS:
        return True
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
    """An administrator assigned a role. Actor: the administrator; subject: the user.

    Historical only: roles are managed in Auth0 since Story 1.9, so nothing appends this
    any more. Kept registered so existing rows stay readable."""

    event_type: ClassVar[str] = "identity.user.role_assigned"

    role: str


@register
class IdentityUserRoleRemoved(TracePayload):
    """An administrator removed a role. Actor: the administrator; subject: the user.

    Historical only (see `IdentityUserRoleAssigned`)."""

    event_type: ClassVar[str] = "identity.user.role_removed"

    role: str


# --- opportunities ------------------------------------------------------------------------
# Subject: the Opportunity (`opportunities.opportunity`), and `opportunity_id` is set.
# Payloads hold ids only, never customer content.


@register
class OpportunitiesOpportunityCreated(TracePayload):
    """A presales engineer created an Opportunity. Actor: the creator (its owner).
    `from_import`: started from an imported file (Story 1.7 import), which was added as its
    first Source (traced as `intake.source.added`)."""

    event_type: ClassVar[str] = "opportunities.opportunity.created"

    from_import: bool = False


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
class IntakeSourceParseStarted(TracePayload):
    """The worker began parsing a Source version (Story 2.3): its status is now `parsing`.
    Actor: the worker (`system`)."""

    event_type: ClassVar[str] = "intake.source.parse_started"

    version: int


@register
class IntakeSourceParseFailed(TracePayload):
    """A Source version's parse failed (Story 2.3): its status is now `failed`. Actor: the
    worker (`system`). `error_code`: the stable failure code, never the parser's message."""

    event_type: ClassVar[str] = "intake.source.parse_failed"

    version: int
    error_code: str


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
    version and locking it against re-extraction; or an extraction refined an unlocked one
    to its next version (Story 2.7, actor `intake_agent@<semver>`). Subject: the Requirement
    (`intake.requirement`), at its new version. Field names only, never the text."""

    event_type: ClassVar[str] = "intake.requirement.edited"

    fields: list[Literal["text", "classification"]]
    version: int


@register
class IntakeRequirementCreated(TracePayload):
    """A person added a Requirement the extraction missed (Story 2.6): `human`, locked, no
    Evidence. Subject: the new Requirement (`intake.requirement`), at `version` 1."""

    event_type: ClassVar[str] = "intake.requirement.created"

    version: int


@register
class IntakeRequirementDeleted(TracePayload):
    """A person deleted a Requirement with a reason (Story 2.6); it leaves the active list
    but stays in history. Subject: the Requirement (`intake.requirement`), at the `version`
    it had. The reason is never in the trace."""

    event_type: ClassVar[str] = "intake.requirement.deleted"

    version: int


@register
class IntakeRequirementSplit(TracePayload):
    """A person split a Requirement into two new ones (Story 2.6), each citing all of its
    Evidence; it is now `superseded`. Subject: the original (`intake.requirement`), at the
    `version` it had. `into`: the new Requirements' ids."""

    event_type: ClassVar[str] = "intake.requirement.split"

    version: int
    into: list[str]


class MergedFrom(BaseModel):
    """One Requirement a merge took, at the version it had."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: int


@register
class IntakeRequirementMerged(TracePayload):
    """A person merged Requirements into one new one (Story 2.6) citing all their Evidence;
    the originals are now `superseded`. Subject: the new Requirement (`intake.requirement`),
    at version 1. `from`: the originals."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, serialize_by_alias=True, validate_by_name=True
    )
    event_type: ClassVar[str] = "intake.requirement.merged"

    from_: list[MergedFrom] = Field(alias="from")


@register
class IntakeRequirementIntegrationTypesTagged(TracePayload):
    """A person changed a Requirement's Integration Type tags (Story 4.1). Subject: the
    Requirement (`intake.requirement`), at its current version (tags are not versioned).
    `added` and `removed`: catalogue entry ids."""

    event_type: ClassVar[str] = "intake.requirement.integration_types_tagged"

    added: list[str]
    removed: list[str]


@register
class IntakeRequirementConfirmed(TracePayload):
    """A person confirmed a Requirement (Story 2.6), on its own or with **Confirm all**,
    locking it against re-extraction. Subject: the Requirement (`intake.requirement`)."""

    event_type: ClassVar[str] = "intake.requirement.confirmed"

    version: int


@register
class IntakeRequirementChangeProposed(TracePayload):
    """A change to a human-locked Requirement was proposed (Story 2.7), e.g. by an extraction
    that read a new Source. Subject: the Requirement (`intake.requirement`), at the
    `base_version` the change was made against. `superseded_change_id`: the open change it
    replaces, if any. Ids and versions only, never the text."""

    event_type: ClassVar[str] = "intake.requirement_change.proposed"

    change_id: str
    base_version: int
    superseded_change_id: str | None = None


@register
class IntakeRequirementChangeAccepted(TracePayload):
    """A person accepted a pending Requirement change (Story 2.7): the Requirement's new
    `version`. Subject: the Requirement (`intake.requirement`)."""

    event_type: ClassVar[str] = "intake.requirement_change.accepted"

    change_id: str
    version: int


@register
class IntakeRequirementChangeRejected(TracePayload):
    """A person rejected a pending Requirement change with a reason (Story 2.7); the
    Requirement stays at `version`. Subject: the Requirement (`intake.requirement`). The
    reason is never in the trace."""

    event_type: ClassVar[str] = "intake.requirement_change.rejected"

    change_id: str
    version: int


# --- gaps ---------------------------------------------------------------------------------
# Story 4.3. Payloads hold ids, categories, impacts and counts only, never Gap, question or
# Requirement text.


@register
class GapsGapRaised(TracePayload):
    """A detection raised a Gap. Subject: the Gap (`gaps.gap`). Actor: the agent
    (`clarification_agent@<semver>`), or for a mandatory Gap (Story 4.2, `origin`
    `mandatory_checklist`) the system (`gaps.detect_gaps`). `requirement_ids`: the
    Requirements it relates to (none for a mandatory Gap)."""

    event_type: ClassVar[str] = "gaps.gap.raised"

    detection_id: str
    category: str
    impact: str
    requirement_ids: list[str]
    origin: str = "detected"


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
    Requirements read, earlier open Gaps superseded, and earlier open Gaps kept because a
    person edited or approved their question (Story 4.5)."""

    event_type: ClassVar[str] = "gaps.detection.completed"

    gap_count: int
    dropped_count: int
    requirement_count: int
    superseded_count: int
    kept_count: int = 0


@register
class GapsClarificationQuestionEdited(TracePayload):
    """A person changed a Clarification Question's text and/or topic (Story 4.5); an approved
    question returned to `drafted` (`approval_revoked`). Subject: the question
    (`gaps.clarification_question`). Field names only, never the text."""

    event_type: ClassVar[str] = "gaps.clarification_question.edited"

    gap_id: str
    fields: list[Literal["text", "topic"]]
    row_version: int
    approval_revoked: bool
    """The question was approved, and the edit returned it to drafted."""


@register
class GapsClarificationQuestionApproved(TracePayload):
    """A person approved a Clarification Question (Story 4.5), on its own or with **Approve
    all**. Subject: the question (`gaps.clarification_question`). `approved_by`: the
    approver's user id."""

    event_type: ClassVar[str] = "gaps.clarification_question.approved"

    gap_id: str
    approved_by: str
    row_version: int


@register
class GapsGapConverted(TracePayload):
    """An open Gap was converted into an Assumption (Story 8.4): the Assumption was accepted;
    or into a Risk (Story 8.5). Subject: the Gap (`gaps.gap`). Actor: the accepting or
    converting person. `assumption_kind`: `condition`, `contingency` or `risk`."""

    event_type: ClassVar[str] = "gaps.gap.converted"

    assumption_kind: Literal["condition", "contingency", "risk"]
    row_version: int


@register
class GapsGapImpactChanged(TracePayload):
    """A person changed an open Gap's impact (Story 4.4). Subject: the Gap (`gaps.gap`). The
    reason is never in the trace."""

    event_type: ClassVar[str] = "gaps.gap.impact_changed"

    old_impact: Literal["high", "medium", "low"]
    new_impact: Literal["high", "medium", "low"]
    row_version: int


@register
class GapsGapDismissed(TracePayload):
    """A person dismissed an open Gap (Story 4.4). Subject: the Gap (`gaps.gap`).
    `reason_kind`: `not_relevant` or `other`; the note is never in the trace."""

    event_type: ClassVar[str] = "gaps.gap.dismissed"

    reason_kind: Literal["not_relevant", "other"]
    row_version: int


@register
class GapsGapReopened(TracePayload):
    """A person reopened a dismissed (Story 4.4) or answered (Story 4.7) Gap. Subject: the Gap
    (`gaps.gap`). The reason is never in the trace."""

    event_type: ClassVar[str] = "gaps.gap.reopened"

    row_version: int


@register
class GapsClarificationQuestionExported(TracePayload):
    """A person exported the approved Clarification Questions of open Gaps (Story 4.6), to copy,
    `.docx` or an unsent `.eml` draft. Subject: the Opportunity
    (`opportunities.opportunity`). Ids only, never the text."""

    event_type: ClassVar[str] = "gaps.clarification_question.exported"

    format: Literal["copy", "docx", "eml"]
    question_ids: list[str]


@register
class GapsClarificationQuestionSent(TracePayload):
    """A person recorded that an approved Clarification Question was sent to the customer
    (Story 4.6). Subject: the question (`gaps.clarification_question`). `sent_on`: the date
    it was sent (ISO)."""

    event_type: ClassVar[str] = "gaps.clarification_question.sent"

    gap_id: str
    sent_on: str
    row_version: int


@register
class GapsClarificationQuestionMarkedUnanswered(TracePayload):
    """A person recorded that the customer won't answer a sent Clarification Question ("No
    answer", Story 4.6). Subject: the question (`gaps.clarification_question`)."""

    event_type: ClassVar[str] = "gaps.clarification_question.marked_unanswered"

    gap_id: str
    row_version: int


@register
class GapsClarificationQuestionAnswered(TracePayload):
    """A person recorded the customer's answer to a sent (or "No answer") Clarification
    Question, or confirmed a suggested one (Story 4.7). Subject: the question
    (`gaps.clarification_question`). `source_id` / `passage_id`: the Source and passage
    holding the answer, its Evidence. Ids only, never the answer text."""

    event_type: ClassVar[str] = "gaps.clarification_question.answered"

    gap_id: str
    source_id: str
    passage_id: str
    row_version: int


@register
class GapsGapAnswered(TracePayload):
    """The answer to its Clarification Question settled an open Gap (Story 4.7). Subject: the
    Gap (`gaps.gap`)."""

    event_type: ClassVar[str] = "gaps.gap.answered"

    question_id: str
    passage_id: str
    row_version: int


@register
class GapsAnswerMatchSuggested(TracePayload):
    """`clarification_agent` suggested that a passage of a new Source answers a sent question
    (Story 4.7); a person decides. Subject: the suggestion (`gaps.answer_match`). Actor:
    `clarification_agent@<semver>`. `injection_suspected`: the passage reads like an
    instruction to the platform."""

    event_type: ClassVar[str] = "gaps.answer_match.suggested"

    question_id: str
    passage_id: str
    injection_suspected: bool


@register
class GapsAnswerMatchConfirmed(TracePayload):
    """A person confirmed a suggested answer, which answered the question (Story 4.7).
    Subject: the suggestion (`gaps.answer_match`)."""

    event_type: ClassVar[str] = "gaps.answer_match.confirmed"

    question_id: str
    passage_id: str


@register
class GapsAnswerMatchRejected(TracePayload):
    """A person said a suggested passage is not an answer ("Not an answer", Story 4.7); the
    pair is never suggested again. Subject: the suggestion (`gaps.answer_match`)."""

    event_type: ClassVar[str] = "gaps.answer_match.rejected"

    question_id: str
    passage_id: str


# --- estimates ----------------------------------------------------------------------------
# Story 8.1. Payloads hold the version number and counts only, never line or Requirement
# text.


@register
class EstimatesEstimateVersionCreated(TracePayload):
    """An accepted draft, or a finished assessment run (Story 8.3), created an Estimate
    Version. Subject: the version (`estimates.estimate_version`). Actor: the agent
    (`estimating_agent@<semver>`), or the system for a version from the Assessments. Counts,
    the source and ids only: lines stored, lines dropped, active Requirements no line covers,
    Requirements read, earlier draft versions superseded, accepted Assumptions and line
    edits carried from the superseded draft (Stories 8.7, 8.2), where the lines came from
    and the assessment run's id (Story 8.3)."""

    event_type: ClassVar[str] = "estimates.estimate_version.created"

    version: int
    template_version: str
    line_count: int
    dropped_count: int
    uncovered_count: int
    requirement_count: int
    superseded_count: int
    carried_assumption_count: int = 0
    carried_risk_count: int = 0
    """Story 8.5: Risks carried from the superseded draft."""
    carried_edit_count: int = 0
    """Story 8.2: edited lines of the superseded draft carried onto a matching line."""
    uncarried_edit_count: int = 0
    """Story 8.2: edited lines of the superseded draft with no matching line."""
    source: Literal["model", "assessments"] = "model"
    """Story 8.3: `assessments` when built from the specialist Assessments as an assessment
    run finished (actor `system`), else `model`."""
    source_run_id: str | None = None
    """Story 8.3: that assessment run's id."""


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


# Story 8.5. Payloads hold ids, kinds, hours, levels and lengths only, never Assumption
# wording, Risk descriptions, reasons or Gap text.


@register
class EstimatesAssumptionEdited(TracePayload):
    """A person edited an Assumption of a draft version, which clears its acceptance.
    Subject: the Assumption (`estimates.assumption`). Actor: the person. Before and after:
    the kind, the hours (null for a Condition), the linked line and the wording's length;
    whether it was accepted before, and the reason's length."""

    event_type: ClassVar[str] = "estimates.assumption.edited"

    version_id: str
    gap_id: str
    before_kind: Literal["condition", "contingency"]
    after_kind: Literal["condition", "contingency"]
    before_hours: float | None
    after_hours: float | None
    before_line_id: str | None
    after_line_id: str | None
    before_wording_length: int
    after_wording_length: int
    was_accepted: bool
    reason_length: int


@register
class EstimatesRiskCreated(TracePayload):
    """A person converted an open Gap to a Risk of the draft version. Subject: the Risk
    (`estimates.risk`). Actor: the person. The levels, the description's length, and how
    many unaccepted Assumptions proposed for the Gap were removed."""

    event_type: ClassVar[str] = "estimates.risk.created"

    version_id: str
    gap_id: str
    likelihood: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    description_length: int
    removed_assumption_count: int


@register
class EstimatesRiskEdited(TracePayload):
    """A person edited a Risk of a draft version. Subject: the Risk (`estimates.risk`).
    Actor: the person. Before and after: the levels and the description's length; the
    reason's length."""

    event_type: ClassVar[str] = "estimates.risk.edited"

    version_id: str
    before_likelihood: Literal["low", "medium", "high"]
    after_likelihood: Literal["low", "medium", "high"]
    before_impact: Literal["low", "medium", "high"]
    after_impact: Literal["low", "medium", "high"]
    before_description_length: int
    after_description_length: int
    reason_length: int


# Story 8.2. A person's edit of a line: the before and after values and the person's own
# reason; never the line's title or any Requirement text.


@register
class EstimatesEstimateLineEdited(TracePayload):
    """A person changed an Estimate line's effort and/or role mix on a draft version.
    Subject: the line (`estimates.estimate_line`). Actor: the person. `version`: the Estimate
    Version's number. Role mixes are `{engineer, project_manager, qa}` in whole percent."""

    event_type: ClassVar[str] = "estimates.estimate_line.edited"

    version: int
    before_hours: float
    after_hours: float
    before_role_mix: dict[str, int]
    after_role_mix: dict[str, int]
    reason: str


# Story 8.8. The version and the format only, never any line, Assumption or question text.


@register
class EstimatesEstimateVersionExported(TracePayload):
    """An Estimate Version was exported to a file. Subject: the version
    (`estimates.estimate_version`). Actor: the person who exported it."""

    event_type: ClassVar[str] = "estimates.estimate_version.exported"

    version_id: str
    version: int
    format: Literal["xlsx", "docx"]


# Story 8.6. Ids, version numbers and counts only, never line or Assumption text.


@register
class EstimatesEstimateVersionSubmitted(TracePayload):
    """A draft Estimate Version was submitted with its submission blockers clear. Subject:
    the version (`estimates.estimate_version`). Actor: the person who submitted it. Counts:
    its lines and Assumptions, and earlier submitted versions it superseded."""

    event_type: ClassVar[str] = "estimates.estimate_version.submitted"

    version_id: str
    version: int
    line_count: int
    assumption_count: int
    superseded_count: int


@register
class EstimatesEstimateVersionSuperseded(TracePayload):
    """A submitted Estimate Version was superseded by the submission of a newer one. Subject:
    the superseded version (`estimates.estimate_version`). Actor: the person who submitted
    the newer one."""

    event_type: ClassVar[str] = "estimates.estimate_version.superseded"

    version_id: str
    version: int
    superseded_by_version_id: str
    superseded_by_version: int


# Story 6.5. Payloads hold the version and counts only, never Requirement, Gap or Finding text.


@register
class AssessmentsRedTeamReviewCompleted(TracePayload):
    """An accepted Red Team run created a Red Team Review. Subject: the Review
    (`assessments.review`). Actor: the agent (`red_team_agent@<semver>`). Counts only: Findings
    stored (and per severity), Findings dropped, Requirements, Gaps and Estimate lines read,
    and earlier Reviews superseded."""

    event_type: ClassVar[str] = "assessments.red_team_review.completed"

    version: int
    finding_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    dropped_count: int
    requirement_count: int
    gap_count: int
    line_count: int
    superseded_count: int


@register
class AssessmentsCriticReviewCompleted(TracePayload):
    """An accepted Critic task created a Critic Review (Story 6.4). Subject: the Review
    (`assessments.review`). Actor: the agent (`critic_agent@<semver>`). Counts only: Findings
    stored (and per severity), proposed Findings dropped, coverage Findings written by code
    for uncovered Requirements the agent did not report, Conflicts raised from its
    contradictions, and earlier Critic Reviews superseded."""

    event_type: ClassVar[str] = "assessments.critic_review.completed"

    version: int
    finding_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    dropped_count: int
    backstopped_count: int
    conflict_count: int
    superseded_count: int


# Story 6.6. A person's resolution or override of a Critic or Red Team Finding: the Review kind
# and version, the person's reason (their own words, as a Conflict's, FR-29), never the
# Finding's text.


class FindingEvidenceSummary(BaseModel):
    """An Evidence reference supplied to resolve a Finding: kind, id and version only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    id: str
    version: int | None


@register
class AssessmentsFindingResolved(TracePayload):
    """A person resolved an open Critic or Red Team Finding (Story 6.6). Subject: the Finding
    (`assessments.finding`). Actor: that person. `kind`: `evidence_supplied` (with the
    `evidence` references and the person's note as `reason`) or `addressed` (with the
    reason). `severity`: the Finding's."""

    event_type: ClassVar[str] = "assessments.finding.resolved"

    review_kind: Literal["red_team", "critic"]
    review_version: int
    severity: Literal["low", "medium", "high", "critical"]
    kind: Literal["evidence_supplied", "addressed"]
    reason: str
    evidence: list[FindingEvidenceSummary] = Field(default_factory=list)


@register
class AssessmentsFindingOverridden(TracePayload):
    """A person overrode an open Critic or Red Team Finding with a reason (Story 6.6).
    Subject: the Finding. Actor: that person (`person_id`). `policy_basis`: the grant that
    allowed it (`owner`, `head_of_delivery` or `security_reviewer`); `override_id`: the
    override row; `previous_override_id`: the earlier Finding's override it re-applies, if
    any."""

    event_type: ClassVar[str] = "assessments.finding.overridden"

    review_kind: Literal["red_team", "critic"]
    review_version: int
    severity: Literal["low", "medium", "high", "critical"]
    override_id: str
    person_id: str
    reason: str
    policy_basis: Literal["owner", "head_of_delivery", "security_reviewer"]
    previous_override_id: str | None = None


# Epic 5 slice 5A. Payloads hold ids, enums and counts only, never Requirement, Gap or Finding
# text.


@register
class AssessmentsAssessmentRunStarted(TracePayload):
    """An assessment run was started (or one of its tasks retried). Subject: the run
    (`assessments.assessment_run`). Actor: the person who started it, or the system
    (`workflows.execute`) for the automatic run after a Gap detection (Story 5.1).
    `agent_count`: the agents it runs."""

    event_type: ClassVar[str] = "assessments.assessment_run.started"

    agent_count: int


@register
class AssessmentsAssessmentRunCancelled(TracePayload):
    """A person cancelled a queued or running assessment run (Story 5.5). Subject: the run
    (`assessments.assessment_run`). Actor: that person. `skipped_count`: the unfinished tasks
    it skipped; `succeeded_count`: the tasks whose Assessments it kept."""

    event_type: ClassVar[str] = "assessments.assessment_run.cancelled"

    skipped_count: int
    succeeded_count: int


@register
class AssessmentsAssessmentCompleted(TracePayload):
    """A specialist agent's task succeeded and stored a new Assessment. Subject: the
    Assessment (`assessments.assessment`). Actor: the agent (`<agent_id>@<semver>`). Counts
    only: Findings stored (and per severity), effort rows stored, Findings and effort rows
    dropped, Requirements and Gaps read, and earlier Assessments superseded."""

    event_type: ClassVar[str] = "assessments.assessment.completed"

    run_id: str
    agent: str
    version: int
    recommendation: Literal["proceed", "proceed_with_conditions", "do_not_proceed"]
    confidence: Literal["high", "medium", "low"]
    finding_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    effort_count: int
    dropped_count: int
    requirement_count: int
    gap_count: int
    superseded_count: int


@register
class AssessmentsTaskSkipped(TracePayload):
    """An assessment run's task was skipped before it started because its Agent is not
    active in the Agent Registry (Story 7.1): since Story 5.5, once a person chose
    **Continue without** it and the run resumed. Subject: the run
    (`assessments.assessment_run`). Actor: the system (`workflows.execute`). Ids and the
    reason only."""

    event_type: ClassVar[str] = "assessments.task.skipped"

    run_id: str
    task_id: str
    agent: str
    config_version_id: str
    reason: Literal["agent_disabled"]


@register
class AssessmentsAssessmentRunCompleted(TracePayload):
    """Every task of an assessment run has finished. Subject: the run
    (`assessments.assessment_run`). Actor: the system (`workflows.execute`).
    `failed_count`: the tasks that neither succeeded nor were skipped by a person's choice
    to continue without their disabled Agent (Story 5.5), so `succeeded` has none."""

    event_type: ClassVar[str] = "assessments.assessment_run.completed"

    status: Literal["succeeded", "partially_failed", "failed"]
    task_count: int
    succeeded_count: int
    failed_count: int


# --- workflows ----------------------------------------------------------------------------
# Story 5.5 (pause and resume). Ids and codes only.


@register
class WorkflowsRunWaitingForHuman(TracePayload):
    """An assessment run paused on an open decision: a queued task's Agent is not active, so
    a person decides whether the run goes on without it. Appended once per decision. Subject:
    the run (`assessments.assessment_run`). Actor: the system (`workflows.execute`)."""

    event_type: ClassVar[str] = "workflows.run.waiting_for_human"

    decision_id: str
    task_id: str
    agent: str
    kind: Literal["plan_escalation"]


@register
class WorkflowsDecisionResolved(TracePayload):
    """A person resolved a run's decision: **Continue without** the Agent, or **Re-plan**
    (the task re-pinned to the Agent's current config version, a new plan version). The run
    is queued to resume. Subject: the run (`assessments.assessment_run`). Actor: that
    person. `config_version_id`: the task's pin after the decision."""

    event_type: ClassVar[str] = "workflows.decision.resolved"

    decision_id: str
    task_id: str
    agent: str
    kind: Literal["plan_escalation"]
    choice: Literal["continue_without", "replan"]
    plan_version: int
    config_version_id: str


# --- knowledge ----------------------------------------------------------------------------
# Story 3.1. Catalogue events have no Opportunity. Payloads hold ids, kinds and version
# numbers only, never an entry's code, name, definition or retirement reason.


@register
class KnowledgeCatalogueEntryCreated(TracePayload):
    """An administrator created a catalogue entry at version 1. Subject: the entry
    (`knowledge.catalogue_entry`)."""

    event_type: ClassVar[str] = "knowledge.catalogue_entry.created"

    kind: str
    version: int


@register
class KnowledgeCatalogueEntryUpdated(TracePayload):
    """An administrator changed an entry's name and/or definition, saving a new version.
    Subject: the entry. `from_version` and `to_version`: the version numbers before and
    after."""

    event_type: ClassVar[str] = "knowledge.catalogue_entry.updated"

    kind: str
    from_version: int
    to_version: int


@register
class KnowledgeCatalogueEntryRetired(TracePayload):
    """An administrator retired an entry. Subject: the entry. The reason is not traced."""

    event_type: ClassVar[str] = "knowledge.catalogue_entry.retired"

    kind: str
    version: int


@register
class KnowledgeCatalogueEntryReactivated(TracePayload):
    """An administrator reactivated a retired entry. Subject: the entry."""

    event_type: ClassVar[str] = "knowledge.catalogue_entry.reactivated"

    kind: str
    version: int


# Story 3.2. Knowledge Source events have no Opportunity (subject `knowledge.source`).
# Payloads hold ids, counts, kinds and version numbers only, never a title, product, file
# name, owner or text.


@register
class KnowledgeSourceRegistered(TracePayload):
    """A Knowledge Source was registered with its first file (version 1). Subject: the
    Source. `owner_id`: the user who owns it."""

    event_type: ClassVar[str] = "knowledge.source.registered"

    version: int
    owner_id: str
    tag_count: int
    size_bytes: int


@register
class KnowledgeSourceVersionAdded(TracePayload):
    """A new file was uploaded as the next version of a Knowledge Source. Subject: the
    Source. Earlier versions stay readable."""

    event_type: ClassVar[str] = "knowledge.source.version_added"

    from_version: int
    to_version: int
    size_bytes: int


@register
class KnowledgeSourceRetagged(TracePayload):
    """A Knowledge Source's tags, product, title or owner changed. Subject: the Source.
    `tag_ids_added` / `tag_ids_removed`: Integration Type ids; the other flags say which
    plain fields changed."""

    event_type: ClassVar[str] = "knowledge.source.retagged"

    tag_ids_added: list[str]
    tag_ids_removed: list[str]
    product_changed: bool
    title_changed: bool
    owner_changed: bool


@register
class KnowledgeSourceReviewed(TracePayload):
    """Someone marked a Knowledge Source reviewed today. Subject: the Source.
    `was_stale`: it was flagged stale beforehand."""

    event_type: ClassVar[str] = "knowledge.source.reviewed"

    was_stale: bool


@register
class KnowledgeSourceRetired(TracePayload):
    """A Knowledge Source was retired. Subject: the Source. The reason is not traced."""

    event_type: ClassVar[str] = "knowledge.source.retired"

    version: int


@register
class KnowledgeSourceParsed(TracePayload):
    """The worker extracted the text of a Knowledge Source version. Subject: the Source.
    Actor: the system (`knowledge.parse_source`)."""

    event_type: ClassVar[str] = "knowledge.source.parsed"

    version: int
    char_count: int


@register
class KnowledgeSourceParseRetried(TracePayload):
    """Someone queued a failed Knowledge Source version's parse again. Subject: the Source.
    `error_code` is the failure being retried."""

    event_type: ClassVar[str] = "knowledge.source.parse_retried"

    version: int
    error_code: str


# Story 3.3. Ids, counts and the embedding profile only, never chunk or query text.


@register
class KnowledgeSourceEmbedded(TracePayload):
    """The worker chunked and embedded a Knowledge Source version; it is Ready for search.
    Subject: the Source. Actor: the system (`knowledge.embed_source`). `model`: the
    embedding profile."""

    event_type: ClassVar[str] = "knowledge.source.embedded"

    version: int
    chunk_count: int
    model: str


@register
class KnowledgeSourceEmbedRetried(TracePayload):
    """Someone queued a Knowledge Source version's embedding again: after it failed
    (`error_code`), or for the first time for a version parsed before embedding existed
    (`error_code` None). Subject: the Source."""

    event_type: ClassVar[str] = "knowledge.source.embed_retried"

    version: int
    error_code: str | None


# Story 3.4. Checklist events have no Opportunity (subject `knowledge.checklist`). Ids,
# version numbers and counts only, never a name, item text or the retirement reason.


@register
class KnowledgeChecklistPublished(TracePayload):
    """Someone published a Checklist's draft as its next version. Subject: the Checklist.
    `item_count` and `mandatory_count`: the new version's items and mandatory items."""

    event_type: ClassVar[str] = "knowledge.checklist.published"

    version: int
    item_count: int
    mandatory_count: int


@register
class KnowledgeChecklistRetired(TracePayload):
    """Someone retired a Checklist; it no longer applies, and its versions stay readable.
    Subject: the Checklist. `version`: its latest published version (None if it was never
    published). The reason is not traced."""

    event_type: ClassVar[str] = "knowledge.checklist.retired"

    version: int | None
    discarded_draft: bool


# Story 5.4: Research Snapshots. Ids, codes, sizes and hashes only, never the URL or page text.


@register
class KnowledgeResearchSnapshotCaptured(TracePayload):
    """The research fetch kept a page as an immutable Research Snapshot. Subject: the snapshot
    (`knowledge.research_snapshot`). Actor: the Agent (`<agent_id>@<semver>`). The URL is not
    traced (it may carry customer terms); the row holds it."""

    event_type: ClassVar[str] = "knowledge.research_snapshot.captured"

    run_id: str | None
    task_id: str | None
    http_status: int
    content_type: Literal["text/html", "text/plain"]
    content_sha256: str
    text_sha256: str
    byte_count: int
    char_count: int
    parser: str


# --- conflicts ------------------------------------------------------------------------------


@register
class ConflictsConflictDetected(TracePayload):
    """A rule (or later a detector) raised a Conflict between Assessments (Story 6.1).
    Subject: the Conflict (`conflicts.conflict`). Actor: the system. The run that raised it,
    the Conflict's type, severity and detector, and how many positions it has; no Requirement
    or Finding text."""

    event_type: ClassVar[str] = "conflicts.conflict.detected"

    run_id: str
    type: Literal[
        "timeline",
        "effort",
        "resource",
        "architecture",
        "security",
        "scope",
        "assumption",
        "evidence",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    detected_by: Literal["rule", "semantic", "critic", "red_team"]
    position_count: int


class ConflictPositionSummary(BaseModel):
    """One original position of a Conflict as a decision records it (Story 6.3): its number,
    where it comes from (an agent's Assessment or the Estimate) and its summary (hours, a
    label or "Not sized")."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int
    source: Literal["assessment", "estimate"]
    agent: str | None
    summary: str


@register
class ConflictsConflictResolved(TracePayload):
    """A Conflict was resolved. Subject: the Conflict (`conflicts.conflict`).

    - By the system after a later run (Story 6.1; actor: the system; `run_id`: that run):
      `no_longer_present` when the run no longer raises it, `carried_forward` when it raises
      it again as a new Conflict that links this one.
    - By a person (Story 6.3; `decided`; actor: that person; no run): the `reason`, the
      choice (`chosen_position` or `entered_position`), every original position's summary,
      and for an `effort` decision the Estimate line it set (`line_id`, `applied_hours`) or
      why it set none (`not_applied`: `no_line`, `shared_line`, `several_lines`,
      `not_permitted`). The reason and the entered position are the person's words (FR-31)."""

    event_type: ClassVar[str] = "conflicts.conflict.resolved"

    run_id: str | None = None
    reason_kind: Literal["no_longer_present", "carried_forward", "decided"]
    reason: str | None = None
    chosen_position: int | None = None
    entered_position: str | None = None
    positions: list[ConflictPositionSummary] | None = None
    line_id: str | None = None
    applied_hours: float | None = None
    not_applied: Literal["no_line", "shared_line", "several_lines", "not_permitted"] | None = None


@register
class ConflictsConflictEscalated(TracePayload):
    """A person escalated an open Conflict to a named reviewer on the Opportunity (Story
    6.3). Subject: the Conflict. Actor: that person. `reviewer_id`: the reviewer's user id;
    `reason`: the person's words. `run_id`: none (a person's action)."""

    event_type: ClassVar[str] = "conflicts.conflict.escalated"

    run_id: str | None = None
    reviewer_id: str
    reason: str


# --- registry -----------------------------------------------------------------------------
# Story 7.1. Registry events have no Opportunity. Subject: the Agent (`registry.agent`), with
# its config version number as the subject version. Payloads hold the agent id, statuses and
# config version ids only: `from_config_version_id` is the current config version before the
# change (null when registering) and `to_config_version_id` the one after.

RegistryStatus = Literal["active", "disabled", "eval_only"]


@register
class RegistryAgentRegistered(TracePayload):
    """An administrator registered an Agent with its config version 1."""

    event_type: ClassVar[str] = "registry.agent.registered"

    agent_id: str
    status: RegistryStatus
    from_config_version_id: None = None
    to_config_version_id: str


@register
class RegistryAgentConfigVersionCreated(TracePayload):
    """An administrator created a new config version of an Agent; it is now current. Runs
    already in progress keep the version they pinned."""

    event_type: ClassVar[str] = "registry.agent_config.version_created"

    agent_id: str
    version: int
    from_config_version_id: str
    to_config_version_id: str


@register
class RegistryAgentEnabled(TracePayload):
    """An administrator set an Agent `active`."""

    event_type: ClassVar[str] = "registry.agent.enabled"

    agent_id: str
    from_status: RegistryStatus
    to_status: Literal["active"]
    from_config_version_id: str
    to_config_version_id: str


@register
class RegistryAgentDisabled(TracePayload):
    """An administrator set an Agent `disabled` or `eval_only`: it gets no new tasks."""

    event_type: ClassVar[str] = "registry.agent.disabled"

    agent_id: str
    from_status: RegistryStatus
    to_status: Literal["disabled", "eval_only"]
    from_config_version_id: str
    to_config_version_id: str


@register
class RegistryEvalCompleted(TracePayload):
    """`make eval` finished and stored a result (Story 7.6). Subject: the result
    (`registry.eval_result`). Actor: the eval harness (system). Ids, counts and pass/fail
    only: the config version ids it evaluated (by agent id), the reference-set version, how
    many Opportunities ran, bars that failed or were not measured, pending Evidence pairs,
    stage failures, and whether it passed and was accepted."""

    event_type: ClassVar[str] = "registry.eval.completed"

    result_id: str
    reference_set_version: str
    config_version_ids: dict[str, str]
    opportunity_count: int
    failed_bar_count: int
    not_measured_bar_count: int
    pending_count: int
    failure_count: int
    passed: bool
    accepted: bool


# --- platform -----------------------------------------------------------------------------


@register
class PlatformToolCallDenied(TracePayload):
    """The ToolGateway refused an Agent's tool call (Story 5.4). Subject: the call's
    `platform_tool_calls` row (`platform.tool_call`). Actor: the Agent. `actor_id`:
    `<agent_id>@<semver>`; `reason`: `tool_not_permitted | out_of_scope | unknown_tool |
    not_allowlisted`. Ids and codes only."""

    event_type: ClassVar[str] = "platform.tool_call.denied"

    actor_id: str
    tool: str
    reason: Literal["tool_not_permitted", "out_of_scope", "unknown_tool", "not_allowlisted"]
    task_id: str | None
