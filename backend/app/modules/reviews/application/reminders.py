"""Review reminders (Story 9.2): the daily `reviews.send_reminders` job, enqueued from its
`platform_schedules` row.

For each `pending` Review Request whose age is at least N intervals
(`PSA_REVIEW_REMINDER_DAYS`, default 3; N >= 1), the reviewer gets a `review_reminder` Inbox
item with key `review:{id}:reminder:{N}`. Only when that item was written is
`reviews.review_request.reminded` traced (request id, reviewer id, interval number), so a
rerun on the same day sends and traces nothing. Decided, superseded and cancelled requests
are not pending, so they get none. Idempotent, in one short Unit of Work.
"""

from datetime import timedelta
from uuid import UUID

from app.modules.notifications.application.public import NotificationKind
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.application.requests import (
    notify_reviewer,
    opportunity_title,
    target_labels,
)
from app.modules.reviews.domain.requests import SUBJECT_TYPE
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.jobs import JobContext, JobPayload, JobType, register
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ReviewsReviewRequestReminded
from app.platform.uow import UnitOfWork, unit_of_work

SEND_REMINDERS = "reviews.send_reminders"
SYSTEM = Actor(type="system", id=SEND_REMINDERS)
_DAY_S = 86_400
_log = get_logger(__name__)


def reminder_settings() -> Settings:
    """Settings for the job (the reminder interval). Tests replace this."""
    return get_settings()


def interval_number(age: timedelta, interval_s: int) -> int:
    """How many whole intervals old a request is (0 before the first)."""
    return int(age.total_seconds() // interval_s)


async def send_due_reminders(uow: UnitOfWork, interval_days: int) -> int:
    """Remind the reviewers of pending requests at least one interval old; how many items
    were written."""
    interval_s = interval_days * _DAY_S
    now, records = await repo.pending_for_reminders(uow, interval_s)
    labels = await target_labels(uow, records)
    titles: dict[UUID, str | None] = {}
    sent = 0
    for record in records:
        number = interval_number(now - record.created_at, interval_s)
        if number < 1:  # pragma: no cover - the query keeps only requests one interval old
            continue
        if record.opportunity_id not in titles:
            titles[record.opportunity_id] = await opportunity_title(uow, record.opportunity_id)
        written = await notify_reviewer(
            uow,
            kind=NotificationKind.REVIEW_REMINDER,
            request_id=record.id,
            reviewer_id=record.reviewer_id,
            row_version=record.row_version,
            target_label=labels[record.id],
            opportunity_id=record.opportunity_id,
            title=titles[record.opportunity_id],
            dedupe_key=f"review:{record.id}:reminder:{number}",
        )
        if not written:
            continue
        sent += 1
        await trace.append(
            uow,
            actor=SYSTEM,
            payload=ReviewsReviewRequestReminded(
                request_id=str(record.id),
                reviewer_id=str(record.reviewer_id),
                interval_number=number,
            ),
            subject_type=SUBJECT_TYPE,
            subject_id=record.id,
            opportunity_id=record.opportunity_id,
            subject_version=record.row_version,
        )
    return sent


class SendReminders(JobPayload):
    """No fields: the job reminds about every pending request that is due."""


async def send_reminders(ctx: JobContext, payload: SendReminders) -> None:
    days = reminder_settings().review_reminder_days
    async with unit_of_work(ctx.engine) as uow:
        sent = await send_due_reminders(uow, days)
    _log.info("reviews.reminders_sent", extra={"sent_count": sent, "interval_days": days})


SEND_REMINDERS_JOB = register(
    JobType(
        name=SEND_REMINDERS,
        payload=SendReminders,
        handler=send_reminders,
        priority="background",
        timeout_s=300.0,
        max_attempts=3,
    )
)
