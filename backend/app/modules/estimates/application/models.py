"""Read models for the Estimate (Stories 8.1, 8.4 and 8.5). Every number is calculated on the
server by `domain/arithmetic.py`; hours are person-hours with one decimal place."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from app.modules.conflicts.application.public import ConflictType
from app.modules.estimates.domain.assumptions import AssumptionKind, ProposalStatus
from app.modules.estimates.domain.estimates import (
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionSource,
    VersionStatus,
)
from app.modules.estimates.domain.risks import RiskLevel
from app.modules.gaps.application.public import GapCategory, Impact
from app.modules.opportunities.application.public import UserRef


class RoleMix(BaseModel):
    """Each role's share of a line's effort, in whole percent, summing to 100."""

    engineer: int = Field(ge=0, le=100)
    project_manager: int = Field(ge=0, le=100)
    qa: int = Field(ge=0, le=100)


class RoleHours(BaseModel):
    """Hours per role (0.1 h), summing exactly to the effort they split."""

    engineer: float
    project_manager: float
    qa: float


class Totals(BaseModel):
    """Effort, Contingency and total hours, and the effort per role."""

    effort_hours: float
    contingency_hours: float
    total_hours: float
    role_hours: RoleHours


class LineRequirement(BaseModel):
    """A Requirement the line covers, at the version it was drafted against. `label` is
    `R<n>`, the Requirement's stable number within the Opportunity, or `Superseded` once it
    is no longer active. `excerpt`: up to 140 characters of that version's text, with `…`
    when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class LineConflict(BaseModel):
    """An open or escalated `effort` or `scope` Conflict whose positions cite a Requirement
    the line covers (Story 8.3): its id and type. The UI marks the line "Open Conflict" and
    links to the Conflicts tab."""

    id: str
    type: ConflictType


class EstimateLine(BaseModel):
    """A work item: its effort and role mix (as drafted, or as a person last edited them),
    and its server-calculated role hours, Contingency (the sum of its linked Contingency
    Assumptions' hours, accepted or not) and total (effort plus Contingency).

    Story 8.2: `row_version` goes back in `If-Match` to edit it. `edited` is true once a
    person changed its effort or role mix (here, or on the earlier version a re-draft
    carried the edit from: `edit_carried_from_version`); `edited_by_name`, `edited_at` and
    `edit_reason` say who, when and why (null when not edited)."""

    id: str
    position: int = Field(ge=1)
    section: Section
    title: str
    basis: str
    role_mix: RoleMix
    effort_hours: float
    contingency_hours: float
    total_hours: float
    role_hours: RoleHours
    requirements: list[LineRequirement]
    row_version: int = Field(ge=1)
    edited: bool
    edited_by_name: str | None
    edited_at: datetime | None
    edit_reason: str | None
    edit_carried_from_version: int | None
    conflicts: list[LineConflict] = Field(
        description="Story 8.3: the open Conflicts about the Requirements it covers."
    )


class EstimateSection(BaseModel):
    """A template section with its lines (in position order) and their subtotal."""

    section: Section
    lines: list[EstimateLine]
    subtotal: Totals


class OriginGap(BaseModel):
    """The Gap an Assumption or a Risk was made from, as it is now. `status` is `open`,
    `converted` (converted to an Assumption, accepted or since edited, or to a Risk) or
    `superseded`."""

    id: str
    title: str
    category: GapCategory
    impact: Impact
    why_it_matters: str
    status: Literal["open", "superseded", "converted"]


class AssumptionLine(BaseModel):
    """The Estimate line a Contingency is linked to."""

    id: str
    title: str


class Assumption(BaseModel):
    """An Assumption of the version: a `condition` (proposal-ready wording, no hours) or a
    `contingency` (`amount_hours`, and the line it is linked to, if any), made from one Gap
    (`origin`). `accepted_by` and `accepted_at` are null until someone accepts it.
    `row_version` goes back in `If-Match` to accept or edit it. `carried_from_version`: the
    number of the earlier version a re-draft carried this Assumption from (Story 8.7), null
    for a proposal.

    Story 8.5: `position` is its register number (`A{position}`); `origin_superseded` is true
    when the Gap is no longer `open` or `converted`, or is open but changed since the
    Assumption was made from it; `origin_is_unknown` is true when the Gap is an Unknown (its
    why it matters opens with "Unknown to the customer:")."""

    id: str
    position: int = Field(ge=1)
    kind: AssumptionKind
    wording: str
    amount_hours: float | None
    line: AssumptionLine | None
    origin_kind: Literal["gap"]
    origin: OriginGap
    origin_superseded: bool
    origin_is_unknown: bool
    accepted_by: UserRef | None
    accepted_at: datetime | None
    row_version: int = Field(ge=1)
    carried_from_version: int | None


class AssumptionGroups(BaseModel):
    """The version's Assumptions in proposal order, grouped by kind. `contingency_hours`: the
    Contingencies' total, accepted or not."""

    conditions: list[Assumption]
    contingencies: list[Assumption]
    contingency_hours: float


class Risk(BaseModel):
    """A Risk of the version (Story 8.5), made from one Gap (`origin`, with
    `origin_superseded` as for an Assumption): a description, a likelihood and an impact. It
    is never accepted and never blocks submission. `position` is its number (`R{position}`);
    `row_version` goes back in `If-Match` to edit it; `carried_from_version`: the number of the
    earlier version a re-draft carried it from, null otherwise."""

    id: str
    position: int = Field(ge=1)
    description: str
    likelihood: RiskLevel
    impact: RiskLevel
    origin_kind: Literal["gap"]
    origin: OriginGap
    origin_superseded: bool
    row_version: int = Field(ge=1)
    carried_from_version: int | None


class AssumptionCounts(BaseModel):
    total: int = Field(ge=0)
    accepted: int = Field(ge=0)
    not_accepted: int = Field(ge=0)


class UnconvertedGap(BaseModel):
    """An open Gap that has no Assumption in this version."""

    id: str
    title: str
    category: GapCategory
    impact: Impact


class EstimateVersion(BaseModel):
    """An Estimate Version. `sections`: only those with lines, in template order.
    `totals`: the overall effort, Contingency and total, with the per-role totals; the
    Contingency includes every Contingency Assumption, accepted or not, and
    `unallocated_contingency_hours` (those linked to no line, in no section).
    `uncovered_count`: active Requirements no line covered when it was drafted;
    `dropped_count`: proposed lines that broke a rule.

    Story 8.4: `proposal_status` is the state of the version's Assumption proposals (null
    when none were queued); `assumptions` and `counts` its Assumptions; `unconverted_gaps`
    the open Gaps without an Assumption in it, once proposals have finished (empty before).

    Story 8.2: `uncarried_edit_count` is how many edited lines of the superseded draft (number
    `uncarried_edits_from_version`, null when the count is 0) had no matching line here; they
    stay in that version and the Trace.

    Story 8.3: `source` is `assessments` for a version built from the specialist Assessments
    when an assessment run finished (`source_run`, that run's number), `model` for an
    accepted model draft.

    Story 8.5: `risks` are its Risks, impact high first, then likelihood high first."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    template_version: str
    roles: list[EstimateRole]
    uncovered_count: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    row_version: int = Field(ge=1)
    created_at: datetime
    sections: list[EstimateSection]
    totals: Totals
    proposal_status: ProposalStatus | None
    assumptions: AssumptionGroups
    counts: AssumptionCounts
    unconverted_gaps: list[UnconvertedGap]
    unallocated_contingency_hours: float
    risks: list[Risk]
    uncarried_edit_count: int = Field(ge=0)
    uncarried_edits_from_version: int | None
    source: VersionSource
    source_run: int | None = Field(
        description="Story 8.3: for a version from the Assessments, the number of the "
        "assessment run it was built for (the Opportunity's runs, oldest first).",
    )
    submitted_at: datetime | None = Field(
        default=None,
        description="Story 8.6: when it was submitted; null for a version never submitted.",
    )


class EstimateDraft(BaseModel):
    """The Opportunity's latest Estimate draft. `error_code` is set only when `failed`."""

    status: DraftStatus
    error_code: DraftErrorCode | None


class CurrentEstimate(BaseModel):
    """An Opportunity's current Estimate Version number, its status (draft, or submitted:
    Story 8.6) and its total hours, Contingency included, for the Opportunity list."""

    version: int
    status: VersionStatus
    total_hours: float
    is_baseline: bool = False
    """Story 9.7: whether this version is the Opportunity's current Baseline."""


BlockerKind = Literal[
    "gap",
    "assumption",
    "conflict",
    "finding",
    "uncovered_requirement",
    "review_request",
    "no_review_request",
]


class Blocker(BaseModel):
    """One thing that stands between an Estimate Version and its submission (Story 8.6):
    its `kind`, the id of its subject (a Gap, Assumption, Conflict, Finding or Requirement),
    a short `title` and `detail` to show, and `href`, the web path that opens it."""

    kind: BlockerKind
    subject_id: str
    title: str
    detail: str
    href: str


class SubmissionBlockers(BaseModel):
    """`estimates.get_submission_blockers`, the only check of submittability (AD-27).
    `to_submit`: open Gaps (and Unknowns), unaccepted Assumptions, open and escalated
    Conflicts, open critical Findings of the current Critic and Red Team Reviews, and active
    Requirements no line covers, in that order; the version can be submitted when it is
    empty. `to_baseline` (Story 9.1): the version's pending, rejected and challenged Review
    Requests; Story 9.7: for a version past the draft, also `no_review_request` when none was
    sent and the content checks above (they can reopen after submit). A Baseline needs it
    empty."""

    to_submit: list[Blocker]
    to_baseline: list[Blocker]


class SubmissionVersion(BaseModel):
    """The current Estimate Version the blockers are for: its id, number, status and
    `row_version` (the `If-Match` of a submission)."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    created_at: datetime
    submitted_at: datetime | None


class SubmissionBlockersView(SubmissionBlockers):
    """The Opportunity's submission blockers (`GET …/submission-blockers`) for the Overview
    card and the header: the blockers, the current version (the draft, else the latest
    submitted; null before the first) and `can_submit`: whether the caller may submit and
    that version is a draft (the blockers still decide; the API re-checks them)."""

    version: SubmissionVersion | None
    can_submit: bool
    is_baseline: bool = Field(
        default=False,
        description="Story 9.7: whether that version is the Opportunity's current Baseline.",
    )
    baseline_version: int | None = Field(
        default=None,
        description="Story 9.7: the current Baseline's version number (null before the "
        "first): a version at or below it can't replace it.",
    )
    can_set_baseline: bool = Field(
        default=False,
        description="Story 9.7: whether the caller may set the Baseline (the owner and "
        "collaborators, not a sales representative). Set Baseline is offered on an approved "
        "version that isn't the Baseline and whose `to_baseline` is empty; the API re-checks.",
    )


class BaselineRef(BaseModel):
    """Story 9.7: the Opportunity's current Baseline: its version (id and number), when it was
    set and by whom."""

    version_id: str
    version: int = Field(ge=1)
    set_at: datetime
    set_by_name: str


class BaselineSet(BaseModel):
    """Story 9.7: the Baseline just set, and the version it replaced (null for the first)."""

    version_id: str
    version: int = Field(ge=1)
    set_at: datetime
    set_by_name: str
    previous_version_id: str | None
    previous_version: int | None


class BaselineApproval(BaseModel):
    """Story 9.7: one Review Request behind an Estimate Version, for the Set Baseline dialog:
    the reviewer who decided (else the reviewer), the review type, the request's status, and
    when and which decision (null while undecided)."""

    name: str
    review_type: Literal["engineering", "pm", "security"]
    status: str
    decided_at: datetime | None
    decision_id: str | None


class VersionGate(BaseModel):
    """Story 9.7: what Set Baseline needs to know about one Estimate Version: its id, number,
    status and `row_version` (the `If-Match`), whether it is the Baseline, its blockers to
    Baseline (`to_baseline`, the one check) and whether the caller may set the Baseline."""

    version_id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    is_baseline: bool
    to_baseline: list[Blocker]
    can_set_baseline: bool
    baseline_version: int | None = Field(
        default=None,
        description="The current Baseline's version number (null before the first): a version "
        "at or below it can't replace it.",
    )


class VersionListItem(BaseModel):
    """Story 9.7: one Estimate Version in the version switcher's full list: its number,
    status, whether it is the Baseline, who created it and when, and the reason given for a
    **New version** (null otherwise)."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    is_baseline: bool
    created_by_name: str | None
    created_at: datetime
    reason: str | None


class EstimateView(BaseModel):
    """The Opportunity's current Estimate Version (its draft, else its latest submitted one:
    Story 8.6), null before the first, and its
    latest draft run, null before the first. `can_start_draft`: whether the caller may start
    (retry) a draft; `can_accept_assumptions`: whether the caller may accept Assumptions;
    `can_export`: whether the caller may export the Estimate (Story 8.8); `can_edit_lines`:
    whether the caller may edit the draft's lines (Story 8.2); `assessment_running` (Story
    8.3): whether an assessment run is queued or running; `can_edit_assumptions`,
    `can_create_risks` and `can_edit_risks` (Story 8.5): whether the caller may edit
    Assumptions, convert Gaps to Risks and edit Risks. The UI only uses them to hide
    controls; the API decides (and no version but the draft can be changed)."""

    version: EstimateVersion | None
    draft: EstimateDraft | None
    can_start_draft: bool
    can_accept_assumptions: bool
    can_export: bool
    can_edit_lines: bool
    can_edit_assumptions: bool
    can_create_risks: bool
    can_edit_risks: bool
    assessment_running: bool = Field(
        description="Story 8.3: whether an assessment run of the Opportunity is queued or "
        "running (the Estimate is built when it finishes).",
    )
    blockers: SubmissionBlockers = Field(
        description="Story 8.6: the current version's submission blockers."
    )
    can_submit: bool = Field(
        description="Story 8.6: whether the caller may submit and the current version is a "
        "draft. Submit is offered only while `blockers.to_submit` is empty; the API re-checks."
    )
    can_request_review: bool = Field(
        default=False,
        description="Story 9.1: whether the caller may send Review Requests and the current "
        "version is submitted or in review.",
    )
    can_create_version: bool = Field(
        default=False,
        description="Story 9.4: whether the caller may start a new draft from the current "
        "version, which is rejected or approved (no draft exists then).",
    )
    baseline: BaselineRef | None = Field(
        default=None,
        description="Story 9.7: the Opportunity's current Baseline; null before the first.",
    )
    is_current: bool = Field(
        default=True,
        description="Story 9.7: whether `version` is the current Estimate Version (false when "
        "an earlier one was asked for with `?version=`: it is then read only).",
    )
    can_set_baseline: bool = Field(
        default=False,
        description="Story 9.7: whether the caller may set the Baseline (the owner and "
        "collaborators, not a sales representative). Set Baseline is offered on an approved "
        "version that isn't the Baseline and whose `blockers.to_baseline` is empty; the API "
        "re-checks.",
    )


class EstimateLineChanges(BaseModel):
    """A person's edit of an Estimate line (Story 8.2): new effort and/or role mix (at least
    one), and why. Fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    effort_hours: StrictInt | StrictFloat | None = Field(
        default=None,
        description="The new effort in hours, 0 to 2,000; rounded half up to 0.1.",
    )
    role_mix: dict[str, object] | None = Field(
        default=None,
        description="The new role mix: a whole percentage (0-100) for exactly each of the "
        "template's roles (`engineer`, `project_manager`, `qa`), summing to 100.",
    )
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")


class LineDiff(BaseModel):
    """Story 9.3: one line that differs between two Estimate Versions, matched by section and
    title (trimmed, case-insensitive): `added` (only in the newer), `removed` (only in the
    older) or `changed` (its hours or role mix differ). Hours include the line's
    Contingency; `delta_hours` is after minus before (a missing side counts as 0)."""

    change: Literal["added", "removed", "changed"]
    section: Section
    title: str
    before_hours: float | None
    after_hours: float | None
    delta_hours: float


class VersionDiff(BaseModel):
    """Story 9.3 (`estimates.compare_versions`): an Estimate Version against the one numbered
    just before it (`previous_version`, null for the first: `first` is then true and `lines`
    empty). `lines`: added, removed and changed lines in template order; the total hours of
    each side and their delta."""

    version: int = Field(ge=1)
    previous_version: int | None
    first: bool
    lines: list[LineDiff]
    total_before: float | None
    total_after: float
    total_delta: float


class SubmittedVersion(BaseModel):
    """A submitted Estimate Version (Story 8.6): its id, number, `submitted` status and new
    `row_version`, and how many earlier submitted versions it superseded."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    superseded_count: int = Field(ge=0)


class NewVersionCreate(BaseModel):
    """Story 9.4: start a new draft Estimate Version from a rejected or approved one, with an
    optional reason (at most 1,000 characters, trimmed)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr | None = Field(
        default=None, max_length=4000, description="Why; trimmed, at most 1,000 characters."
    )


class CreatedVersion(BaseModel):
    """Story 9.4: the new draft Estimate Version (its id, number, `draft` status and
    `row_version`) and the version it was copied from."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    base_version_id: str
    base_version: int = Field(ge=1)


class AcceptAllResult(BaseModel):
    """How many Assumptions were accepted."""

    count: int = Field(ge=0)


class AssumptionChanges(BaseModel):
    """A person's edit of an Assumption (Story 8.5): its kind, wording, hours and line, and
    why. Fields left out stay as they are; `amount_hours` and `line_id` may be null (a
    Condition has neither; a Contingency with no line is Unallocated). The whole result must
    keep the Story 8.4 rules."""

    model_config = ConfigDict(extra="forbid")

    kind: AssumptionKind | None = Field(default=None, description="`condition` or `contingency`.")
    wording: StrictStr | None = Field(
        default=None, description="Proposal-ready wording; trimmed, 1 to 500 characters."
    )
    amount_hours: StrictInt | StrictFloat | None = Field(
        default=None,
        description="A Contingency's hours, 0.5 to 1,000, rounded half up to 0.1; null for a "
        "Condition.",
    )
    line_id: UUID | None = Field(
        default=None,
        description="The line of this version a Contingency is linked to; null for none "
        "(Unallocated) and for a Condition.",
    )
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")


class RiskCreate(BaseModel):
    """Convert an open Gap to a Risk of the current draft (Story 8.5)."""

    model_config = ConfigDict(extra="forbid")

    gap_id: UUID
    description: StrictStr = Field(description="Trimmed, 1 to 500 characters.")
    likelihood: RiskLevel
    impact: RiskLevel


class RiskChanges(BaseModel):
    """A person's edit of a Risk (Story 8.5); fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    description: StrictStr | None = Field(default=None, description="Trimmed, 1 to 500 characters.")
    likelihood: RiskLevel | None = None
    impact: RiskLevel | None = None
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")


# --- lineage and compare (Story 9.9) --------------------------------------------------------


class LineageActor(BaseModel):
    """Who recorded a decision: a person's name, an agent's role in words (e.g. "Red Team
    Agent", with its version) or "System"."""

    type: Literal["user", "agent", "system"]
    id: str
    name: str
    version: str | None = None


class LineageEvidence(BaseModel):
    """An Evidence chip: a Requirement at the version cited (`label` `R<n>`, or `Superseded`
    once no longer active) or a Source passage (`S<n> · <file name>`, with its `passage_id`).
    `superseded`: the Requirement was edited after this version was cited, or is no longer
    active; the chip still opens the cited version."""

    kind: Literal["requirement", "source_document"]
    id: str
    version: int | None
    label: str
    superseded: bool
    passage_id: str | None = None
    excerpt: str = ""


class LineageRequirement(BaseModel):
    """A Requirement the line covers, at the version it cites (`text`: that version's text),
    with its Evidence chip. `active_version`: its current version (null once no longer
    active); `superseded` when that is newer than the cited one, or it is no longer active."""

    id: str
    version: int = Field(ge=1)
    label: str
    text: str
    active_version: int | None
    superseded: bool
    evidence: list[LineageEvidence]


class LineageFinding(BaseModel):
    """What sized or challenged the line, from the version's assessment run: a specialist
    `finding` or `effort` entry citing one of the line's Requirements (its agent, Assessment
    id and version), or a `critic` or `red_team` Finding citing them (or the line). `title`:
    the Finding's title, or the effort's Requirement; `detail`: its detail, or the effort's
    basis; `hours` for an effort entry. `evidence`: the cited Requirement versions.
    `superseded`: a rerun replaced the Assessment (or a newer Review the Review)."""

    entry: Literal["finding", "effort", "critic", "red_team"]
    id: str
    agent: str
    agent_label: str
    assessment_id: str
    version: int = Field(ge=1)
    title: str
    detail: str
    severity: str | None
    hours: float | None
    status: str | None
    created_at: datetime | None
    superseded: bool
    evidence: list[LineageEvidence]


class LineageDecision(BaseModel):
    """A human decision behind the line: a Conflict resolution that set its hours
    (`conflict_resolved`), or the override or resolution of a Finding in its lineage
    (`finding_overridden`, `finding_resolved`), with the reason, who and when. `version`:
    the Estimate Version number (a Conflict) or the Review version (a Finding);
    `superseded`: it was on a superseded Review."""

    kind: Literal["conflict_resolved", "finding_overridden", "finding_resolved"]
    subject_id: str
    title: str
    reason: str | None
    actor: LineageActor
    at: datetime
    version: int | None
    superseded: bool


class LineageAssumption(BaseModel):
    """A Contingency Assumption linked to the line: its register number, wording, hours,
    and who accepted it and when (null while unaccepted)."""

    id: str
    position: int = Field(ge=1)
    wording: str
    amount_hours: float | None
    accepted_by_name: str | None
    accepted_at: datetime | None
    version: int = Field(ge=1)
    superseded: bool


class LineageEdit(BaseModel):
    """A person's edit of the line, or of the line on an earlier version it was carried from
    (`line_id`): the hours before and after, why, who and when. `version`: the Estimate
    Version number it was made on; `superseded`: a later edit replaced it."""

    line_id: str
    version: int = Field(ge=1)
    before_hours: float
    after_hours: float
    reason: str
    actor: LineageActor
    at: datetime
    superseded: bool


class LineageReview(BaseModel):
    """A Challenge targeting the line's version, or a Finding or Assessment in its lineage
    (`challenge`, `label` its status), or a Review Decision on the version or one of those
    Assessments (`review_decision`, `label` the decision), with the reason, who and when.
    `version`: the target's version; `superseded`: the target was superseded since."""

    kind: Literal["challenge", "review_decision"]
    id: str
    label: str
    target_kind: str
    target_id: str
    reason: str | None
    actor: LineageActor
    at: datetime
    version: int | None
    superseded: bool
    decline_reason: str | None = Field(
        default=None,
        description="A declined Challenge: the owner's reason for declining it.",
    )


class LineLineage(BaseModel):
    """Story 9.9 (`estimates.get_line_lineage`): what is behind an Estimate line, derived
    (nothing is stored): its Requirements, the Findings and effort entries of the version's
    assessment run, human decisions, its Contingencies, its edits (and its carried
    predecessors') and the reviews of its version. Empty sections are empty lists."""

    line_id: str
    title: str
    section: Section
    version_id: str
    version: int = Field(ge=1)
    source: VersionSource
    requirements: list[LineageRequirement]
    findings: list[LineageFinding]
    decisions: list[LineageDecision]
    assumptions: list[LineageAssumption]
    edits: list[LineageEdit]
    reviews: list[LineageReview]


class LineagePassage(BaseModel):
    """A Source passage, as the answer step cites it."""

    passage_id: str
    source_id: str
    source_version: int = Field(ge=1)
    filename: str
    label: str
    excerpt: str


LineageStepKind = Literal[
    "gap", "unknown", "finding", "question", "answer", "conversion", "acceptance"
]


class LineageStep(BaseModel):
    """One step of an Assumption's chain of origin. `title`: the Gap's or Finding's title,
    the question's text, the answer's Source, the conversion or the acceptance; `detail`:
    why it matters, the answer date and so on. `actor` and `at`: who and when (null when
    not recorded). `version`: the Gap's row version the Assumption was made from, or the
    Assessment's; `superseded`: the origin moved on since the Assumption was made from it."""

    kind: LineageStepKind
    id: str
    title: str
    detail: str | None
    actor: LineageActor | None
    at: datetime | None
    version: int | None
    superseded: bool
    evidence: list[LineageEvidence] = Field(default_factory=list)
    passage: LineagePassage | None = None


class AssumptionLineage(BaseModel):
    """Story 9.9 (`estimates.get_assumption_lineage`): an Assumption's chain, oldest first:
    its origin (a Gap, an Unknown or a Finding), the Clarification Question, the recorded
    answer with its Source passage, the conversion and the acceptance. A step that never
    happened (or a question a sales representative may not see) is left out."""

    assumption_id: str
    version_id: str
    version: int = Field(ge=1)
    kind: AssumptionKind
    wording: str
    steps: list[LineageStep]


class ItemDiff(BaseModel):
    """An Assumption or Risk that differs between two versions, matched by its origin (else
    its wording): `added`, `removed` or `changed`, with a one-line summary of each side."""

    change: Literal["added", "removed", "changed"]
    id: str
    text: str
    before: str | None
    after: str | None


class WhySubject(BaseModel):
    """What a trace event is about, as stored."""

    type: str
    id: str
    version: int | None


class WhyEvent(BaseModel):
    """A trace event between the two versions that explains a change: its type and label,
    who and when, the reason given (null when none) and its subject."""

    id: str
    event_type: str
    label: str
    actor: LineageActor
    occurred_at: datetime
    reason: str | None
    subject: WhySubject


class VersionComparison(BaseModel):
    """Story 9.9 (`estimates.compare_any`): any two Estimate Versions of the Opportunity,
    `from_version` (the base) against `to_version`: the line diffs (as `compare_versions`),
    each side's total and the delta, the Assumptions and Risks added, removed or changed,
    and `why`: the trace events between the older version's and the newer version's
    creation that explain the change, oldest first."""

    from_version: int = Field(ge=1)
    from_version_id: str
    to_version: int = Field(ge=1)
    to_version_id: str
    lines: list[LineDiff]
    total_before: float
    total_after: float
    total_delta: float
    assumptions: list[ItemDiff]
    risks: list[ItemDiff]
    why: list[WhyEvent]
