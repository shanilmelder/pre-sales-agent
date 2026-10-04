"""The estimates module's tables (Story 8.1). `opportunity_id` and `requirement_id` hold ids
owned by other modules without foreign keys (AD-2)."""

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
    `draft` per Opportunity."""

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
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(Text)
    uncovered_count: Mapped[int] = mapped_column(Integer)
    dropped_count: Mapped[int] = mapped_column(Integer)
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
