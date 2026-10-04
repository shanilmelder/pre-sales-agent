"""Proposal-only agents (AD-4, AD-5).

`contract.py` holds the agent contract (`AgentResult`, `Agent`, `AgentConfig`); each agent
has its own package: `<agent_id>/agent.py`, `schema.py`, `prompts/v<N>.md`. Agents never
import `langgraph` and never write business state.
"""
