"""The Postgres job queue (AD-29). Commands enqueue with `enqueue(uow, payload)`; modules
register job types with `register(JobType(...))` at import.

The claim loop (`app.platform.jobs.runner`, `app.main_worker`) is deliberately not exported
here: the `api` process imports this package to enqueue but never runs jobs.
"""

from app.platform.jobs.queue import enqueue
from app.platform.jobs.registry import (
    REGISTRY,
    JobContext,
    JobPayload,
    JobType,
    Priority,
    UnknownJobTypeError,
    register,
)

__all__ = [
    "REGISTRY",
    "JobContext",
    "JobPayload",
    "JobType",
    "Priority",
    "UnknownJobTypeError",
    "enqueue",
    "register",
]
