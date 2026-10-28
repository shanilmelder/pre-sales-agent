"""Reporting: failed Assumptions with their wording (Story 10.4; FR-50).

`reporting_failed_assumptions` is recreated with the Assumption's register number
(`assumption_position`, "A{n}"), wording (`assumption_wording`) and Contingency hours
(`assumption_amount_hours`, null for a Condition), so Reports can list a group's failed
Assumptions. The other columns are unchanged.

`DROP VIEW` + `CREATE VIEW` (not `CREATE OR REPLACE`: the new columns sit beside the old
ones), so the grants are repeated: `psa_app` may only SELECT it, with INSERT, UPDATE, DELETE
and TRUNCATE revoked again because the default privileges from 0002 grant them. The downgrade
restores the 0055 view.

Revision ID: 0056_reporting_failed_wording
Revises: 0055_reporting_views
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0056_reporting_failed_wording"
down_revision: str | None = "0055_reporting_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
FAILED_ASSUMPTIONS = "reporting_failed_assumptions"

FAILED_ASSUMPTIONS_SQL = """
CREATE VIEW reporting_failed_assumptions AS
SELECT
    a.id AS actual_id,
    a.opportunity_id,
    a.estimate_version_id,
    CAST(ref ->> 'assumption_id' AS uuid) AS assumption_id,
    CAST(ref ->> 'version' AS integer) AS assumption_version,
    ea.kind AS assumption_kind,
    ea.position AS assumption_position,
    ea.wording AS assumption_wording,
    ea.amount_hours AS assumption_amount_hours
FROM actuals_actuals a
CROSS JOIN LATERAL jsonb_array_elements(a.failed_assumptions) AS ref
LEFT JOIN estimates_assumptions ea ON ea.id = CAST(ref ->> 'assumption_id' AS uuid)
WHERE a.is_current
"""

# The 0055 definition, restored by the downgrade.
FAILED_ASSUMPTIONS_0055_SQL = """
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


def _recreate(sql: str) -> None:
    op.execute(f"DROP VIEW {FAILED_ASSUMPTIONS}")
    op.execute(sql)
    op.execute(f"GRANT SELECT ON {FAILED_ASSUMPTIONS} TO {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {FAILED_ASSUMPTIONS} FROM {APP_ROLE}")


def upgrade() -> None:
    _recreate(FAILED_ASSUMPTIONS_SQL)


def downgrade() -> None:
    _recreate(FAILED_ASSUMPTIONS_0055_SQL)
