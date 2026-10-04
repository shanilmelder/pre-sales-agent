"""Read models for Opportunity Sources (Story 2.1) and their parse state (Story 2.2)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.intake.domain.parsing import ParseErrorCode, ParseStatus
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
