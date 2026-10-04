"""The assessments module's tables (Story 6.5). `opportunity_id`, `estimate_version_id`,
`requirement_id` and `line_id` hold ids owned by other modules without foreign keys (AD-2)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")


class RedTeamRunRow(Base):
    """One run of `assessments.red_team_review` for an Opportunity. Inserted `queued` with its
    job; `error_code` is set only when `failed`."""

    __tablename__ = "assessments_red_team_runs"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid')",
            name="error_code",
        ),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewRow(Base):
    """A Review of an Opportunity (`kind` `red_team` in Story 6.5). An accepted run inserts a
    `current` review numbered one past the latest of its kind, and marks the earlier
    `current` one `superseded`. At most one `current` per Opportunity and kind.
    `estimate_version_id`: the Estimate Version reviewed (null when there was none)."""

    __tablename__ = "assessments_reviews"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "kind", "version"),
        Index(
            "uq_assessments_reviews_one_current",
            "opportunity_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
        CheckConstraint("kind IN ('red_team')", name="kind"),
        CheckConstraint("status IN ('current', 'superseded')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("dropped_count >= 0", name="dropped_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    estimate_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    dropped_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class FindingRow(Base):
    """A Finding of a Review. Insert-only (no resolving or overriding in Story 6.5)."""

    __tablename__ = "assessments_findings"
    __table_args__ = (
        UniqueConstraint("review_id", "position"),
        CheckConstraint(
            "category IN ('integration_harder', 'requirement_incomplete', "
            "'capability_overstated', 'hidden_dependency')",
            name="category",
        ),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    review_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_reviews.id", ondelete="CASCADE", name="fk_assessments_findings_review_id"
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    argument: Mapped[str] = mapped_column(Text)


class FindingRequirementRow(Base):
    """A Finding challenges a Requirement at a version. Insert-only."""

    __tablename__ = "assessments_finding_requirements"

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_requirements_finding_id",
        ),
        primary_key=True,
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class FindingLineRow(Base):
    """A Finding challenges a line of the reviewed Estimate Version. Insert-only."""

    __tablename__ = "assessments_finding_lines"

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_lines_finding_id",
        ),
        primary_key=True,
    )
    line_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
