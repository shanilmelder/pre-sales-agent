"""The `assessments` module (Epic 6): Reviews of an Opportunity and their Findings.

Demo scope (Story 6.5): after every stored Estimate Version an `assessments.red_team_review`
job asks `red_team_agent` to argue the Opportunity is harder than it looks, and
`assessments.accept_red_team_review` stores a Red Team Review with specific, severity-ranked
Findings, each citing the Requirements (and optionally the Estimate lines) it challenges.
Epic 5 slice 5A: the Engineering, PM and Security Agents assess the Opportunity in parallel
(as the tasks of a Workflow Run, owned by `workflows` since Story 5.2); each result is
accepted by `assessments.accept_assessment` as the agent's new Assessment (recommendation,
confidence, Findings citing Requirements, effort per Requirement).

Read-only: no resolving or overriding. Other modules use it only through
`application/public.py`.
"""
