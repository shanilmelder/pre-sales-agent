"""assessments' ToolGateway handler (Story 6.4), registered at import.

- `assessments.run.read`: the task run's accepted Assessments (the newest per agent) with
  their Findings and versions (`RunAssessment`s). The Opportunity and the run come from the
  `ToolContext`, never from the arguments: a call without a run, or naming another run, is
  denied `out_of_scope` and reads nothing. The gateway checks the permission and records the
  call.
"""

from collections.abc import Mapping
from typing import Any

from app.modules.assessments.application.critic import run_assessment_reads
from app.platform import tool_gateway
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolResult
from app.platform.tool_gateway.catalogue import RUN_ASSESSMENT_READ
from app.platform.uow import UnitOfWork


async def read_run_assessments(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    if ctx.run_id is None:
        return ToolDenied("out_of_scope")
    named = args.get("run_id")
    if named is not None and str(named) != str(ctx.run_id):
        return ToolDenied("out_of_scope")
    return ToolResult(items=tuple(await run_assessment_reads(uow, ctx.opportunity_id, ctx.run_id)))


tool_gateway.register_tool(RUN_ASSESSMENT_READ, read_run_assessments)
