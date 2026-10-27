"""Reporting views (Story 10.3; AD-12): read-only read models that join across modules.

- `reporting_estimate_vs_actual`: one row per current Actual. Its Opportunity (title,
  products), the Close delivery time (`closed_at`, null while delivery is open), the Estimate
  Version it was recorded against (id, number, whether it is the Opportunity's current
  Baseline), the Estimate line (id, "L{n}" label in grid order, title, effort; Unplanned work
  has no line and an estimate of 0), the Actual's effort, kind and cause, its Integration Type
  ids with their current catalogue names (same order), its Work Package and name, and how
  many failed Assumptions it names.
- `reporting_failed_assumptions`: one row per failed-Assumption reference of a current
  Actual, with the version the reference was stored at and the Assumption's kind
  (`condition` or `contingency`).

`psa_app` may only SELECT them: the default privileges from 0002 also grant INSERT, UPDATE
and DELETE on every new relation, so those are revoked explicitly.

Revision ID: 0055_reporting_views
Revises: 0054_actuals_imports
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0055_reporting_views"
down_revision: str | None = "0054_actuals_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
ESTIMATE_VS_ACTUAL = "reporting_estimate_vs_actual"
FAILED_ASSUMPTIONS = "reporting_failed_assumptions"


# Lines are labelled "L{n}" in the Estimate grid's order (`estimates.domain.Section`, then
# position), as the Actuals tab labels them. Every lookup is a correlated subquery on an
# index (catalogue name: pk (entry_id, version); Baseline: (opportunity_id, set_at DESC);
# line rank: the line's version), so a filter on the view's rows narrows the work instead of
# the view first scanning every catalogue entry, Baseline and Estimate line.
SECTION_RANK = """CASE {col}
    WHEN 'functional' THEN 0 WHEN 'integration' THEN 1 WHEN 'data' THEN 2
    WHEN 'security' THEN 3 WHEN 'non_functional' THEN 4 WHEN 'commercial' THEN 5
    ELSE 6 END"""

CATALOGUE_NAME = """(SELECT cv.name FROM knowledge_catalogue_entry_versions cv
        WHERE cv.entry_id = {id} ORDER BY cv.version DESC LIMIT 1)"""

ESTIMATE_VS_ACTUAL_SQL = f"""
CREATE VIEW reporting_estimate_vs_actual AS
SELECT
    a.id AS actual_id,
    a.opportunity_id,
    o.title AS opportunity_title,
    o.products,
    d.closed_at,
    a.estimate_version_id,
    ev.version AS estimate_version,
    COALESCE(
        (SELECT b.estimate_version_id FROM estimates_baselines b
         WHERE b.opportunity_id = a.opportunity_id ORDER BY b.set_at DESC LIMIT 1)
        = a.estimate_version_id,
        false
    ) AS is_baseline,
    a.estimate_line_id AS line_id,
    CASE WHEN l.id IS NOT NULL THEN 'L' || (
        SELECT count(*) FROM estimates_estimate_lines l2
        WHERE l2.version_id = l.version_id
          AND ({SECTION_RANK.format(col="l2.section")}, l2.position, l2.id)
              <= ({SECTION_RANK.format(col="l.section")}, l.position, l.id)
    ) END AS line_label,
    l.title AS line_title,
    CAST(COALESCE(l.effort_hours, 0) AS numeric(10, 1)) AS estimate_hours,
    a.effort_hours AS actual_hours,
    a.kind,
    a.variance_cause,
    a.integration_type_ids,
    ARRAY(
        SELECT COALESCE({CATALOGUE_NAME.format(id="t.id")}, '')
        FROM unnest(a.integration_type_ids) WITH ORDINALITY AS t(id, n)
        ORDER BY t.n
    ) AS integration_type_names,
    a.work_package_id,
    {CATALOGUE_NAME.format(id="a.work_package_id")} AS work_package_name,
    jsonb_array_length(a.failed_assumptions) AS failed_count,
    a.recorded_at
FROM actuals_actuals a
JOIN opportunities_opportunities o ON o.id = a.opportunity_id
JOIN estimates_estimate_versions ev ON ev.id = a.estimate_version_id
LEFT JOIN estimates_estimate_lines l ON l.id = a.estimate_line_id
LEFT JOIN actuals_deliveries d ON d.opportunity_id = a.opportunity_id
WHERE a.is_current
"""

FAILED_ASSUMPTIONS_SQL = """
CREATE VIEW reporting_failed_assumptions AS
SELECT
    a.id AS actual_id,
    a.opportunity_id,
    a.estimate_version_id,
    CAST(ref ->> 'assumption_id' AS uuid) AS assumption_id,
    CAST(ref ->> 'version' AS integer) AS assumption_version,
    ea.kind AS assumption_kind
FROM actuals_actuals a
CROSS JOIN LATERAL jsonb_array_elements(a.failed_assumptions) AS ref
LEFT JOIN estimates_assumptions ea ON ea.id = CAST(ref ->> 'assumption_id' AS uuid)
WHERE a.is_current
"""


def upgrade() -> None:
    op.execute(ESTIMATE_VS_ACTUAL_SQL)
    op.execute(FAILED_ASSUMPTIONS_SQL)
    for view in (ESTIMATE_VS_ACTUAL, FAILED_ASSUMPTIONS):
        op.execute(f"GRANT SELECT ON {view} TO {APP_ROLE}")
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {view} FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP VIEW {FAILED_ASSUMPTIONS}")
    op.execute(f"DROP VIEW {ESTIMATE_VS_ACTUAL}")
