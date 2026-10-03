"""Inputs and read models for Opportunities (Story 1.7)."""

from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.opportunities.domain import opportunity as rules
from app.modules.opportunities.domain.opportunity import OpportunityStatus


class NewOpportunity(BaseModel):
    """What a presales engineer enters to create an Opportunity. Text is trimmed; a blank
    title falls back to the customer name; products are de-duplicated case-insensitively;
    the target proposal date may not be before today (UTC)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None, description=f"Optional, at most {rules.TITLE_MAX} characters."
    )
    customer_name: str = Field(description=f"Required, at most {rules.CUSTOMER_NAME_MAX}.")
    products: list[str] = Field(
        description=(
            f"{rules.PRODUCTS_MIN}-{rules.PRODUCTS_MAX} product names, each "
            f"1-{rules.PRODUCT_NAME_MAX} characters."
        )
    )
    industry: str = Field(description=f"Required, at most {rules.INDUSTRY_MAX} characters.")
    target_proposal_date: date = Field(description="A calendar date, not in the past.")

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return rules.optional_title(value)

    @field_validator("customer_name")
    @classmethod
    def _customer_name(cls, value: str) -> str:
        return rules.required_text(value, max_length=rules.CUSTOMER_NAME_MAX)

    @field_validator("industry")
    @classmethod
    def _industry(cls, value: str) -> str:
        return rules.required_text(value, max_length=rules.INDUSTRY_MAX)

    @field_validator("products")
    @classmethod
    def _products(cls, value: list[str]) -> list[str]:
        return rules.normalize_products(value)

    @field_validator("target_proposal_date")
    @classmethod
    def _target_date(cls, value: date) -> date:
        return rules.check_target_date(value, today=datetime.now(UTC).date())


class OpportunityChanges(BaseModel):
    """What the owner edits on an existing Opportunity (Story 1.8 Part B). An omitted (or
    null) field stays unchanged. This checks shape only: the title is trimmed and at most
    the title limit, and may be blank (it then falls back to the customer name). The
    not-in-the-past rule for the date needs the stored value, so the command checks it."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        description=f"At most {rules.TITLE_MAX} characters once trimmed; blank falls back to "
        "the customer name.",
    )
    target_proposal_date: date | None = Field(
        default=None,
        description="A calendar date, not in the past (checked only when it changes).",
    )

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return None if value is None else rules.edited_title(value)


class UserRef(BaseModel):
    """A user shown by name."""

    id: str
    name: str


class OpportunitySummary(BaseModel):
    """A list row."""

    id: str
    title: str
    customer_name: str
    status: OpportunityStatus
    owner: UserRef
    target_proposal_date: date
    created_at: datetime


class OpportunityPage(BaseModel):
    """One page of Opportunities, newest first."""

    items: list[OpportunitySummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class OpportunityFilters(BaseModel):
    """All Opportunities filters (Story 1.7 Part B). Every one is optional and they combine
    with AND. `product` matches any of the Opportunity's products, trimmed and ignoring case
    (a blank one is ignored); `date_from`/`date_to` bound the target proposal date
    inclusively and may not be reversed."""

    model_config = ConfigDict(frozen=True)

    status: OpportunityStatus | None = None
    owner_id: UUID | None = None
    product: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @field_validator("product")
    @classmethod
    def _product(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    @model_validator(mode="after")
    def _range(self) -> "OpportunityFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("`from` must not be after `to`")
        return self


class OpportunityFacets(BaseModel):
    """The filter choices for All Opportunities: the distinct owners and products across
    the Opportunities the caller can read, each sorted ignoring case."""

    owners: list[UserRef]
    products: list[str]


class Opportunity(BaseModel):
    """One Opportunity as a reader sees it. `row_version` is also the `ETag`.

    `last_changed_by` names whoever made the latest recorded change (null when unknown).
    `can_manage_collaborators` says whether the caller may add or remove collaborators and
    `can_edit` whether they may edit the title and target proposal date; the UI only uses
    them to hide controls, the API decides on every write."""

    id: str
    title: str
    customer_name: str
    products: list[str]
    industry: str
    target_proposal_date: date
    status: OpportunityStatus
    owner: UserRef
    collaborators: list[UserRef]
    row_version: int
    created_at: datetime
    last_changed_by: str | None
    can_manage_collaborators: bool
    can_edit: bool
