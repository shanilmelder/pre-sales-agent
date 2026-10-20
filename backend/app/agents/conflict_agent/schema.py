"""`conflict_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in
`AgentResult.extensions["conflict_agent"]`.

`type` and `severity` are plain strings whose JSON schema lists the allowed values (so
constrained decoding keeps to them) while parsing accepts any string: one candidate with an
unknown value is dropped on acceptance instead of failing the whole reply. Text fields carry
no limits here for the same reason; the conflicts module re-validates every candidate.
"""

from pydantic import BaseModel, ConfigDict, Field

TYPES: tuple[str, ...] = ("architecture", "assumption", "evidence", "scope")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConflictStance(_Output):
    finding_label: str = Field(description="The label of a cited Finding, e.g. 'F3'.")
    stance: str = Field(
        description="What that Finding holds, in one sentence (at most 240 characters)."
    )


class ConflictCandidateOutput(_Output):
    type: str = Field(
        description="What kind of contradiction this is.",
        json_schema_extra={"enum": list(TYPES)},
    )
    severity: str = Field(
        description="How much harm the contradiction does if nobody resolves it.",
        json_schema_extra={"enum": list(SEVERITIES)},
    )
    finding_labels: list[str] = Field(
        description="Labels of the contradicting Findings, at least two from different "
        "agents, e.g. ['F2', 'F5']."
    )
    summary: str = Field(description="The contradiction in one sentence (at most 240 characters).")
    stances: list[ConflictStance] = Field(description="One stance per cited Finding.")
    mandatory_constraint: bool = Field(
        description="True only if the contradiction is about a mandatory constraint "
        "(a mandatory checklist item or a mandatory security control)."
    )


class ConflictOutput(_Output):
    conflicts: list[ConflictCandidateOutput]
