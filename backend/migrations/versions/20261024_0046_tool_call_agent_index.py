"""Index `platform_tool_calls`' denied calls by time and by Agent (Story 7.4).

The Admin → Agents → Denied tool calls list reads `outcome = 'denied'` rows newest first,
optionally by Agent and date: two partial indexes over the denied rows only. No row
and no config version is touched: versions stay immutable, and any existing version that
grants a non-read permission (none expected) is left as it is.

Revision ID: 0046_tool_call_agent_index
Revises: 0045_registry_config_reason
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_tool_call_agent_index"
down_revision: str | None = "0045_registry_config_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CALLS = "platform_tool_calls"
DENIED = sa.text("outcome = 'denied'")
INDEXES = {
    "ix_platform_tool_calls_denied_agent_id_created_at": ["agent_id", "created_at"],
    "ix_platform_tool_calls_denied_created_at_id": ["created_at", "id"],
}


def upgrade() -> None:
    for name, columns in INDEXES.items():
        op.create_index(name, CALLS, columns, postgresql_where=DENIED)


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name=CALLS)
