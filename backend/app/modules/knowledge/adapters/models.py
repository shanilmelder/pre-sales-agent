"""The knowledge module's tables: the catalogue (Story 3.1), Knowledge Sources (3.2) and
their chunks and embedding state (3.3), AD-2."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
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
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
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


# --- chunks and embeddings (Story 3.3) -------------------------------------------------------


class SourceEmbedRow(Base):
    """The embedding state of one Source version: `queued`, `embedding`, `ready` (with
    `chunk_count` and the embedding profile `model`) or `failed` (with an `error_code`).
    Inserted `queued` when the version's parse succeeds; absent for versions parsed before
    Story 3.3 (they show an Embed action)."""

    __tablename__ = "knowledge_source_embeds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "version"],
            ["knowledge_source_versions.source_id", "knowledge_source_versions.version"],
        ),
        CheckConstraint("status IN ('queued', 'embedding', 'ready', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN ('model_unavailable', 'model_timeout', "
            "'model_bad_output', 'text_missing', 'internal_error')",
            name="error_code",
        ),
        CheckConstraint(
            "(status = 'ready') = (chunk_count IS NOT NULL AND model IS NOT NULL)",
            name="ready_has_chunks",
        ),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    source_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ChunkRow(Base):
    """One chunk of a Source version's extracted text, with its embedding (AD-14). `text` is
    exactly `extracted_text[start_offset:end_offset]` (Unicode code points). The product,
    product version and Integration Type ids are copied at embedding time. `embedding` is an
    untyped `vector`; each embedding model has its own partial HNSW expression index (see
    migration 0035). Insert-only: a later version's chunks never replace an earlier one's."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "version"],
            ["knowledge_source_versions.source_id", "knowledge_source_versions.version"],
        ),
        UniqueConstraint("source_id", "version", "embedding_model", "ordinal"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="offsets"),
        CheckConstraint("ordinal >= 0", name="ordinal"),
        CheckConstraint(
            "embedding_dims >= 1 AND vector_dims(embedding) = embedding_dims", name="dims"
        ),
        Index(
            "ix_knowledge_chunks_embedding_bge_m3",
            text("(embedding::vector(1024)) vector_cosine_ops"),
            postgresql_using="hnsw",
            postgresql_where=text("embedding_model = 'bge-m3'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    product: Mapped[str] = mapped_column(Text)
    product_version: Mapped[str] = mapped_column(Text)
    integration_type_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    embedding_model: Mapped[str] = mapped_column(Text)
    embedding_dims: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(VECTOR())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
