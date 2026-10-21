"""Read and write models for Knowledge Sources (Story 3.2), their embedding state and search
results (Story 3.3)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.knowledge.domain.embedding import EmbedErrorCode, EmbedStatus
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


class KnowledgeSourceEmbed(BaseModel):
    """Where chunking and embedding of a parsed version stands (Story 3.3): `ready` means
    its chunks are searchable. `error_code` is set exactly when `failed`."""

    status: EmbedStatus
    error_code: EmbedErrorCode | None


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
    embed: KnowledgeSourceEmbed | None = Field(
        description="The latest version's embedding state; null until its parse succeeds, "
        "and for a version parsed before embedding existed (it can be embedded on request)."
    )
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
    embed: KnowledgeSourceEmbed | None
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


# --- search (Story 3.3) -----------------------------------------------------------------------


class KnowledgeSpan(BaseModel):
    """Unicode code-point offsets `[start, end)` into the version's extracted text."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)


class KnowledgeEvidence(BaseModel):
    """A citable Evidence reference to a chunk (AD-13): `id` is the chunk, `version` the
    Source version and `span` the chunk's offsets in that version's extracted text."""

    kind: Literal["knowledge_chunk"]
    id: str
    version: int = Field(ge=1)
    span: KnowledgeSpan


class KnowledgeSearchHit(BaseModel):
    """One passage, nearest first. `text` is exactly the cited span of the extracted text."""

    text: str
    source_id: str
    source_title: str
    version: int = Field(ge=1)
    product: str
    product_version: str
    stale: bool
    distance: float = Field(description="Cosine distance to the query: lower is closer.")
    evidence: KnowledgeEvidence


class KnowledgeSearchResult(BaseModel):
    items: list[KnowledgeSearchHit]
    model: str = Field(description="The embedding profile the query and chunks share.")
    stale_months: int = Field(ge=1)
