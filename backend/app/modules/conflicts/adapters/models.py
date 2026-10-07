"""The conflicts module's tables (Story 6.1). `opportunity_id`, `run_id`, `assessment_id`,
`estimate_version_id` and `requirement_id` hold ids owned by other modules without foreign
keys (AD-2)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")
TYPES = (
    "('timeline', 'effort', 'resource', 'architecture', 'security', 'scope', 'assumption', "
    "'evidence')"
)


class ConflictRow(Base):
    """A Conflict between Assessments (and the Estimate), raised once per run, detection pass
    (1, then 2, … each time the run finishes again after a task retry) and fingerprint.
    Inserted `open`; the system resolves it (`resolution_reason`, `resolved_at`) when a later
    run no longer raises it or raises it again (the newer one links it through
    `previous_conflict_id`). `row_version` counts its changes."""

    __tablename__ = "conflicts_conflicts"
    __table_args__ = (
        UniqueConstraint("run_id", "detection_pass", "fingerprint"),
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint(f"type IN {TYPES}", name="type"),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint(
            "status IN ('open', 'negotiating', 'resolved', 'escalated')", name="status"
        ),
        CheckConstraint(
            "detected_by IN ('rule', 'semantic', 'critic', 'red_team')", name="detected_by"
        ),
        CheckConstraint("(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_at"),
        CheckConstraint(
            "(resolved_at IS NULL) = (resolution_reason IS NULL)", name="resolution_reason"
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
        CheckConstraint("detection_pass >= 1", name="detection_pass"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    detected_by: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    previous_conflict_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conflicts_conflicts.id", name="fk_conflicts_conflicts_previous_conflict_id"),
        index=True,
    )
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detection_pass: Mapped[int] = mapped_column(Integer)
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class PositionRow(Base):
    """One side of a Conflict: an agent's Assessment (with its version) or the Estimate
    Version, a short summary, an hours value (or none) and the Requirement it is about.
    Insert-only."""

    __tablename__ = "conflicts_positions"
    __table_args__ = (
        CheckConstraint("source IN ('assessment', 'estimate')", name="source"),
        CheckConstraint(
            "(source = 'assessment') = (assessment_id IS NOT NULL AND assessment_version IS "
            "NOT NULL AND agent IS NOT NULL)",
            name="assessment_ref",
        ),
        CheckConstraint(
            "(source = 'estimate') = (estimate_version_id IS NOT NULL AND estimate_version IS "
            "NOT NULL)",
            name="estimate_ref",
        ),
        CheckConstraint("source = 'assessment' OR agent IS NULL", name="estimate_has_no_agent"),
        CheckConstraint(
            "(requirement_id IS NULL) = (requirement_version IS NULL)", name="requirement_ref"
        ),
        CheckConstraint("position >= 1", name="position"),
    )

    conflict_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "conflicts_conflicts.id",
            ondelete="CASCADE",
            name="fk_conflicts_positions_conflict_id",
        ),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    assessment_id: Mapped[UUID | None] = mapped_column(Uuid)
    assessment_version: Mapped[int | None] = mapped_column(Integer)
    estimate_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    estimate_version: Mapped[int | None] = mapped_column(Integer)
    agent: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    requirement_id: Mapped[UUID | None] = mapped_column(Uuid)
    requirement_version: Mapped[int | None] = mapped_column(Integer)
