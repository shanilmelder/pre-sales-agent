"""The gaps module's tables (Story 4.3). `opportunity_id` and `requirement_id` hold ids owned
by other modules without foreign keys (AD-2)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base

_NOW = text("now()")
_FALSE = text("false")
"""`QuestionRow` has a `text` column, which shadows `text()` inside its class body."""


class DetectionRow(Base):
    """One run of `gaps.detect_gaps` for an Opportunity. Inserted `queued` with its job;
    `error_code` is set only when `failed`. Counts are set when it succeeds."""

    __tablename__ = "gaps_detections"
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
    gap_count: Mapped[int | None] = mapped_column(Integer)
    dropped_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GapRow(RowVersioned, Base):
    """A Gap of an Opportunity. Detection inserts `open`, `detected` Gaps, and a later
    detection marks them `superseded`. Accepting an Assumption made from an `open` Gap marks it
    `converted`, recording the Assumption's kind in `converted_to` (Story 8.4)."""

    __tablename__ = "gaps_gaps"
    __table_args__ = (
        Index(None, "opportunity_id", "status"),
        CheckConstraint(
            "category IN ('data_volumes', 'versions_and_platforms', 'integration_details', "
            "'security_and_compliance', 'non_functional', 'scope_and_ownership', "
            "'commercial', 'other')",
            name="category",
        ),
        CheckConstraint("impact IN ('high', 'medium', 'low')", name="impact"),
        CheckConstraint("origin IN ('detected')", name="origin"),
        CheckConstraint("status IN ('open', 'superseded', 'converted')", name="status"),
        CheckConstraint(
            "converted_to IS NULL OR converted_to IN ('condition', 'contingency')",
            name="converted_to",
        ),
        CheckConstraint(
            "(status = 'converted') = (converted_to IS NOT NULL)", name="converted_has_kind"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB)
    why_it_matters: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    impact_basis: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    detection_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("gaps_detections.id"))
    converted_to: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class GapRequirementRow(Base):
    """A Gap relates to a Requirement at a version. Insert-only."""

    __tablename__ = "gaps_gap_requirements"

    gap_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("gaps_gaps.id", ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class QuestionRow(RowVersioned, Base):
    """The Clarification Question drafted for a Gap (one per Gap in the demo). Story 4.5: a
    person may edit its text and topic (`edited_by_human`) and approve it (`approved_by` /
    `approved_at`, set only while `approved`); editing an approved question returns it to
    `drafted`. `changed_by`: the person behind its latest edit or approval."""

    __tablename__ = "gaps_clarification_questions"
    __table_args__ = (
        CheckConstraint("status IN ('drafted', 'approved', 'superseded')", name="status"),
        CheckConstraint("(approved_at IS NULL) = (approved_by IS NULL)", name="approved_has_by"),
        CheckConstraint(
            "(status = 'approved') = (approved_by IS NOT NULL)", name="approved_iff_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    gap_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("gaps_gaps.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW
    )
    approved_by: Mapped[UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_by_human: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)
