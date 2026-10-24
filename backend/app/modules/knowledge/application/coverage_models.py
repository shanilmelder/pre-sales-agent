"""Read models for Knowledge coverage (Story 3.5)."""

from pydantic import BaseModel, Field

from app.modules.knowledge.domain.coverage import CoverageStatus


class CoverageCounts(BaseModel):
    """What covers one product and Integration Type pair. `sources`: non-retired Sources
    whose latest version is Ready (searchable); `stale`: how many of those are stale;
    `checklists`: active Checklists with a published version whose published scope covers
    the pair."""

    sources: int = Field(ge=0)
    stale: int = Field(ge=0)
    checklists: int = Field(ge=0)
    status: CoverageStatus


class CoveragePair(CoverageCounts):
    """The counts for one asked-for pair (`get_pair_coverage`)."""

    product: str
    integration_type_id: str


class CoverageCell(CoverageCounts):
    integration_type_id: str


class CoverageRow(BaseModel):
    """One product, with a cell per column, in column order."""

    product: str
    cells: list[CoverageCell]


class CoverageIntegrationType(BaseModel):
    """A column: an active Integration Type."""

    id: str
    code: str
    name: str


class CoverageIndustry(BaseModel):
    """Checklists scoped only by this industry (no products, no Integration Types)."""

    industry: str
    checklists: int = Field(ge=1)
    names: list[str] = Field(description="The Checklists' names, by name.")


class KnowledgeCoverage(BaseModel):
    """The coverage matrix: products (rows, sorted ignoring case) by active Integration Types
    (columns), and the industry-only Checklists. `stale_months` is the review age after which
    a Source is stale."""

    integration_types: list[CoverageIntegrationType]
    rows: list[CoverageRow]
    industries: list[CoverageIndustry]
    stale_months: int = Field(ge=1)
