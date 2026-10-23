"""The ToolGateway's tool catalogue (Story 5.4, AD-9): every tool an Agent may call.

Each tool is a READ, named by an `identity` action (`<module>.<entity>.<verb>`; the names
are repeated in `app.modules.identity.actions.Action`, a test keeps the two in step). There
is no write, delete, send or approve tool. An Agent's registry config grants tools through
`tool_permissions`, which accepts only these names.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

REQUIREMENT_LIST = "intake.requirement.list"
PASSAGE_READ = "intake.passage.read"
CHUNK_SEARCH = "knowledge.chunk.search"
CHUNK_READ = "knowledge.chunk.read"
CATALOGUE_ENTRY_LIST = "knowledge.catalogue_entry.list"
GAP_LIST = "gaps.gap.list"
RESEARCH_PAGE_FETCH = "knowledge.research_page.fetch"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    network: bool = False
    """True for the research fetch: it runs with no Unit of Work open (AD-25)."""


_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(REQUIREMENT_LIST, "The task Opportunity's active Requirements, by number."),
    ToolSpec(PASSAGE_READ, "Cited Source passages of the task Opportunity, by id."),
    ToolSpec(CHUNK_SEARCH, "The Knowledge chunks nearest to a query."),
    ToolSpec(CHUNK_READ, "Knowledge chunks by id."),
    ToolSpec(CATALOGUE_ENTRY_LIST, "The active Integration Types and Work Packages."),
    ToolSpec(GAP_LIST, "The task Opportunity's open Gaps."),
    ToolSpec(
        RESEARCH_PAGE_FETCH,
        "Fetch one allowlisted HTTPS page and keep it as a Research Snapshot.",
        network=True,
    ),
)

TOOLS: Mapping[str, ToolSpec] = MappingProxyType({t.name: t for t in _TOOLS})
READ_TOOLS: frozenset[str] = frozenset(TOOLS)
"""Every tool name; all of them are reads."""


def is_read_tool(name: str) -> bool:
    return name in READ_TOOLS
