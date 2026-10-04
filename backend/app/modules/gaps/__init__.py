"""The `gaps` module (Epic 4): Gaps and their Clarification Questions.

Demo scope (Story 4.3 + 4.4): after every successful Requirement extraction a
`gaps.detect_gaps` job runs `clarification_agent` over the Opportunity's active Requirements,
and `gaps.accept_gap_detection` stores ranked Gaps, each with a drafted Clarification
Question. Other modules use it only through `application/public.py`.
"""
