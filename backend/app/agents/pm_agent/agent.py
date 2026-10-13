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

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@cache
def prompt(version: int) -> str:
    """The instructions, `prompts/v<version>.md`."""
    return read_prompt(PROMPTS_DIR, version)


class PmAgent(SpecialistAgent):
    def __init__(self, gateway: ModelGatewayPort, *, config: AgentConfig) -> None:
        super().__init__(
            gateway,
            config=config,
            instructions=prompt(config.prompt_version),
            output_model=PmOutput,
        )
