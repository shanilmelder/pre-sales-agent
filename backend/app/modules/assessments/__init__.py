"""The `assessments` module (Epic 6): Reviews of an Opportunity and their Findings.

Demo scope (Story 6.5): after every accepted Estimate draft an `assessments.red_team_review`
job asks `red_team_agent` to argue the Opportunity is harder than it looks, and
`assessments.accept_red_team_review` stores a Red Team Review with specific, severity-ranked
Findings, each citing the Requirements (and optionally the Estimate lines) it challenges.
Read-only: no resolving or overriding. Other modules use it only through
`application/public.py`.
"""
