"""The intake module's tables (Stories 2.1, 2.2, 2.5, 2.6, 2.7). `opportunity_id`, `created_by` and
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
from sqlalchemy.dialects.postgresql import ARRAY
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
            "('model_unavailable', 'model_timeout', 'output_invalid', 'input_too_large', "
            "'registry_agent_disabled')",
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
    rows at version 1; a later extraction that refines one moves it to its next version in
    place (Story 2.7). A human-locked one (Story 2.6) is never changed by extraction: it
    gets a pending change instead. A person may also create one, delete one (`deleted`, with
    a `removal_reason`), or split or merge them (the originals `superseded`).

    `number`: its stable `R<n>` within the Opportunity, never reused (Story 2.6)."""

    __tablename__ = "intake_requirements"
    __table_args__ = (
        Index(None, "opportunity_id", "status"),
        UniqueConstraint("opportunity_id", "number"),
        CheckConstraint(
            "classification IN ('functional', 'integration', 'data', 'security', "
            "'non_functional', 'commercial')",
            name="classification",
        ),
        CheckConstraint("origin IN ('extracted', 'human')", name="origin"),
        CheckConstraint("status IN ('active', 'superseded', 'deleted')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("(confirmed_at IS NULL) = (confirmed_by IS NULL)", name="confirmed_has_by"),
        CheckConstraint("number >= 1", name="number"),
        CheckConstraint(
            "(status = 'deleted') = (removal_reason IS NOT NULL)", name="deleted_has_reason"
        ),
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
    # Story 2.6: who confirmed the Requirement, and when (both or neither).
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid)
    number: Mapped[int] = mapped_column(Integer)
    removal_reason: Mapped[str | None] = mapped_column(Text)


class RequirementIntegrationTypeRow(Base):
    """One catalogue Integration Type a person tagged a Requirement with (Story 4.1).
    Human-owned: extraction never reads or writes it, and it is not versioned with the
    Requirement. Saving replaces the set (`psa_app` has no UPDATE). `entry_id` is a knowledge
    catalogue entry without a foreign key (AD-2); `tagged_by` a user's id."""

    __tablename__ = "intake_requirement_integration_types"
    __table_args__ = (Index(None, "entry_id"),)

    requirement_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "intake_requirements.id",
            ondelete="CASCADE",
            name="fk_intake_requirement_integration_types_requirement_id",
        ),
        primary_key=True,
    )
    entry_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tagged_by: Mapped[UUID] = mapped_column(Uuid)
    tagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class RequirementVersionRow(Base):
    """One version of a Requirement's text and classification (Story 2.6). Immutable
    (`psa_app` has no UPDATE or DELETE): extraction writes version 1, every human edit the
    next. `created_by` is the actor id: `intake_agent@<semver>` or a user's id."""

    __tablename__ = "intake_requirement_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="version"),)

    requirement_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "intake_requirements.id",
            ondelete="CASCADE",
            name="fk_intake_requirement_versions_requirement_id",
        ),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


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


class RequirementChangeRow(RowVersioned, Base):
    """A pending change to a human-locked Requirement (Story 2.7): what extraction (or, later,
    a Gap answer) proposes, against the Requirement's `base_version`. At most one `open` per
    Requirement; a newer proposal marks it `superseded`. A person accepts it (the next
    version) or rejects it with a `reason`. `passage_ids`: the passages it would add, sorted.
    `extraction_id`: the extraction that proposed it (null for other proposers)."""

    __tablename__ = "intake_requirement_changes"
    __table_args__ = (
        Index(
            "uq_intake_requirement_changes_one_open",
            "requirement_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        CheckConstraint("status IN ('open', 'accepted', 'rejected', 'superseded')", name="status"),
        CheckConstraint(
            "classification IN ('functional', 'integration', 'data', 'security', "
            "'non_functional', 'commercial')",
            name="classification",
        ),
        CheckConstraint("base_version >= 1", name="base_version"),
        CheckConstraint("(status = 'rejected') = (reason IS NOT NULL)", name="rejected_has_reason"),
        CheckConstraint(
            "(status IN ('accepted', 'rejected')) = (decided_by IS NOT NULL) "
            "AND (decided_by IS NULL) = (decided_at IS NULL)",
            name="decided_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "intake_requirements.id",
            ondelete="CASCADE",
            name="fk_intake_requirement_changes_requirement_id",
        ),
    )
    base_version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(Text)
    passage_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    extraction_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("intake_extractions.id", name="fk_intake_requirement_changes_extraction_id"),
    )
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
