"""`intake_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in `AgentResult.extensions["intake_agent"]`.

Classifications are listed here as literals (agents never import a module's domain); the
intake module re-validates them against its own `Classification` on acceptance.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClassificationName = Literal[
    "functional", "integration", "data", "security", "non_functional", "commercial"
]
SOURCE_LABEL_PATTERN = r"^S[1-9][0-9]*$"


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(_Output):
    source: str = Field(
        pattern=SOURCE_LABEL_PATTERN, description="The label of the cited Source, e.g. S1."
    )
    quote: str = Field(
        min_length=1, description="An exact, verbatim passage copied from that Source."
    )


class ExtractedRequirement(_Output):
    text: str = Field(min_length=1, description="One requirement, stated as one sentence.")
    classification: ClassificationName
    citations: list[Citation] = Field(min_length=1)


class IntakeOutput(_Output):
    requirements: list[ExtractedRequirement]
