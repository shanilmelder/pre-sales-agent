"""The intake module's tables (Stories 2.1, 2.2). `opportunity_id`, `created_by` and
`uploaded_by` hold ids owned by other modules without foreign keys (AD-2); `file_sha256` and
`text_sha256` name blobs in `platform.storage` (metadata rows in `platform_files`)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
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


class SourceParseRow(RowVersioned, Base):
    """The parse state of one Source version (Story 2.2 Part B). Version rows are
    immutable, so their parse state lives here. Inserted `queued` with the version.
    `text_sha256` names the extracted-text blob in `platform.storage` once `parsed`."""

    __tablename__ = "intake_source_parses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "version"],
            ["intake_source_versions.source_id", "intake_source_versions.version"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('queued', 'parsing', 'parsed', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('unreadable', 'not_supported', 'no_text', 'timeout', 'too_large_output')",
            name="error_code",
        ),
        CheckConstraint("(status = 'parsed') = (text_sha256 IS NOT NULL)", name="parsed_has_text"),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    source_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    text_sha256: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int | None] = mapped_column(Integer)
    parser: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
