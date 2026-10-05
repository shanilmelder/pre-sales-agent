"""The specialist agents' output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in `AgentResult.extensions[<agent_id>]`.

`recommendation`, `confidence`, `kind` and `severity` are plain strings whose JSON schema
lists the allowed values (so constrained decoding keeps to them) while parsing accepts any
string: one Finding with an unknown value is dropped on acceptance instead of failing the
whole reply. Text and number fields carry no limits here for the same reason; the
assessments module re-validates the reply.
"""

from pydantic import BaseModel, ConfigDict, Field

RECOMMENDATIONS: tuple[str, ...] = ("proceed", "proceed_with_conditions", "do_not_proceed")
CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")
KINDS: tuple[str, ...] = ("risk", "constraint", "dependency", "opportunity")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecialistFindingCandidate(_Output):
    kind: str = Field(
        description="What kind of Finding this is.",
        json_schema_extra={"enum": list(KINDS)},
    )
    severity: str = Field(
        description="How much it matters to the deal if nobody acts on it.",
        json_schema_extra={"enum": list(SEVERITIES)},
    )
    title: str = Field(description="A specific one-line Finding.")
    detail: str = Field(description="What you found and why it matters, in a few sentences.")
    requirements: list[str] = Field(
        description="Labels of the Requirements this is about, e.g. ['R2', 'R5']."
    )


class EffortRowCandidate(_Output):
    requirement: str = Field(description="The label of one Requirement, e.g. 'R3'.")
    hours: float = Field(description="Your effort for that Requirement, in person-hours.")
    basis: str = Field(description="How you sized it, in one sentence.")


class SpecialistOutput(_Output):
    recommendation: str = Field(
        description="Whether to proceed with the deal from your point of view.",
        json_schema_extra={"enum": list(RECOMMENDATIONS)},
    )
    confidence: str = Field(
        description="How confident you are in that recommendation.",
        json_schema_extra={"enum": list(CONFIDENCES)},
    )
    confidence_basis: str = Field(description="Why you are that confident, in one sentence.")
    findings: list[SpecialistFindingCandidate]
    effort: list[EffortRowCandidate] = Field(
        default_factory=list,
        description="Effort per Requirement in your scope, one row per Requirement.",
    )
