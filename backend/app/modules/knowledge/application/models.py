"""Read and write models for the catalogue (Story 3.1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.knowledge.domain.catalogue import Kind, Status


class CatalogueEntry(BaseModel):
    """A catalogue entry at one version. `version` is the version shown (the current one
    unless another was asked for); `current_version` the latest. `retired` is true for a
    retired entry, which still resolves; `retired_reason` is set exactly then."""

    id: str
    kind: Kind
    code: str
    name: str
    definition: str
    version: int = Field(ge=1)
    current_version: int = Field(ge=1)
    status: Status
    retired: bool
    retired_reason: str | None
    row_version: int
    created_at: datetime


class CatalogueList(BaseModel):
    items: list[CatalogueEntry]


class CatalogueVersion(BaseModel):
    """One earlier or current version of an entry, with who saved it."""

    version: int = Field(ge=1)
    name: str
    definition: str
    changed_by_id: str
    changed_by_name: str
    changed_at: datetime


class CatalogueVersionList(BaseModel):
    """The entry's versions, newest first."""

    items: list[CatalogueVersion]


class NewEntry(BaseModel):
    """Create an entry. Text is trimmed; code 1-40, name 1-120, definition 1-2,000
    characters."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["integration_type", "work_package"]
    code: StrictStr
    name: StrictStr
    definition: StrictStr


class EntryChanges(BaseModel):
    """Fields to change; a field left out stays as it is."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    definition: StrictStr | None = None


class RetireRequest(BaseModel):
    """Why the entry is retired (1-500 characters, trimmed)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr
