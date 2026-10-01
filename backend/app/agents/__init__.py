"""Proposal-only agents (AD-4, AD-5).

Will hold `contract.py` (the `AgentResult` base model) and one package per agent:
`<agent_id>/agent.py`, `schemas.py`, `prompts/v<N>.md`. Agents never import `langgraph`
and never write business state. Empty until the agent epics.
"""
