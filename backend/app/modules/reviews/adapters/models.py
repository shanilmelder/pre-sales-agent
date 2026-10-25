"""The reviews module's tables (Story 9.1). `opportunity_id`, `target_id`,
`estimate_version_id`, `reviewer_id` and `requested_by` hold ids owned by other modules
without foreign keys (AD-2)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, Uuid, text
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
