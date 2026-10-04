"""`red_team_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in
`AgentResult.extensions["red_team_agent"]`.

`category` and `severity` are plain strings whose JSON schema lists the allowed values (so
constrained decoding keeps to them) while parsing accepts any string: one Finding with an
unknown value is dropped on acceptance instead of failing the whole reply. Text fields carry
no limits here for the same reason; the assessments module re-validates every Finding.
"""

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES: tuple[str, ...] = (
    "integration_harder",
    "requirement_incomplete",
    "capability_overstated",
    "hidden_dependency",
)
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RedTeamFindingCandidate(_Output):
    category: str = Field(
        description="What kind of challenge this is.",
        json_schema_extra={"enum": list(CATEGORIES)},
    )
    severity: str = Field(
        description="How badly the deal overruns or fails if nobody acts on it.",
        json_schema_extra={"enum": list(SEVERITIES)},
    )
    title: str = Field(
        description="A specific one-line challenge, e.g. 'ERP custom fields — no evidence the "
        "connector supports them'."
    )
    argument: str = Field(description="Why this is harder than it looks, in a few sentences.")
    requirements: list[str] = Field(
        description="Labels of the Requirements this challenges, e.g. ['R2', 'R5']."
    )
    lines: list[str] = Field(
        default_factory=list,
        description="Labels of the Estimate lines this challenges, e.g. ['L3']; may be empty.",
    )


class RedTeamOutput(_Output):
    findings: list[RedTeamFindingCandidate]
