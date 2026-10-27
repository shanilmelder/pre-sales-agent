"""The `actuals` module (Epic 10): what delivery actually took.

Story 10.1: a delivery manager records Actuals against each line of the Opportunity's
Baseline Estimate Version (or as Unplanned work with no line), each with a variance cause;
corrections make new versions; **Close delivery** records that every line has a final
Actual, which makes the Opportunity `delivered`.

It owns `actuals_actuals` and `actuals_deliveries`, reads Estimate data only through
`estimates.public`, and other modules use it only through `application/public.py`.
"""
