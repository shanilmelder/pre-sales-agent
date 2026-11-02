"""Rename the `demo-chat` model profile to `ollama-cloud-chat`.

Config versions name their profile, so every row pinned to the old name is renamed in place.
A new config version would not do: older versions stay pinned by runs and can be restored,
and an undefined profile fails at run time. Config versions are otherwise immutable; only the
profile's name changes here, not the model it calls. `platform_model_calls` keeps the old name
as history. `local-chat` and `local-chat-openai` are removed from the code with no rename: a
row pinned to one of them fails as an unknown profile rather than move data to a cloud.

Revision ID: 0060_chat_profile_rename
Revises: 0059_challenge_versions
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060_chat_profile_rename"
down_revision: str | None = "0059_challenge_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "registry_agent_config_versions"


def upgrade() -> None:
    op.execute(
        f"UPDATE {VERSIONS} SET model_profile = 'ollama-cloud-chat' "  # noqa: S608 - constants only
        "WHERE model_profile = 'demo-chat'"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE {VERSIONS} SET model_profile = 'demo-chat' "  # noqa: S608 - constants only
        "WHERE model_profile = 'ollama-cloud-chat'"
    )
