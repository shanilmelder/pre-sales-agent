"""The assessments module's tables: Red Team Reviews (Story 6.5) and specialist Assessments
(Epic 5 slice 5A). `opportunity_id`, `estimate_version_id`, `requirement_id` and `line_id`
hold ids owned by other modules without foreign keys (AD-2)."""

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
    PrimaryKeyConstraint,
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


# --- specialist Assessments (Epic 5 slice 5A) ----------------------------------------------

_AGENTS = "('engineering_agent', 'pm_agent', 'security_agent')"
_ERROR_CODES = "('model_unavailable', 'model_timeout', 'output_invalid')"
_SEVERITIES = "('low', 'medium', 'high', 'critical')"


class AssessmentRunRow(Base):
    """One assessment run of an Opportunity: one task per specialist agent. Inserted
    `queued` with its job; its status follows its tasks'. `queued_at`: when it was last
    queued (a task retry queues it again); staleness counts from there."""

    __tablename__ = "assessments_runs"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed')",
            name="status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssessmentTaskRow(Base):
    """One agent's task in an assessment run. `error_code` is set only when `failed`."""

    __tablename__ = "assessments_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "agent"),
        CheckConstraint(f"agent IN {_AGENTS}", name="agent"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(f"error_code IS NULL OR error_code IN {_ERROR_CODES}", name="error_code"),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("assessments_runs.id", ondelete="CASCADE", name="fk_assessments_tasks_run_id"),
    )
    agent: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssessmentRow(Base):
    """A specialist agent's Assessment of an Opportunity. A succeeded task inserts a
    `current` one numbered one past the agent's latest, and marks the earlier `current` one
    `superseded`. At most one `current` per Opportunity and agent."""

    __tablename__ = "assessments_assessments"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "agent", "version", name="uq_assessments_assessments_version"
        ),
        Index(
            "uq_assessments_assessments_one_current",
            "opportunity_id",
            "agent",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
        CheckConstraint(f"agent IN {_AGENTS}", name="agent"),
        CheckConstraint("status IN ('current', 'superseded')", name="status"),
        CheckConstraint(
            "recommendation IN ('proceed', 'proceed_with_conditions', 'do_not_proceed')",
            name="recommendation",
        ),
        CheckConstraint("confidence IN ('high', 'medium', 'low')", name="confidence"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("dropped_count >= 0", name="dropped_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    agent: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assessments_runs.id", name="fk_assessments_assessments_run_id")
    )
    status: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    confidence_basis: Mapped[str] = mapped_column(Text)
    dropped_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class AssessmentFindingRow(Base):
    """A Finding of an Assessment. Insert-only."""

    __tablename__ = "assessments_assessment_findings"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "position", name="uq_assessments_assessment_findings_position"
        ),
        CheckConstraint("kind IN ('risk', 'constraint', 'dependency', 'opportunity')", name="kind"),
        CheckConstraint(f"severity IN {_SEVERITIES}", name="severity"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessments.id",
            ondelete="CASCADE",
            name="fk_assessments_assessment_findings_assessment_id",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)


class AssessmentFindingRequirementRow(Base):
    """An Assessment Finding cites a Requirement at a version. Insert-only."""

    __tablename__ = "assessments_assessment_finding_requirements"
    __table_args__ = (
        # The default names would pass PostgreSQL's 63-character limit.
        PrimaryKeyConstraint(
            "finding_id", "requirement_id", name="pk_assessments_assessment_finding_reqs"
        ),
    )

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessment_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_assessment_finding_reqs_finding_id",
        ),
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid)
    requirement_version: Mapped[int] = mapped_column(Integer)


class AssessmentEffortRow(Base):
    """An Assessment's effort for one Requirement (at a version), in person-hours to 0.1 h.
    Insert-only."""

    __tablename__ = "assessments_effort"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "requirement_id", name="uq_assessments_effort_requirement"
        ),
        CheckConstraint("hours >= 0.5 AND hours <= 2000", name="hours"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessments.id",
            ondelete="CASCADE",
            name="fk_assessments_effort_assessment_id",
        ),
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid)
    requirement_version: Mapped[int] = mapped_column(Integer)
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    basis: Mapped[str] = mapped_column(Text)
