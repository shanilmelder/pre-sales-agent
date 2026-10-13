"""`estimating_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in
`AgentResult.extensions["estimating_agent"]`.

Sections are listed here as literals (agents never import a module's domain), so constrained
decoding keeps them to the template's sections; the estimates module re-validates every line
on acceptance. Text and number fields carry no limits here on purpose: one bad line is
dropped on acceptance instead of failing the whole reply.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SectionName = Literal[
    "functional",
    "integration",
    "data",
    "security",
    "non_functional",
    "commercial",
]


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleMix(_Output):
    engineer: int = Field(description="The engineer's share of the effort, in percent.")
    project_manager: int = Field(description="The project manager's share, in percent.")
    qa: int = Field(description="QA's share, in percent.")


class EstimateLineCandidate(_Output):
    section: SectionName
    title: str = Field(description="A short name for the work item.")
    covers: list[str] = Field(
        description="Labels of the Requirements this work item delivers, e.g. ['R1', 'R4']."
    )
    effort_hours: float = Field(description="The work item's effort in person-hours.")
    role_mix: RoleMix
    basis: str = Field(description="One or two sentences on how the effort was sized.")


class EstimatingOutput(_Output):
    lines: list[EstimateLineCandidate]


# --- Assumption proposals (Story 8.4, prompt `v1-assumptions`) -------------------------------


class AssumptionCandidate(_Output):
    gap: str = Field(description="The label of the open Gap this Assumption covers, e.g. 'G2'.")
    resolvable_by: str = Field(
        description=(
            "One sentence, written before choosing the kind: can the customer realistically "
            "remove this uncertainty before the work starts, or will nobody know until the "
            "work is under way? Not stored."
        )
    )
    """Comes before `kind` so that, under constrained decoding, the model weighs who can
    remove the uncertainty before it commits to a kind (without it nearly every Gap became a
    Condition, since every Gap carries a question to the customer)."""
    kind: Literal["condition", "contingency"]
    wording: str = Field(
        description=(
            "Proposal-ready wording: a Condition starts 'The estimate assumes the customer…'; "
            "a Contingency says what the hours cover."
        )
    )
    hours: float | None = Field(
        default=None,
        description="A Contingency's hours (0.5 to 1000). Null for a Condition.",
    )
    line: str | None = Field(
        default=None,
        description="The label of the Estimate line a Contingency affects, e.g. 'L3', or null.",
    )


class AssumptionsOutput(_Output):
    assumptions: list[AssumptionCandidate]
