"""Blocking Findings and overrides (Story 6.6).

`assessments_findings` (Critic and Red Team Findings) gains:

- `status` (`open | resolved | overridden`, default `open`), `resolution` (JSONB, set only
  when `resolved`) and `row_version` (default 1): the only columns `psa_app` may UPDATE;
- `fingerprint` (NOT NULL): SHA-256 of the Review kind, category, sorted cited Requirement
  ids and (Red Team) the cited Estimate lines' keys or (Critic) the cited specialist Finding
  ids. Existing rows are backfilled here with a literal copy of
  `app.modules.assessments.domain.findings.fingerprint` (a test keeps them equal);
- `security_discipline` (default false; backfilled: a Critic Finding citing a Security
  Agent Finding), `policy_ref` (JSONB, the mandatory security Checklist item that makes it
  not overridable; null for existing rows) and `previous_override_id` (an override of an
  earlier Finding with the same fingerprint; no foreign key).

New insert-only tables (`psa_app`: SELECT, INSERT): `assessments_finding_overrides` (the
Finding, the Review kind and version, who, why, the policy basis, when) and
`assessments_finding_evidence` (the Evidence references a person supplied: `requirement` or
`source_document`, with a version). A Finding is overridden at most once (unique index).

Revision ID: 0042_blocking_findings
Revises: 0041_critic_review
Create Date: 2026-10-24
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_blocking_findings"
down_revision: str | None = "0041_critic_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
FINDINGS = "assessments_findings"
OVERRIDES = "assessments_finding_overrides"
EVIDENCE = "assessments_finding_evidence"
UPDATABLE = ("status", "resolution", "row_version")
CHECKS = {
    "ck_assessments_findings_status": "status IN ('open', 'resolved', 'overridden')",
    "ck_assessments_findings_resolved_has_resolution": (
        "(status = 'resolved') = (resolution IS NOT NULL)"
    ),
    "ck_assessments_findings_row_version": "row_version >= 1",
}


def fingerprint(
    kind: str, category: str, requirement_ids: Iterable[object], keys: Iterable[str] = ()
) -> str:
    """A literal copy of `app.modules.assessments.domain.findings.fingerprint`."""
    parts = [
        kind,
        category,
        ",".join(sorted(str(r) for r in requirement_ids)),
        ",".join(sorted(keys)),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def line_key(section: str, title: str) -> str:
    """A literal copy of `app.modules.assessments.domain.findings.line_key`."""
    return f"{section.strip().casefold()}:{' '.join(title.split()).casefold()}"


def _backfill() -> None:
    bind = op.get_bind()
    findings = bind.execute(
        sa.text(
            "SELECT f.id, f.category, r.kind FROM assessments_findings f "
            "JOIN assessments_reviews r ON r.id = f.review_id"
        )
    ).all()
    requirements: dict[object, list[object]] = defaultdict(list)
    for finding_id, requirement_id in bind.execute(
        sa.text("SELECT finding_id, requirement_id FROM assessments_finding_requirements")
    ):
        requirements[finding_id].append(requirement_id)
    keys: dict[object, list[str]] = defaultdict(list)
    for finding_id, section, title in bind.execute(
        sa.text(
            "SELECT fl.finding_id, l.section, l.title FROM assessments_finding_lines fl "
            "JOIN estimates_estimate_lines l ON l.id = fl.line_id"
        )
    ):
        keys[finding_id].append(line_key(section, title))
    for finding_id, target in bind.execute(
        sa.text("SELECT finding_id, assessment_finding_id FROM assessments_finding_targets")
    ):
        keys[finding_id].append(str(target))
    for finding_id, category, kind in findings:
        bind.execute(
            sa.text("UPDATE assessments_findings SET fingerprint = :fp WHERE id = :id"),
            {
                "fp": fingerprint(kind, category, requirements[finding_id], keys[finding_id]),
                "id": finding_id,
            },
        )
    bind.execute(
        sa.text(
            "UPDATE assessments_findings f SET security_discipline = true WHERE EXISTS ("
            "SELECT 1 FROM assessments_finding_targets t "
            "JOIN assessments_assessments a ON a.id = t.assessment_id "
            "WHERE t.finding_id = f.id AND a.agent = 'security_agent')"
        )
    )


def upgrade() -> None:
    op.add_column(
        FINDINGS, sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False)
    )
    op.add_column(FINDINGS, sa.Column("fingerprint", sa.Text(), nullable=True))
    op.add_column(
        FINDINGS,
        sa.Column(
            "security_discipline", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(FINDINGS, sa.Column("policy_ref", postgresql.JSONB(), nullable=True))
    op.add_column(FINDINGS, sa.Column("previous_override_id", sa.Uuid(), nullable=True))
    op.add_column(FINDINGS, sa.Column("resolution", postgresql.JSONB(), nullable=True))
    op.add_column(
        FINDINGS,
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    _backfill()
    op.alter_column(FINDINGS, "fingerprint", nullable=False)
    for name, condition in CHECKS.items():
        op.execute(f"ALTER TABLE {FINDINGS} ADD CONSTRAINT {name} CHECK ({condition})")
    op.create_index("ix_assessments_findings_fingerprint", FINDINGS, ["fingerprint"])

    op.create_table(
        OVERRIDES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("review_kind", sa.Text(), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("overridden_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_basis", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "review_kind IN ('red_team', 'critic')",
            name="ck_assessments_finding_overrides_review_kind",
        ),
        sa.CheckConstraint(
            "policy_basis IN ('owner', 'head_of_delivery', 'security_reviewer')",
            name="ck_assessments_finding_overrides_policy_basis",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            [f"{FINDINGS}.id"],
            name="fk_assessments_finding_overrides_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessments_finding_overrides"),
    )
    op.create_index(
        "uq_assessments_finding_overrides_finding_id", OVERRIDES, ["finding_id"], unique=True
    )
    op.create_table(
        EVIDENCE,
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("ref_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('requirement', 'source_document')",
            name="ck_assessments_finding_evidence_kind",
        ),
        sa.CheckConstraint("position >= 1", name="ck_assessments_finding_evidence_position"),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            [f"{FINDINGS}.id"],
            name="fk_assessments_finding_evidence_finding_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("finding_id", "position", name="pk_assessments_finding_evidence"),
    )

    op.execute(f"GRANT UPDATE ({', '.join(UPDATABLE)}) ON {FINDINGS} TO {APP_ROLE}")
    for table in (OVERRIDES, EVIDENCE):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({', '.join(UPDATABLE)}) ON {FINDINGS} FROM {APP_ROLE}")
    op.drop_table(EVIDENCE)
    op.drop_index("uq_assessments_finding_overrides_finding_id", table_name=OVERRIDES)
    op.drop_table(OVERRIDES)
    op.drop_index("ix_assessments_findings_fingerprint", table_name=FINDINGS)
    for name in CHECKS:
        op.execute(f"ALTER TABLE {FINDINGS} DROP CONSTRAINT {name}")
    for column in (
        "row_version",
        "resolution",
        "previous_override_id",
        "policy_ref",
        "security_discipline",
        "fingerprint",
        "status",
    ):
        op.drop_column(FINDINGS, column)
