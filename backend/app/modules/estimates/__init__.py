"""The `estimates` module (Epic 8): Estimates, their Versions and lines.

Demo scope (Story 8.1 + 8.2 + 8.3): after every successful Gap detection an
`estimates.draft_estimate` job asks `estimating_agent` to group the Opportunity's active
Requirements into work items with effort and a role mix, and `estimates.accept_draft` stores
them as a new `draft` Estimate Version. Every total is calculated by the pure functions in
`domain/arithmetic.py`, never by the model. Other modules use it only through
`application/public.py`.
"""
