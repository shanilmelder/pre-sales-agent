"""The `assessments` module (Epic 6): Reviews of an Opportunity and their Findings.

Demo scope (Story 6.5): after every stored Estimate Version an `assessments.red_team_review`
job asks `red_team_agent` to argue the Opportunity is harder than it looks, and
`assessments.accept_red_team_review` stores a Red Team Review with specific, severity-ranked
Findings, each citing the Requirements (and optionally the Estimate lines) it challenges.
Epic 5 slice 5A: the Engineering, PM and Security Agents assess the Opportunity in parallel
(as the tasks of a Workflow Run, owned by `workflows` since Story 5.2); each result is
accepted by `assessments.accept_assessment` as the agent's new Assessment (recommendation,
confidence, Findings citing Requirements, effort per Requirement).
Story 6.4: every assessment run ends with a `critic_agent` task, and
`assessments.accept_critic_review` stores a versioned Critic Review whose Findings cite the
run's specialist Findings (at their Assessment version) or Requirements; its contradictions
become Conflicts (`detected_by = critic`).

Read-only: no resolving or overriding. Other modules use it only through
`application/public.py`.
"""
