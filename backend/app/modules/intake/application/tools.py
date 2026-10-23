"""intake's ToolGateway handlers (Story 5.4), registered at import.

- `intake.requirement.list`: the task Opportunity's active Requirements at their current
  versions, by number (`RequirementSnapshot`s).
- `intake.passage.read`: `{"passage_ids": [...]}`, those passages of the task Opportunity's
  Sources (`PassageRef`s). Any id that isn't a passage of that Opportunity denies the whole
  call (`out_of_scope`) and returns nothing.

Both take the Opportunity from the `ToolContext`, never from the arguments. The gateway
checks the permission and records the call.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.intake.application.answers import passage_refs
from app.modules.intake.application.requirement_refs import active_requirement_snapshots
from app.platform import tool_gateway
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolResult
from app.platform.tool_gateway.catalogue import PASSAGE_READ, REQUIREMENT_LIST
from app.platform.uow import UnitOfWork

PASSAGE_READ_MAX = 50


def ids_argument(args: Mapping[str, Any], key: str, maximum: int) -> list[UUID] | None:
    """`args[key]` as a list of 1..`maximum` UUIDs; None when missing or malformed."""
    raw = args.get(key)
    if not isinstance(raw, list | tuple) or not 1 <= len(raw) <= maximum:
        return None
    try:
        return [value if isinstance(value, UUID) else UUID(str(value)) for value in raw]
    except ValueError:
        return None


async def list_requirements(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    return ToolResult(items=tuple(await active_requirement_snapshots(uow, ctx.opportunity_id)))


async def read_passages(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    ids = ids_argument(args, "passage_ids", PASSAGE_READ_MAX)
    if ids is None:
        return ToolDenied("out_of_scope")
    found = await passage_refs(uow, ctx.opportunity_id, ids)
    if any(passage_id not in found for passage_id in ids):
        return ToolDenied("out_of_scope")
    return ToolResult(items=tuple(found[passage_id] for passage_id in dict.fromkeys(ids)))


tool_gateway.register_tool(REQUIREMENT_LIST, list_requirements)
tool_gateway.register_tool(PASSAGE_READ, read_passages)
