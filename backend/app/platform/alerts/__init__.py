"""Alert emails (Story 7.4), sent through Resend by the `platform.alert_email` job.

- `email` — `AlertEmail` and `send_alert`, the Resend API client (httpx).
- `jobs` — the `platform.alert_email` job type and its payload, `AlertEmailJob`: one
  `ToolDenialAlert` (Story 7.4) or `PurgeFailedAlert` (Story 10.6).

Commands enqueue the job in their own Unit of Work (an outbox through the job queue), so an
alert is queued exactly when the change that raised it commits.
"""

from app.platform.alerts.email import (
    RESEND_URL,
    AlertEmail,
    AlertEmailRejectedError,
    AlertEmailUnavailableError,
    send_alert,
)
from app.platform.alerts.jobs import (
    ALERT_EMAIL,
    AlertEmailJob,
    PurgeFailedAlert,
    ToolDenialAlert,
    denial_alert_email,
    purge_alert_email,
)

__all__ = [
    "ALERT_EMAIL",
    "RESEND_URL",
    "AlertEmail",
    "AlertEmailJob",
    "AlertEmailRejectedError",
    "AlertEmailUnavailableError",
    "PurgeFailedAlert",
    "ToolDenialAlert",
    "denial_alert_email",
    "purge_alert_email",
    "send_alert",
]
