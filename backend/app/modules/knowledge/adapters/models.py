"""The knowledge module's tables: the catalogue (Story 3.1) and Knowledge Sources (3.2), AD-2."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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


# --- Knowledge Sources (Story 3.2) ----------------------------------------------------------
# `owner_id`, `created_by` and `uploaded_by` hold ids owned by identity without foreign keys
# (AD-2); `file_sha256` and `text_sha256` name blobs in `platform.storage`.


class SourceRow(RowVersioned, Base):
    """A Knowledge Source's mutable header: title, product, owner, last-reviewed date and
    status. Its files live in the immutable version rows; its Integration Type tags in
    `knowledge_source_tags`. `retired_reason` is set exactly when `retired`."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index(None, "status", "last_reviewed_on"),
        Index(None, "owner_id"),
        CheckConstraint("status IN ('active', 'retired')", name="status"),
        CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)", name="retired_has_reason"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    product: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    retired_reason: Mapped[str | None] = mapped_column(Text)
    last_reviewed_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SourceTagRow(Base):
    """One Integration Type tag of a Source (a catalogue entry). Retagging replaces the set."""

    __tablename__ = "knowledge_source_tags"

    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_sources.id"), primary_key=True
    )
    entry_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_catalogue_entries.id"), primary_key=True
    )


class SourceVersionRow(Base):
    """One uploaded file of a Source, with the product version it documents. Insert-only."""

    __tablename__ = "knowledge_source_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="version"), Index(None, "file_sha256"))

    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_sources.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_version: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SourceParseRow(Base):
    """The parse state of one Source version: `queued`, `parsing`, `parsed` (with the
    extracted-text blob's `text_sha256`, `char_count` and `parser`) or `failed` (with an
    `error_code`). Inserted `queued` with the version."""

    __tablename__ = "knowledge_source_parses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "version"],
            ["knowledge_source_versions.source_id", "knowledge_source_versions.version"],
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
