"""Read models for the Conflicts tab (Story 6.1) and the decisions on it (Story 6.3)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    DetectedBy,
    PositionSource,
)


class ConflictRequirement(BaseModel):
    """The Requirement a position is about, at the version it names. `label` is `R<n>`, its
    position among the Opportunity's active Requirements (oldest first), or `Superseded` once
    it is no longer active. `excerpt`: up to 140 characters of that version's text, with `…`
    when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class ConflictFinding(BaseModel):
    """The Assessment Finding a semantic Conflict's position cites (Story 6.2): its id,
    title and kind (`risk`, `constraint`, `dependency`, `opportunity`)."""

    id: str
    title: str
    kind: str


class ConflictPosition(BaseModel):
    """One side of a Conflict. From an agent's Assessment (`agent`, `assessment_id`,
    `assessment_version`) or the Estimate (`estimate_version_id`, `estimate_version`).
    `summary`: e.g. "24 h", "Not sized", "Do not proceed", or for a semantic Conflict the
    cited Finding's stance. `value`: hours to 0.1, or null. `finding`: the cited Finding
    (semantic Conflicts only, Story 6.2), else null."""

    position: int = Field(ge=1)
    source: PositionSource
    agent: str | None
    assessment_id: str | None
    assessment_version: int | None
    estimate_version_id: str | None
    estimate_version: int | None
    summary: str
    value: float | None
    requirement: ConflictRequirement | None
    finding: ConflictFinding | None


class Person(BaseModel):
    """A user by id and name."""

    id: str
    name: str


class PreviousDecision(BaseModel):
    """Story 6.3: who resolved an earlier Conflict with this fingerprint, and when, before
    the positions changed and it was raised again."""

    name: str
    resolved_at: datetime


class ConflictView(BaseModel):
    """A Conflict with its positions in order. `requirement`: the Requirement it is about
    (null for an Opportunity-level Conflict). `row_version`: for `If-Match` on a resolution
    or escalation.

    Story 6.3, a person's decision: `resolved_by_name` (null when the system resolved it),
    `chosen_position` (a position number) or `entered_position`, `applied_hours` (the hours
    an `effort` decision set on the Estimate line) or `not_applied` (why it set none:
    `no_line`, `shared_line`, `several_lines`). `previous_decision`: for a Conflict raised
    again after a person resolved it, who and when. An escalation: `escalated_to`,
    `escalated_by`, `escalation_reason`, `escalated_at`. `can_resolve` / `can_escalate`:
    whether the viewer may."""

    id: str
    type: ConflictType
    severity: ConflictSeverity
    status: ConflictStatus
    detected_by: DetectedBy
    summary: str
    run_id: str
    previous_conflict_id: str | None
    resolution_reason: str | None
    resolved_at: datetime | None
    created_at: datetime
    requirement: ConflictRequirement | None
    positions: list[ConflictPosition]
    row_version: int = Field(ge=1)
    resolved_by_name: str | None
    chosen_position: int | None
    entered_position: str | None
    applied_hours: float | None
    not_applied: str | None
    previous_decision: PreviousDecision | None
    escalated_to: Person | None
    escalated_by: Person | None
    escalation_reason: str | None
    escalated_at: datetime | None
    can_resolve: bool
    can_escalate: bool


class ConflictsView(BaseModel):
    """The Opportunity's Conflicts: open (and negotiating, escalated) before resolved, then
    critical to low, then newest first; those carried forward to a later run are left out
    (a Conflict a person resolved stays listed). `open_count`: open plus escalated.
    `reviewers`: who the viewer may escalate to (the Opportunity's owner and collaborators,
    without the viewer), by name."""

    conflicts: list[ConflictView]
    open_count: int = Field(ge=0)
    reviewers: list[Person]


class EnteredPosition(BaseModel):
    """A different position than the Conflict's own, in words (1-200 characters; for an
    `effort` Conflict, hours from 0 to 2,000 to 0.1 h, e.g. "48")."""

    model_config = ConfigDict(extra="forbid")

    entered: str


class ConflictResolution(BaseModel):
    """A person's decision: `choice` is one of the Conflict's position numbers or
    `{"entered": text}`; `reason` (1-1,000 characters) is required."""

    model_config = ConfigDict(extra="forbid")

    choice: Annotated[StrictInt, Field(ge=1)] | EnteredPosition
    reason: str


class ConflictEscalation(BaseModel):
    """Escalate to `reviewer_id` (the Opportunity's owner or a collaborator, not the caller)
    with a `reason` (1-1,000 characters)."""

    model_config = ConfigDict(extra="forbid")

    reviewer_id: UUID
    reason: str


class OpenConflict(BaseModel):
    """An open or escalated Conflict, for other modules (e.g. submission blockers)."""

    id: str
    type: ConflictType
    severity: ConflictSeverity
    status: ConflictStatus
    summary: str
