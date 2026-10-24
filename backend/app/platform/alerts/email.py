"""The Resend client for alert emails (Story 7.4).

`send_alert` POSTs one plain-text email to `https://api.resend.com/emails` with
`Authorization: Bearer <PSA_RESEND_API_KEY>`, from `PSA_ALERT_EMAIL_FROM` to every address in
`PSA_ALERT_EMAIL_TO`. When any of the three is unset it logs `alerts.email_not_configured`
and sends nothing (returns False). A network error, a 5xx, 408 or 429 raises
`AlertEmailUnavailableError` (the job retries); any other non-2xx raises
`AlertEmailRejectedError` (a `PermanentJobError`: retrying can't fix it). Bodies hold ids
only; logs hold the status code, never the body or the key.
"""

from dataclasses import dataclass

import httpx

from app.platform.config import Settings
from app.platform.jobs.registry import PermanentJobError
from app.platform.logging import get_logger

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_S = 10.0
_log = get_logger(__name__)


class AlertEmailUnavailableError(Exception):
    """Resend could not be reached or answered 5xx, 408 or 429: retry later."""


class AlertEmailRejectedError(PermanentJobError):
    """Resend refused the email (another 4xx): retrying sends the same request again."""


@dataclass(frozen=True, slots=True)
class AlertEmail:
    subject: str
    text: str


def configured(settings: Settings) -> bool:
    key = settings.resend_api_key
    return bool(
        key is not None
        and key.get_secret_value().strip()
        and (settings.alert_email_from or "").strip()
        and settings.alert_email_to
    )


async def send_alert(
    settings: Settings,
    email: AlertEmail,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Send `email` to the alert recipients; False when alert email is not configured.
    `transport` replaces the network (tests pass an `httpx.MockTransport`)."""
    if not configured(settings):
        _log.warning(
            "alerts.email_not_configured",
            extra={"missing": _missing(settings), "subject": email.subject},
        )
        return False
    assert settings.resend_api_key is not None and settings.alert_email_from is not None
    headers = {"Authorization": f"Bearer {settings.resend_api_key.get_secret_value().strip()}"}
    body = {
        "from": settings.alert_email_from.strip(),
        "to": list(settings.alert_email_to),
        "subject": email.subject,
        "text": email.text,
    }
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S) as client:
            response = await client.post(RESEND_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        _log.warning("alerts.email_unreachable", extra={"exc_type": type(exc).__name__})
        raise AlertEmailUnavailableError(type(exc).__name__) from None
    status = response.status_code
    if status >= 500 or status in (408, 429):  # temporary: retry later
        _log.warning("alerts.email_failed", extra={"http_status": status})
        raise AlertEmailUnavailableError(f"Resend answered {status}")
    if not response.is_success:
        _log.error("alerts.email_rejected", extra={"http_status": status})
        raise AlertEmailRejectedError(f"Resend answered {status}")
    _log.info(
        "alerts.email_sent",
        extra={"http_status": status, "recipient_count": len(settings.alert_email_to)},
    )
    return True


def _missing(settings: Settings) -> list[str]:
    missing = []
    key = settings.resend_api_key
    if key is None or not key.get_secret_value().strip():
        missing.append("PSA_RESEND_API_KEY")
    if not (settings.alert_email_from or "").strip():
        missing.append("PSA_ALERT_EMAIL_FROM")
    if not settings.alert_email_to:
        missing.append("PSA_ALERT_EMAIL_TO")
    return missing
