"""`opportunity_intake_agent`'s output schema: the JSON object the model must return, sent to
the ModelGateway as the `format`. The same shape goes in
`AgentResult.extensions["opportunity_intake_agent"]`.

Text fields carry no limits here: the opportunities module re-validates every suggestion
against the New Opportunity form's own rules and drops what fails, instead of failing the
whole reply.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuggestedField(_Output):
    value: str | None = Field(
        description="The suggested value, or null when the text doesn't support one."
    )
    quote: str | None = Field(
        description="The short passage of the text, copied exactly, that the value comes "
        "from; null when value is null."
    )


class SuggestedProduct(_Output):
    value: str = Field(description="A product, system or solution in scope.")
    quote: str = Field(description="The short passage, copied exactly, that names it.")


class OpportunityIntakeOutput(_Output):
    title: SuggestedField = Field(description="A short name for the opportunity.")
    customer_name: SuggestedField = Field(
        description="The buying organisation: never the vendor, never a person."
    )
    industry: SuggestedField = Field(
        description="The customer's industry: named in the text, or inferred from what the "
        "customer does."
    )
    industry_inferred: bool = Field(
        default=False,
        description="True when the text doesn't name the industry and it was inferred from "
        "what the customer does (the quote is the passage it was inferred from).",
    )
    products: list[SuggestedProduct] = Field(description="0 to 5 products in scope.")
    target_proposal_date: SuggestedField = Field(
        description="The proposal deadline as YYYY-MM-DD, only if the text states one."
    )
