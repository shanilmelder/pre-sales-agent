"""The ToolGateway (Story 5.4, AD-9): task-scoped, permission-checked READ tools for Agents.

- `catalogue` — the tool names (each an `identity` action) and `READ_TOOLS`.
- `port` — `ToolContext` and the outcomes `ToolResult`, `ToolDenied`, `ToolFailed`.
- `gateway` — `ToolGateway.call`, `register_tool`, `register_research_sink`.
- `models` — the `platform_tool_calls` row.
- `allowlist`, `fetcher` — the research allowlist and the HTTPS fetcher.
"""

from app.platform.tool_gateway.catalogue import READ_TOOLS, TOOLS, is_read_tool
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
    "ToolContext",
    "ToolDenied",
    "ToolFailed",
    "ToolGateway",
    "ToolOutcome",
    "ToolResult",
    "is_read_tool",
    "register_research_sink",
    "register_tool",
    "registered_tools",
]
