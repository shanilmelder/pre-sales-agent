"""Alert emails (Story 7.4), sent through Resend by the `platform.alert_email` job.

- `email` — `AlertEmail` and `send_alert`, the Resend API client (httpx).
- `jobs` — the `platform.alert_email` job type and `ToolDenialAlert`, its payload.

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
from app.platform.alerts.jobs import ALERT_EMAIL, ToolDenialAlert, denial_alert_email

__all__ = [
    "ALERT_EMAIL",
    "RESEND_URL",
    "AlertEmail",
    "AlertEmailRejectedError",
    "AlertEmailUnavailableError",
    "ToolDenialAlert",
    "denial_alert_email",
    "send_alert",
]
