"""The `reporting` module (Epic 10): derived, read-only reports across Opportunities.

Story 10.3: **Estimate vs actual**, aggregated in SQL over the read-only `reporting_*` views
(`reporting_estimate_vs_actual`, `reporting_failed_assumptions`), for holders of
`reporting.report.read` (Head of Delivery and platform administrators), restricted to the
Opportunities the caller can read before aggregating.

It owns no table and never writes. It uses `identity`, `opportunities` and `actuals` only
through their public APIs.
"""
