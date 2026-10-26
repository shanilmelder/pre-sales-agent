"""The notifications module's table (Story 9.2). `recipient_id`, `opportunity_id` and
`subject_id` hold ids owned by other modules without foreign keys (AD-2)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")
KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated', 'review_outcome', 'review_replied', 'challenge_raised', "
    "'challenge_declined')"
)


class NotificationRow(Base):
    """An Inbox item for one recipient. Inserted once per `dedupe_key`; only `read_at`
    ever changes. Never deleted."""

    __tablename__ = "notifications_notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index(None, "recipient_id", "read_at", "created_at"),
        CheckConstraint(f"kind IN {KINDS}", name="kind"),
        CheckConstraint("channel IN ('in_app')", name="channel"),
        CheckConstraint("char_length(summary) <= 300", name="summary"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    recipient_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    subject_version: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, server_default=text("'in_app'"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
