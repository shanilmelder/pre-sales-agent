"""The estimates module's tables (Stories 8.1 and 8.4). `opportunity_id`, `requirement_id`
and an Assumption's origin Gap and `accepted_by` hold ids owned by other modules without
foreign keys (AD-2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base

_NOW = text("now()")


class DraftRow(Base):
    """One run of `estimates.draft_estimate` for an Opportunity. Inserted `queued` with its
    job; `error_code` is set only when `failed`."""

    __tablename__ = "estimates_drafts"
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


class EstimateVersionRow(RowVersioned, Base):
    """An Estimate Version of an Opportunity. An accepted draft inserts a `draft` version
    numbered one past the latest, and marks the earlier `draft` `superseded`. At most one
    `draft` per Opportunity. `proposal_status` is the state of its Assumption proposals
    (Story 8.4); null for a version that never had them queued."""

    __tablename__ = "estimates_estimate_versions"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version"),
        Index(
            "uq_estimates_estimate_versions_one_draft",
            "opportunity_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        CheckConstraint("status IN ('draft', 'superseded')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("uncovered_count >= 0 AND dropped_count >= 0", name="counts"),
        CheckConstraint(
            "proposal_status IS NULL OR proposal_status IN "
            "('queued', 'running', 'succeeded', 'failed')",
            name="proposal_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(Text)
    uncovered_count: Mapped[int] = mapped_column(Integer)
    dropped_count: Mapped[int] = mapped_column(Integer)
    proposal_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class EstimateLineRow(Base):
    """A work item of an Estimate Version. Insert-only in the demo (no inline editing)."""

    __tablename__ = "estimates_estimate_lines"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        CheckConstraint(
            "section IN ('functional', 'integration', 'data', 'security', 'non_functional', "
            "'commercial')",
            name="section",
        ),
        CheckConstraint("effort_hours >= 0", name="effort_hours"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        Uuid,
        # Named explicitly: the convention's name would pass Postgres' 63-character limit.
        ForeignKey(
            "estimates_estimate_versions.id",
            ondelete="CASCADE",
            name="fk_estimates_estimate_lines_version_id",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    effort_hours: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    role_mix: Mapped[dict[str, Any]] = mapped_column(JSONB)
    basis: Mapped[str] = mapped_column(Text)


class LineRequirementRow(Base):
    """A line covers a Requirement at a version. Insert-only."""

    __tablename__ = "estimates_line_requirements"

    line_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_lines.id",
            ondelete="CASCADE",
            name="fk_estimates_line_requirements_line_id",
        ),
        primary_key=True,
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class AssumptionRow(RowVersioned, Base):
    """An Assumption of an Estimate Version (Story 8.4): a `condition` (no hours) or a
    `contingency` (hours, optionally linked to one of the version's lines), made from one
    origin (`origin_ref`: `{kind: "gap", id, row_version}`). Inserted unaccepted; accepting
    sets `accepted_by` and `accepted_at` together. `position` keeps the proposal order.
    `carried_from` (Story 8.7): the accepted Assumption of the superseded version this one
    was copied from by a re-draft, null for a proposal."""

    __tablename__ = "estimates_assumptions"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        CheckConstraint("kind IN ('condition', 'contingency')", name="kind"),
        CheckConstraint(
            "(kind = 'contingency') = (amount_hours IS NOT NULL)", name="contingency_has_hours"
        ),
        CheckConstraint("amount_hours IS NULL OR amount_hours > 0", name="amount_hours"),
        CheckConstraint("kind = 'contingency' OR line_id IS NULL", name="condition_has_no_line"),
        CheckConstraint("(accepted_by IS NULL) = (accepted_at IS NULL)", name="accepted_has_by"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_versions.id",
            ondelete="CASCADE",
            name="fk_estimates_assumptions_version_id",
        ),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    wording: Mapped[str] = mapped_column(Text)
    amount_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    line_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_lines.id",
            ondelete="CASCADE",
            name="fk_estimates_assumptions_line_id",
        ),
    )
    origin_ref: Mapped[dict[str, Any]] = mapped_column(JSONB)
    accepted_by: Mapped[UUID | None] = mapped_column(Uuid)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    carried_from: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_assumptions.id",
            ondelete="SET NULL",
            name="fk_estimates_assumptions_carried_from",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
