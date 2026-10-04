"""Read models for Opportunity Sources (Story 2.1)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.intake.domain.sources import SourceKind
from app.modules.opportunities.application.public import UserRef


class Source(BaseModel):
    """An Opportunity Source with its latest version. `filename`, `size_bytes`,
    `uploaded_by` and `uploaded_at` describe that version; `version_count` counts them
    all."""

    id: str
    kind: SourceKind
    filename: str
    version: int = Field(ge=1)
    version_count: int = Field(ge=1)
    size_bytes: int = Field(ge=1)
    uploaded_by: UserRef
    uploaded_at: datetime
    created_at: datetime


class SourceList(BaseModel):
    """An Opportunity's Sources, newest first."""

    items: list[Source]
