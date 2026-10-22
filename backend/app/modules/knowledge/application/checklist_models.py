"""Read and write models for Checklists (Story 3.4)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from app.modules.knowledge.application.source_models import IntegrationTypeTag, KnowledgeUserRef
from app.modules.knowledge.domain.catalogue import Kind
from app.modules.knowledge.domain.checklists import Domain, Impact, ItemKind, Status


class AffectedArea(BaseModel):
    """The estimate area an item affects: an Integration Type or a Work Package. A retired
    entry keeps resolving, with `retired` true."""

    id: str
    kind: Kind
    code: str
    name: str
    retired: bool


class ChecklistItem(BaseModel):
    """One item. `id` is stable across versions: an item carried into the next version keeps
    it. Mandatory items always raise a Gap when unanswered; on a `security` Checklist they are
    mandatory security controls."""

    id: str
    kind: ItemKind
    text: str
    why_it_matters: str
    affected_area: AffectedArea | None
    impact: Impact
    mandatory: bool


class ChecklistDraft(BaseModel):
    """The one unpublished draft: what the next Publish will make the next version."""

    name: str
    domain: Domain
    products: list[str]
    industry: str | None
    integration_types: list[IntegrationTypeTag]
    items: list[ChecklistItem]
    publishable: bool = Field(description="True when Publish would succeed.")
    publish_problem: str | None = Field(
        description="Why the draft can't be published yet (the sentence to show), or null."
    )


class Checklist(BaseModel):
    """A Checklist. `name`, `domain`, `products`, `industry`, `integration_types` and `items`
    are the latest published version's (`current_version`, null before the first Publish;
    `name` and `domain` are then the ones given at creation). `draft` is the unpublished
    draft, or null. `retired_reason` is set exactly when `retired`."""

    id: str
    name: str
    domain: Domain
    products: list[str]
    industry: str | None
    integration_types: list[IntegrationTypeTag]
    status: Status
    retired: bool
    retired_reason: str | None
    current_version: int | None = Field(ge=1)
    item_count: int = Field(ge=0, description="Items in the current version.")
    mandatory_count: int = Field(ge=0, description="Mandatory items in the current version.")
    items: list[ChecklistItem]
    draft: ChecklistDraft | None
    created_by: KnowledgeUserRef
    created_at: datetime
    row_version: int


class ChecklistList(BaseModel):
    items: list[Checklist]


class ChecklistVersionSummary(BaseModel):
    """One published version, with who published it and when."""

    version: int = Field(ge=1)
    name: str
    published_by: KnowledgeUserRef
    published_at: datetime
    item_count: int
    mandatory_count: int


class ChecklistVersionList(BaseModel):
    """The Checklist's published versions, newest first."""

    items: list[ChecklistVersionSummary]


class ChecklistVersion(BaseModel):
    """One published version, read-only: its name, domain, scope and items as published."""

    checklist_id: str
    version: int = Field(ge=1)
    name: str
    domain: Domain
    products: list[str]
    industry: str | None
    integration_types: list[IntegrationTypeTag]
    items: list[ChecklistItem]
    published_by: KnowledgeUserRef
    published_at: datetime


class NewChecklist(BaseModel):
    """Create a Checklist: a name (1-200 characters, trimmed) and a domain. It starts with an
    empty draft."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    domain: Domain


class DraftItemInput(BaseModel):
    """One item of a draft. `id` null: a new item (it gets a stable id when saved); otherwise
    an id from the draft or an earlier version. Text and "why it matters" may be blank while
    drafting (at most 2,000 characters each); Publish needs both."""

    model_config = ConfigDict(extra="forbid")

    id: StrictStr | None = None
    kind: ItemKind
    text: StrictStr = Field(max_length=4000)
    why_it_matters: StrictStr = Field(max_length=4000)
    affected_entry_id: StrictStr | None = None
    impact: Impact
    mandatory: StrictBool


class DraftInput(BaseModel):
    """The whole draft, replacing the stored one. Products (at most 20, 1-100 characters
    each) and the industry (at most 100) are trimmed; products repeated ignoring case are
    kept once. Integration Types and affected areas must be active catalogue entries."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    domain: Domain
    products: list[StrictStr] = Field(default_factory=list, max_length=100)
    industry: StrictStr | None = None
    integration_type_ids: list[StrictStr] = Field(default_factory=list, max_length=200)
    items: list[DraftItemInput] = Field(default_factory=list, max_length=400)


class RetireChecklist(BaseModel):
    """Why the Checklist is retired (1-500 characters, trimmed)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr


class ApplicableItem(BaseModel):
    """An item of an applicable Checklist version, for Gap detection."""

    item_id: str
    kind: ItemKind
    text: str
    why_it_matters: str
    affected_entry_id: str | None
    impact: Impact
    mandatory: bool


class ApplicableChecklist(BaseModel):
    """The latest published version of an active Checklist whose scope matches. Mandatory
    items of a `security` Checklist are mandatory security controls."""

    checklist_id: str
    version: int
    name: str
    domain: Domain
    items: list[ApplicableItem]
