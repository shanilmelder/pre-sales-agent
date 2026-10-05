"""`pm_agent`'s output schema: the shared specialist shape
(`app.agents.specialist.schema`), the JSON object the model must return and what goes in
`AgentResult.extensions["pm_agent"]`."""

from app.agents.specialist.schema import SpecialistOutput


class PmOutput(SpecialistOutput):
    """The PM Agent's Assessment: recommendation, confidence with its basis, Findings
    citing Requirements, and effort per Requirement."""
