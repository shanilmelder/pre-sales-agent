"""The reviews module's tables (Stories 9.1 and 9.3). No cross-module foreign keys (AD-2):
`opportunity_id`, `target_id`, `estimate_version_id`, `reviewer_id`, `requested_by`,
`decided_by` and `escalated_to` hold ids owned by other modules. Decisions reference their
Review Request (an in-module foreign key)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")


class ReviewRequestRow(Base):
    """A Review Request: one named reviewer asked to review one target (an Estimate Version,
    or one of its Assessments at `target_version`) for one review type, counting towards
    `estimate_version_id`. Inserted `pending`; only its status (and a cancel's reason) ever
    changes, bumping `row_version`. Never deleted."""

    __tablename__ = "reviews_review_requests"
    __table_args__ = (
        Index(None, "opportunity_id"),
        Index(None, "estimate_version_id"),
        Index(None, "reviewer_id"),
        Index(
            "uq_reviews_review_requests_one_pending",
            "reviewer_id",
            "review_type",
            "target_kind",
            "target_id",
            "target_version",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint("review_type IN ('engineering', 'pm', 'security')", name="review_type"),
        CheckConstraint("target_kind IN ('estimate_version', 'assessment')", name="target_kind"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'challenged', 'superseded', "
            "'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancelled_has_reason"
        ),
        CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="message"),
        CheckConstraint("target_version >= 1", name="target_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    review_type: Mapped[str] = mapped_column(Text)
    target_kind: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID] = mapped_column(Uuid)
    target_version: Mapped[int] = mapped_column(Integer)
    estimate_version_id: Mapped[UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid)
    requested_by: Mapped[UUID] = mapped_column(Uuid)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ReviewDecisionRow(Base):
    """A Review Decision (Story 9.3): what the request's reviewer decided, why, on which
    version of the target, and (for an escalation) who the request went to. Append-only:
    `psa_app` may only SELECT and INSERT."""

    __tablename__ = "reviews_review_decisions"
    __table_args__ = (
        Index(None, "review_request_id", "decided_at"),
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'challenged', 'evidence_requested', "
            "'alternative_requested', 'escalated')",
            name="decision",
        ),
        CheckConstraint(
            "decision = 'approved' OR (reason IS NOT NULL AND char_length(btrim(reason)) >= 1)",
            name="reason_required",
        ),
        CheckConstraint("reason IS NULL OR char_length(reason) <= 1000", name="reason"),
        CheckConstraint(
            "(decision = 'escalated') = (escalated_to IS NOT NULL)", name="escalated_has_target"
        ),
        CheckConstraint("target_version >= 1", name="target_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    review_request_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "reviews_review_requests.id", name="fk_reviews_review_decisions_review_request_id"
        ),
    )
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[UUID] = mapped_column(Uuid)
    target_version: Mapped[int] = mapped_column(Integer)
    escalated_to: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
