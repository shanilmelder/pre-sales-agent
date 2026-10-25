"""The `platform.alert_email` job (Story 7.4): one alert email per payload, via Resend.

The ToolGateway enqueues `ToolDenialAlert` in the Unit of Work that traced
`platform.tool_call.denial_threshold_exceeded`, so the email is queued only if that commits.
The email holds ids and counts only: the run, the Opportunity, the run-wide denial count and
threshold, the Agent whose call passed it (`<agent_id>@<semver>`), and a link to the denial
list filtered to the run's days (every Agent). Unconfigured email completes the job without
sending; Resend 5xx, 408, 429 or network errors retry it; any other 4xx fails it permanently
(`dead`).
"""

from datetime import date
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx

from app.platform.alerts.email import AlertEmail, send_alert
from app.platform.config import get_settings
from app.platform.jobs.registry import JobContext, JobPayload, JobType, register

DENIALS_PATH = "/admin/agents/denials"
_transport: httpx.AsyncBaseTransport | None = None
"""Replaces the network in tests (an `httpx.MockTransport`); None in the app."""


class ToolDenialAlert(JobPayload):
    """A run passed the denied-tool-call threshold. Ids and counts only."""

    kind: Literal["tool_denial_threshold"] = "tool_denial_threshold"
    run_id: UUID
    opportunity_id: UUID
    agent_id: str
    semver: str
    denial_count: int
    threshold: int
    day_from: date
    """The UTC day of the run's first denied call (the link's `from`)."""
    day_to: date
    """The UTC day of the denial that passed the threshold (the link's `to`)."""


def denial_alert_email(payload: ToolDenialAlert, web_base_url: str) -> AlertEmail:
    query = urlencode({"from": payload.day_from.isoformat(), "to": payload.day_to.isoformat()})
    link = f"{web_base_url.rstrip('/')}{DENIALS_PATH}?{query}"
    actor = f"{payload.agent_id}@{payload.semver}"
    return AlertEmail(
        subject=f"[PSA] A run passed {payload.threshold} denied tool calls",
        text=(
            f"A run passed {payload.threshold} denied tool calls (all its Agents).\n\n"
            f"Run: {payload.run_id}\n"
            f"Opportunity: {payload.opportunity_id}\n"
            f"Denied calls in the run: {payload.denial_count} "
            f"(threshold {payload.threshold})\n"
            f"Last denied call: {actor}\n\n"
            f"Denied tool calls: {link}\n"
        ),
    )


async def alert_email(ctx: JobContext, payload: ToolDenialAlert) -> None:
    settings = get_settings()
    await send_alert(
        settings, denial_alert_email(payload, settings.web_base_url), transport=_transport
    )


ALERT_EMAIL = register(
    JobType(
        name="platform.alert_email",
        payload=ToolDenialAlert,
        handler=alert_email,
        priority="background",
        timeout_s=60.0,
        max_attempts=5,
    )
)
