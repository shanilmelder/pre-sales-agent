"""The ToolGateway (Story 5.4, AD-9): task-scoped, permission-checked READ tools for Agents.

- `catalogue` — the tool names (each an `identity` action) and `READ_TOOLS`.
- `port` — `ToolContext` and the outcomes `ToolResult`, `ToolDenied`, `ToolFailed`.
- `gateway` — `ToolGateway.call`, `register_tool`, `register_research_sink`.
- `models` — the `platform_tool_calls` row.
- `allowlist`, `fetcher` — the research allowlist and the HTTPS fetcher.
- `denials` — `list_denials`, the denied-call list (Story 7.4).
"""

from app.platform.tool_gateway.catalogue import READ_TOOLS, TOOLS, is_read_tool
from app.platform.tool_gateway.denials import DenialPage, DenialRecord, list_denials
from app.platform.tool_gateway.gateway import (
    ToolGateway,
    register_research_sink,
    register_tool,
    registered_tools,
)
from app.platform.tool_gateway.port import (
    ToolContext,
    ToolDenied,
    ToolFailed,
    ToolOutcome,
    ToolResult,
)

__all__ = [
    "READ_TOOLS",
    "TOOLS",
    "DenialPage",
    "DenialRecord",
    "ToolContext",
    "ToolDenied",
    "ToolFailed",
    "ToolGateway",
    "ToolOutcome",
    "ToolResult",
    "is_read_tool",
    "list_denials",
    "register_research_sink",
    "register_tool",
    "registered_tools",
]
