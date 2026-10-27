"""Read models for the Knowledge Graph (Story 3.6)."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from app.modules.knowledge.application.source_models import KnowledgeUserRef
from app.modules.knowledge.domain.graph import NodeStatus


class GraphNodeType(StrEnum):
    PRODUCT = "product"
    INTEGRATION_TYPE = "integration_type"
    SOURCE = "source"
    CHECKLIST = "checklist"


class GraphEdgeKind(StrEnum):
    LINKED = "linked"
    """A Source's or Checklist's tag, or a Ready product and Integration Type pair."""
    GAP = "gap"
    """A Partial product and Integration Type pair: covered only by Sources or only by
    Checklists (missing coverage)."""


class GraphNode(BaseModel):
    """One node. `id` is prefixed by type (`product:<match key>`, `integration_type:<id>`,
    `source:<id>`, `checklist:<id>`). `owner`: the Source's owner or the Checklist's creator
    (None for products and Integration Types). `last_reviewed_on`: the Source's last review
    or the Checklist's latest publication. `row_version` and `can_review` (the caller may
    Mark reviewed) are for Sources only; `stale_in_days` (0 once stale) too."""

    id: str
    type: GraphNodeType
    label: str
    status: NodeStatus
    score: int = Field(ge=0, le=100)
    owner: KnowledgeUserRef | None
    last_reviewed_on: date | None
    row_version: int | None = None
    can_review: bool = False
    stale_in_days: int | None = Field(default=None, ge=0)


class GraphEdge(BaseModel):
    """A link between two nodes (their ids). Products are always `source` of a product and
    Integration Type edge; Sources and Checklists are always `source` of their tag edges."""

    source: str
    target: str
    kind: GraphEdgeKind


class KnowledgeGraph(BaseModel):
    """Products, active Integration Types, non-retired Sources and active published
    Checklists, and the links between them. `stale_months` is the review age after which a
    Source is stale."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stale_months: int = Field(ge=1)
