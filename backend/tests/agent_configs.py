"""Agent configs for tests that build an agent directly: the seeded config version 1 of the
Agent Registry (Story 7.1), with its deterministic id."""

from app.agents.contract import AgentConfig
from app.modules.registry.domain.registry import seed_config_version_id

SEED_SEMVER = "0.1.0"


def seed_config(agent_id: str, profile: str = "demo-chat") -> AgentConfig:
    """`agent_id`'s seeded config version 1 (0.1.0, prompt 1), calling `profile`."""
    return AgentConfig(
        agent_id=agent_id,
        semver=SEED_SEMVER,
        prompt_version=1,
        profile=profile,
        config_version_id=seed_config_version_id(agent_id),
    )
