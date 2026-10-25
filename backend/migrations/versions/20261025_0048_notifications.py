"""Inbox items and review reminders (Story 9.2).

- `notifications_notifications`: one Inbox item per recipient and `dedupe_key` (unique), for
  the `in_app` channel. `psa_app` gets SELECT, INSERT and UPDATE (marking read); no DELETE.
  Indexed by recipient, read state and time for the Inbox and its unread count.
- A `platform_schedules` row enqueues the `reviews.send_reminders` job daily.
- Back-fill, with the keys the live producers use (so a rerun, or a later live insert, writes
  nothing): a `review_requested` item for every pending Review Request; a `run_waiting` item
  for every open decision of a run waiting for a person, to the user who started the run
  (its plan v1's creator, as `workflows.public.run_starter` reads it) or, for a run the
  system queued, the Opportunity's owner; and a
  `conflict_escalated` item for every escalated Conflict, to the reviewer it was escalated
  to. Summaries hold glossary terms, version numbers and the Opportunity's title only.

Revision ID: 0048_notifications
Revises: 0047_reviews_review_requests
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_notifications"
down_revision: str | None = "0047_reviews_review_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
TABLE = "notifications_notifications"
SCHEDULE = "reviews.send_reminders"
DAY_S = 86_400
UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
KINDS = (
    "('review_requested', 'review_reminder', 'review_cancelled', 'run_waiting', "
    "'conflict_escalated')"
)
AGENT_LABEL = """CASE {col}
    WHEN 'engineering_agent' THEN 'Engineering'
    WHEN 'pm_agent' THEN 'PM'
    WHEN 'security_agent' THEN 'Security'
    WHEN 'critic_agent' THEN 'Critic'
    ELSE {col} END"""
TASK_AGENT_LABEL = """CASE t.agent
    WHEN 'engineering_agent' THEN 'Engineering Agent'
    WHEN 'pm_agent' THEN 'PM Agent'
    WHEN 'security_agent' THEN 'Security Agent'
    WHEN 'critic_agent' THEN 'Critic'
    ELSE t.agent END"""


WAITING_RECIPIENT = (
    f"COALESCE(CASE WHEN p.created_by ~ '{UUID_RE}' THEN CAST(p.created_by AS uuid) END, "
    "o.owner_id)"
)
"""A waiting run's recipient: its starter (plan v1's user), else the Opportunity's owner."""


def _summary(head: str) -> str:
    """`head — {title}` (just `head` without a title), on one line, cut to 300 characters
    with an ellipsis as `clean_summary` cuts it."""
    text = f"trim(regexp_replace({head} || COALESCE(' — ' || o.title, ''), '\\s+', ' ', 'g'))"
    return (
        f"CASE WHEN char_length({text}) <= 300 THEN {text} ELSE rtrim(left({text}, 299)) || '…' END"
    )


def _backfill() -> None:
    review_target = (
        "CASE r.target_kind WHEN 'estimate_version' THEN 'Estimate v' || r.target_version "
        f"ELSE COALESCE({AGENT_LABEL.format(col='a.agent')} || ' Assessment', 'Assessment') "
        "|| ' v' || r.target_version END"
    )
    op.execute(
        sa.text(
            f"""
        INSERT INTO {TABLE} (id, recipient_id, kind, opportunity_id, subject_type, subject_id,
            subject_version, summary, dedupe_key, channel, created_at)
        SELECT gen_random_uuid(), r.reviewer_id, 'review_requested', r.opportunity_id,
            'reviews.review_request', r.id, r.row_version,
            {_summary("'Review: ' || " + review_target)},
            'review:' || r.id || :requested, 'in_app', r.created_at
        FROM reviews_review_requests AS r
        LEFT JOIN opportunities_opportunities AS o ON o.id = r.opportunity_id
        LEFT JOIN assessments_assessments AS a
            ON r.target_kind = 'assessment' AND a.id = r.target_id
        WHERE r.status = 'pending'
        ON CONFLICT (dedupe_key) DO NOTHING
        """  # noqa: S608 - module constants only, no input
        ).bindparams(requested=":requested")
    )
    op.execute(
        sa.text(
            f"""
        INSERT INTO {TABLE} (id, recipient_id, kind, opportunity_id, subject_type, subject_id,
            subject_version, summary, dedupe_key, channel, created_at)
        SELECT gen_random_uuid(), {WAITING_RECIPIENT}, 'run_waiting', w.opportunity_id,
            'workflows.decision', d.id, NULL,
            {_summary("'Decision needed: ' || " + TASK_AGENT_LABEL + " || ' is not active'")},
            'decision:' || d.id, 'in_app', d.created_at
        FROM workflows_decisions AS d
        JOIN workflows_runs AS w ON w.id = d.run_id
        JOIN workflows_tasks AS t ON t.id = d.task_id
        LEFT JOIN workflows_plan_versions AS p
            ON p.run_id = w.id AND p.version = 1 AND p.created_by_type = 'user'
        LEFT JOIN opportunities_opportunities AS o ON o.id = w.opportunity_id
        WHERE d.status = 'open' AND w.status = 'waiting_for_human'
            AND {WAITING_RECIPIENT} IS NOT NULL
        ON CONFLICT (dedupe_key) DO NOTHING
        """  # noqa: S608 - module constants only, no input
        )
    )
    op.execute(
        sa.text(
            f"""
        INSERT INTO {TABLE} (id, recipient_id, kind, opportunity_id, subject_type, subject_id,
            subject_version, summary, dedupe_key, channel, created_at)
        SELECT gen_random_uuid(), c.escalated_to, 'conflict_escalated', c.opportunity_id,
            'conflicts.conflict', c.id, c.row_version,
            {_summary("'Conflict escalated: ' || initcap(c.type) || ' Conflict'")},
            'conflict:' || c.id || :escalated
                || CAST(floor(extract(epoch FROM c.escalated_at)) AS bigint),
            'in_app', c.escalated_at
        FROM conflicts_conflicts AS c
        LEFT JOIN opportunities_opportunities AS o ON o.id = c.opportunity_id
        WHERE c.status = 'escalated' AND c.escalated_to IS NOT NULL
        ON CONFLICT (dedupe_key) DO NOTHING
        """  # noqa: S608 - module constants only, no input
        ).bindparams(escalated=":escalated:")
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("subject_version", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), server_default=sa.text("'in_app'"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_notifications_notifications_kind"),
        sa.CheckConstraint("channel IN ('in_app')", name="ck_notifications_notifications_channel"),
        sa.CheckConstraint(
            "char_length(summary) <= 300", name="ck_notifications_notifications_summary"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications_notifications"),
        sa.UniqueConstraint("dedupe_key", name="uq_notifications_notifications_dedupe_key"),
    )
    op.create_index(
        "ix_notifications_notifications_recipient_id_read_at_created_at",
        TABLE,
        ["recipient_id", "read_at", "created_at"],
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {TABLE} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {TABLE} FROM {APP_ROLE}")

    op.execute(
        sa.text(
            "INSERT INTO platform_schedules (name, job_type, interval_s) "
            "VALUES (:name, :name, :interval) ON CONFLICT (name) DO NOTHING"
        ).bindparams(name=SCHEDULE, interval=DAY_S)
    )
    _backfill()


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM platform_schedules WHERE name = :name").bindparams(name=SCHEDULE)
    )
    op.drop_index("ix_notifications_notifications_recipient_id_read_at_created_at", TABLE)
    op.drop_table(TABLE)
