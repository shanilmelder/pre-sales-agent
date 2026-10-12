"""Read models for the Conflicts tab (Story 6.1)."""

from datetime import datetime

from pydantic import BaseModel, Field

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


class ConflictPosition(BaseModel):
    """One side of a Conflict. From an agent's Assessment (`agent`, `assessment_id`,
    `assessment_version`) or the Estimate (`estimate_version_id`, `estimate_version`).
    `summary`: e.g. "24 h", "Not sized", "Do not proceed". `value`: hours to 0.1, or null."""

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


class ConflictView(BaseModel):
    """A Conflict with its positions in order. `requirement`: the Requirement it is about
    (null for an Opportunity-level Conflict)."""

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


class ConflictsView(BaseModel):
    """The Opportunity's Conflicts: open (and negotiating, escalated) before resolved, then
    critical to low, then newest first; those carried forward to a later run are left out.
    `open_count`: open plus escalated."""

    conflicts: list[ConflictView]
    open_count: int = Field(ge=0)


class OpenConflict(BaseModel):
    """An open or escalated Conflict, for other modules (e.g. submission blockers)."""

    id: str
    type: ConflictType
    severity: ConflictSeverity
    status: ConflictStatus
    summary: str
