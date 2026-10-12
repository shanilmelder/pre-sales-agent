"""The knowledge module's catalogue tables (Story 3.1, AD-2)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base

_NOW = text("now()")


class CatalogueEntryRow(RowVersioned, Base):
    """An Integration Type or Work Package. `code` never changes; the name and definition
    live in the immutable version rows. `retired_reason` is set exactly when `retired`."""

    __tablename__ = "knowledge_catalogue_entries"
    __table_args__ = (
        Index(None, "kind", "status"),
        CheckConstraint("kind IN ('integration_type', 'work_package')", name="kind"),
        CheckConstraint("status IN ('active', 'retired')", name="status"),
        CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)", name="retired_has_reason"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    retired_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class CatalogueEntryVersionRow(Base):
    """One immutable version of an entry's name and definition. Insert-only."""

    __tablename__ = "knowledge_catalogue_entry_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="version"),)

    entry_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_catalogue_entries.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    definition: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[UUID] = mapped_column(Uuid)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
