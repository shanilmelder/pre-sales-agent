"""Read and write models for Knowledge Sources (Story 3.2)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.platform.parsing.rules import ParseErrorCode, ParseStatus

SourceStatus = Literal["active", "retired"]


class KnowledgeUserRef(BaseModel):
    id: str
    name: str


class IntegrationTypeTag(BaseModel):
    """An Integration Type a Source is tagged with. `retired` tags keep resolving."""

    id: str
    code: str
    name: str
    retired: bool


class KnowledgeSourceParse(BaseModel):
    """Where parsing of a version stands. `error_code` is set exactly when `failed`."""

    status: ParseStatus
    error_code: ParseErrorCode | None


class KnowledgeSource(BaseModel):
    """A Knowledge Source at its latest version. `stale` is derived: the last-reviewed date
    is more than `stale_months` months ago (it is never stored). `retired_reason` is set
    exactly when `retired`."""

    id: str
    title: str
    product: str
    owner: KnowledgeUserRef
    integration_types: list[IntegrationTypeTag]
    status: SourceStatus
    retired: bool
    retired_reason: str | None
    last_reviewed_on: date
    stale: bool
    version: int = Field(ge=1)
    version_count: int = Field(ge=1)
    product_version: str
    filename: str
    size_bytes: int
    uploaded_by: KnowledgeUserRef
    uploaded_at: datetime
    parse: KnowledgeSourceParse
    row_version: int
    created_at: datetime


class KnowledgeSourceList(BaseModel):
    items: list[KnowledgeSource]
    stale_months: int = Field(ge=1, description="The threshold `stale` was derived with.")


class KnowledgeSourceVersion(BaseModel):
    """One uploaded file of a Source. Earlier versions stay readable."""

    version: int = Field(ge=1)
    product_version: str
    filename: str
    size_bytes: int
    uploaded_by: KnowledgeUserRef
    uploaded_at: datetime
    parse: KnowledgeSourceParse
    char_count: int | None


class KnowledgeSourceVersionList(BaseModel):
    """The Source's versions, newest first."""

    items: list[KnowledgeSourceVersion]


class SourceText(BaseModel):
    """The extracted text of a parsed version, exactly as stored."""

    version: int = Field(ge=1)
    char_count: int
    text: str


class DownloadLink(BaseModel):
    """A short-lived signed link to the original file of a version. `url` is relative to
    the API origin."""

    url: str
    expires_at: datetime


class SourceChanges(BaseModel):
    """Fields to change; a field left out stays as it is. `integration_type_ids`
    replaces the tags. Only an administrator may change `owner_id`."""

    model_config = ConfigDict(extra="forbid")

    title: StrictStr | None = None
    product: StrictStr | None = None
    owner_id: str | None = None
    integration_type_ids: list[str] | None = None


class RetireSource(BaseModel):
    """Why the Source is retired (1-500 characters, trimmed)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr
