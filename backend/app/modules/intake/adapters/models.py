"""The intake module's tables (Stories 2.1, 2.2, 2.5). `opportunity_id`, `created_by` and
`uploaded_by` hold ids owned by other modules without foreign keys (AD-2); `file_sha256` and
`text_sha256` name blobs in `platform.storage` (metadata rows in `platform_files`)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


# --- Requirements (Story 2.5 Part A) -------------------------------------------------------

_NOW = text("now()")
"""`RequirementRow` has a `text` column, which shadows `text()` inside its class body."""


class ExtractionRow(Base):
    """One run of `intake.extract_requirements` for an Opportunity. Inserted `queued` with
    its job; `error_code` is set only when `failed`. Counts are set when it finishes."""

    __tablename__ = "intake_extractions"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid', 'input_too_large')",
            name="error_code",
        ),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    requirement_count: Mapped[int | None] = mapped_column(Integer)
    dropped_count: Mapped[int | None] = mapped_column(Integer)
    source_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourcePassageRow(Base):
    """A cited span of a Source version's extracted text: Unicode code-point offsets
    `[start, end)`. Immutable (`psa_app` has no UPDATE or DELETE), and one row per span."""

    __tablename__ = "intake_source_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_version"],
            ["intake_source_versions.source_id", "intake_source_versions.version"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("source_id", "source_version", "start", "end"),
        CheckConstraint('start >= 0 AND "end" > start', name="span"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    source_version: Mapped[int] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class RequirementRow(RowVersioned, Base):
    """A Requirement of an Opportunity. Extraction inserts `active`, `extracted`, unlocked
    rows at version 1, and a later extraction marks them `superseded`; a human-locked one
    (Story 2.6) is never touched by extraction."""

    __tablename__ = "intake_requirements"
    __table_args__ = (
        Index(None, "opportunity_id", "status"),
        CheckConstraint(
            "classification IN ('functional', 'integration', 'data', 'security', "
            "'non_functional', 'commercial')",
            name="classification",
        ),
        CheckConstraint("origin IN ('extracted', 'human')", name="origin"),
        CheckConstraint("status IN ('active', 'superseded')", name="status"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    text: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    locked_by_human: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    extraction_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("intake_extractions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class RequirementEvidenceRow(Base):
    """A Requirement cites a Source passage. Insert-only."""

    __tablename__ = "intake_requirement_evidence"
    __table_args__ = (Index(None, "passage_id"),)

    # Named explicitly: the naming convention's names are longer than Postgres's 63.
    requirement_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "intake_requirements.id",
            ondelete="CASCADE",
            name="fk_intake_requirement_evidence_requirement_id",
        ),
        primary_key=True,
    )
    passage_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "intake_source_passages.id",
            ondelete="CASCADE",
            name="fk_intake_requirement_evidence_passage_id",
        ),
        primary_key=True,
    )
