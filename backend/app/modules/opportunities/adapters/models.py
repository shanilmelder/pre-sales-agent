"""The opportunities module's tables. `owner_id` and `user_id` hold identity user ids
without foreign keys: modules never reference each other's tables (AD-2)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base


class OpportunityRow(RowVersioned, Base):
    __tablename__ = "opportunities_opportunities"
    __table_args__ = (Index(None, "owner_id"), Index(None, "created_at", "id"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    customer_name: Mapped[str] = mapped_column(Text)
    products: Mapped[list[str]] = mapped_column(ARRAY(Text))
    industry: Mapped[str] = mapped_column(Text)
    target_proposal_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class CollaboratorRow(Base):
    __tablename__ = "opportunities_collaborators"
    __table_args__ = (Index(None, "user_id"),)

    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "opportunities_opportunities.id",
            ondelete="CASCADE",
            # The convention's name would pass Postgres' 63-character limit.
            name="fk_opportunities_collaborators_opportunity_id",
        ),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ImportRow(Base):
    """An Opportunity import (Story 1.7, import from file): one uploaded file, stored in
    `platform.storage` (`file_sha256`), and the field suggestions the worker read from it.
    `error_code` is set only when `failed`; `consumed_at` once an Opportunity was created
    from it (single use)."""

    __tablename__ = "opportunities_imports"
    __table_args__ = (
        Index(None, "uploaded_by", "created_at"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('unreadable', 'model_unavailable', 'model_timeout', 'output_invalid')",
            name="error_code",
        ),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
        CheckConstraint("size_bytes > 0", name="size_bytes"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    file_sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    suggestions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
