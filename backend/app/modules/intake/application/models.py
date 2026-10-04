"""Read models for Opportunity Sources (Story 2.1), their parse state (Story 2.2) and
Requirements (Story 2.5)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.intake.domain.parsing import ParseErrorCode, ParseStatus
from app.modules.intake.domain.requirements import (
    Classification,
    ExtractionErrorCode,
    ExtractionStatus,
    RequirementOrigin,
)
from app.modules.intake.domain.sources import TEXT_MAX_CHARS, SourceKind
from app.modules.opportunities.application.public import UserRef


class SourceParse(BaseModel):
    """The parse state of a Source's latest version. `error_code` is set only when
    `failed`."""

    status: ParseStatus
    error_code: ParseErrorCode | None


class Source(BaseModel):
    """An Opportunity Source with its latest version. `filename`, `size_bytes`,
    `uploaded_by`, `uploaded_at` and `parse` describe that version; `version_count` counts
    them all. `parse` is null only for a version with no parse state."""

    id: str
    kind: SourceKind
    filename: str
    version: int = Field(ge=1)
    version_count: int = Field(ge=1)
    size_bytes: int = Field(ge=1)
    uploaded_by: UserRef
    uploaded_at: datetime
    created_at: datetime
    parse: SourceParse | None


class SourceList(BaseModel):
    """An Opportunity's Sources, newest first."""

    items: list[Source]


class AddTextSource(BaseModel):
    """Pasted text to add as a Source (Story 2.1 Part B). Only its shape is checked here;
    the trimming, length and character rules are the command's, so their rejections carry
    the UI sentences."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(
        description="The pasted text. Trimmed, it must be 1 to "
        f"{TEXT_MAX_CHARS:,} characters with no NUL character or lone surrogate."
    )


# --- Requirements (Story 2.5 Part A) --------------------------------------------------------


class RequirementEvidence(BaseModel):
    """A Source passage a Requirement cites. `label` is `S<n> · <file name>`, where `n` is
    the Source's position among the Opportunity's Sources, oldest first."""

    passage_id: str
    source_id: str
    source_version: int = Field(ge=1)
    filename: str
    label: str


class Requirement(BaseModel):
    """An active Requirement of the Opportunity with the passages it cites."""

    id: str
    text: str
    classification: Classification
    origin: RequirementOrigin
    locked_by_human: bool
    version: int = Field(ge=1)
    row_version: int = Field(ge=1)
    created_at: datetime
    evidence: list[RequirementEvidence]


class Extraction(BaseModel):
    """The Opportunity's latest Requirement extraction. `error_code` is set only when
    `failed`; `source_count` once it has read its Sources."""

    status: ExtractionStatus
    error_code: ExtractionErrorCode | None
    source_count: int | None


class RequirementList(BaseModel):
    """The Opportunity's active Requirements, oldest first, and its latest extraction (null
    when none has been queued yet). `can_start_extraction`: whether the caller may start
    (retry) an extraction; the UI only uses it to hide **Retry**, the API decides."""

    items: list[Requirement]
    extraction: Extraction | None
    can_start_extraction: bool
