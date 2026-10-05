"""`pm_agent` (Epic 5 slice 5A): the PM Agent assesses an Opportunity:
delivery phases, coordination, stakeholders, and PM and testing hours.

The agent only proposes (AD-4): one `complete_structured` call through the ModelGateway (see
`app.agents.specialist.agent`); `assessments.accept_assessment` validates and writes the
result in `extensions["pm_agent"]`.
"""

from functools import cache
from pathlib import Path

from app.agents.contract import AgentConfig
from app.agents.pm_agent.schema import PmOutput
from app.agents.specialist.agent import SpecialistAgent, read_prompt
from app.platform.model_gateway.port import ModelGatewayPort

AGENT_ID = "pm_agent"
SEMVER = "0.1.0"
PROMPT_VERSION = 1
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def config(profile: str) -> AgentConfig:
    """`pm_agent`'s config for a chat profile (`PSA_MODEL_PROFILE_CHAT`)."""
    return AgentConfig(
        agent_id=AGENT_ID, semver=SEMVER, prompt_version=PROMPT_VERSION, profile=profile
    )


@cache
def prompt(version: int = PROMPT_VERSION) -> str:
    """The instructions, `prompts/v<version>.md`."""
    return read_prompt(PROMPTS_DIR, version)


class PmAgent(SpecialistAgent):
    def __init__(self, gateway: ModelGatewayPort, *, profile: str) -> None:
        agent_config = config(profile)
        super().__init__(
            gateway,
            config=agent_config,
            instructions=prompt(agent_config.prompt_version),
            output_model=PmOutput,
        )
