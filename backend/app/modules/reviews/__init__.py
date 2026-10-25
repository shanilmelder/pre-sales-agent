"""The `reviews` module (Epic 9): Review Requests, and later their decisions and Challenges.

Story 9.1: the presales engineer sends a submitted Estimate Version (or some of its
Assessments) to named reviewers who hold the review type's role; each gets read-only
collaboration on the Opportunity while a request is pending. A sender (or the owner) can
cancel a pending request with a reason. Open requests are the `to_baseline` group of
`estimates.get_submission_blockers`.

Other modules use it only through `application/public.py`.
"""
