"""`critic_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in `AgentResult.extensions["critic_agent"]`.

`category`, `severity` and `type` are plain strings whose JSON schema lists the allowed
values (so constrained decoding keeps to them) while parsing accepts any string: one Finding
or contradiction with an unknown value is dropped on acceptance instead of failing the whole
reply. Text fields carry no limits here for the same reason; `assessments` re-validates every
Finding and `conflicts` every contradiction.
"""

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES: tuple[str, ...] = (
    "coverage",
    "unsupported_claim",
    "timeline",
    "dependency",
    "risk_coverage",
)
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
CONTRADICTION_TYPES: tuple[str, ...] = ("architecture", "assumption", "evidence", "scope")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriticFindingCandidate(_Output):
    category: str = Field(
        description="What kind of weakness this is.",
        json_schema_extra={"enum": list(CATEGORIES)},
    )
    severity: str = Field(
        description="How much harm it does if nobody acts on it.",
        json_schema_extra={"enum": list(SEVERITIES)},
    )
    title: str = Field(
        description="A specific one-line Finding naming the agent by role, e.g. 'PM Agent "
        "plans go-live in 6 weeks but Engineering sizes R3 at 900 h'."
    )
    argument: str = Field(description="Why this is a problem, in a few sentences.")
    findings: list[str] = Field(
        default_factory=list,
        description="Labels of the specialist Findings this challenges, e.g. ['F2']; may be "
        "empty when it cites Requirements.",
    )
    requirements: list[str] = Field(
        default_factory=list,
        description="Labels of the Requirements concerned, e.g. ['R5']; may be empty when it "
        "cites Findings.",
    )


class CriticStance(_Output):
    finding: str = Field(description="The label of a cited Finding, e.g. 'F3'.")
    stance: str = Field(
        description="What that Finding holds, in one sentence (at most 240 characters)."
    )


class CriticContradiction(_Output):
    type: str = Field(
        description="What kind of contradiction this is.",
        json_schema_extra={"enum": list(CONTRADICTION_TYPES)},
    )
    severity: str = Field(
        description="How much harm the contradiction does if nobody resolves it.",
        json_schema_extra={"enum": list(SEVERITIES)},
    )
    summary: str = Field(description="The contradiction in one sentence (at most 240 characters).")
    positions: list[CriticStance] = Field(
        description="One position per contradicting Finding: at least two, from different agents."
    )
    mandatory_constraint: bool = Field(
        default=False,
        description="True only if the contradiction is about a mandatory constraint "
        "(a mandatory checklist item or a mandatory security control).",
    )


class CriticOutput(_Output):
    findings: list[CriticFindingCandidate] = Field(default_factory=list)
    contradictions: list[CriticContradiction] = Field(default_factory=list)
