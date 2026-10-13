"""`clarification_agent`'s output schema: the JSON object the model must return, sent to the
ModelGateway as the `format`. The same shape goes in
`AgentResult.extensions["clarification_agent"]`.

Categories and impacts are listed here as literals (agents never import a module's domain),
so constrained decoding keeps them to known values; the gaps module re-validates every
candidate on acceptance. Text fields carry no length limits here on purpose: one bad
candidate is dropped on acceptance instead of failing the whole reply.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CategoryName = Literal[
    "data_volumes",
    "versions_and_platforms",
    "integration_details",
    "security_and_compliance",
    "non_functional",
    "scope_and_ownership",
    "commercial",
    "other",
]
ImpactName = Literal["high", "medium", "low"]


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftQuestion(_Output):
    text: str = Field(
        description="A customer-ready question in plain language that would close the Gap."
    )
    topic: str = Field(description="A short topic for grouping questions, e.g. 'WMS interface'.")


class GapCandidate(_Output):
    title: str = Field(description="A short title naming the missing information.")
    category: CategoryName
    customer_can_answer: bool = Field(
        description=(
            "False only when nobody can answer this before the work starts: the customer says "
            "it is unknown, uncertain or undocumented, or asks for an allowance for it. True for "
            "information the customer holds and for any decision they still have to make."
        )
    )
    """Comes before `why_it_matters` so the model decides it first; the gaps module marks the
    stored `why_it_matters` of a Gap the customer cannot answer, which the estimating agent
    reads to propose a Contingency."""
    why_it_matters: str = Field(description="Which part of the estimate this would change.")
    impact: ImpactName
    impact_basis: str = Field(description="Why the impact is high, medium or low.")
    related: list[str] = Field(
        description="Labels of the Requirements this Gap is about, e.g. ['R1', 'R4']."
    )
    question: DraftQuestion


class ClarificationOutput(_Output):
    gaps: list[GapCandidate]
