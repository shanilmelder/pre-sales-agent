"""The intake module's tables (Story 2.1). `opportunity_id`, `created_by` and `uploaded_by`
hold ids owned by other modules without foreign keys (AD-2); `file_sha256` names a blob in
`platform.storage` (its metadata row is `platform_files`)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base


class SourceRow(RowVersioned, Base):
    """An Opportunity Source. Its content lives in its versions."""

    __tablename__ = "intake_sources"
    __table_args__ = (Index(None, "opportunity_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SourceVersionRow(Base):
    """One uploaded file of a Source. Immutable."""

    __tablename__ = "intake_source_versions"
    __table_args__ = (Index(None, "file_sha256"),)

    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("intake_sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_sha256: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
