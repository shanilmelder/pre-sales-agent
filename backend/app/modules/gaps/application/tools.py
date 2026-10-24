"""gaps' ToolGateway handler (Story 5.4), registered at import.

- `gaps.gap.list`: the task Opportunity's open Gaps, high impact first (`GapSummary`s). The
  Opportunity comes from the `ToolContext`, never from the arguments; the gateway checks the
  permission and records the call.
"""

from collections.abc import Mapping
from typing import Any

from app.modules.gaps.application.gap_refs import open_gap_summaries
from app.platform import tool_gateway
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolResult
from app.platform.tool_gateway.catalogue import GAP_LIST
from app.platform.uow import UnitOfWork


async def list_open_gaps(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    return ToolResult(items=tuple(await open_gap_summaries(uow, ctx.opportunity_id)))


tool_gateway.register_tool(GAP_LIST, list_open_gaps)
