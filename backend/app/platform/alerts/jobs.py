"""The `platform.alert_email` job (Story 7.4): one alert email per payload, via Resend.

The payload (`AlertEmailJob`) holds one alert, a union discriminated by `kind`, stored flat in
`platform_jobs.payload` (the alert's own fields, `kind` among them):

- `tool_denial_threshold` (`ToolDenialAlert`, Story 7.4), below;
- `purge_failed` (`PurgeFailedAlert`, Story 10.6): the retention purge's last attempt still
  failed for some Opportunities. Counts and Opportunity UUIDs only, and a link to Admin >
  Retention.

The ToolGateway enqueues `ToolDenialAlert` in the Unit of Work that traced
`platform.tool_call.denial_threshold_exceeded`, so the email is queued only if that commits.
The email holds ids and counts only: the run, the Opportunity, the run-wide denial count and
threshold, the Agent whose call passed it (`<agent_id>@<semver>`), and a link to the denial
list filtered to the run's days (every Agent). Unconfigured email completes the job without
sending; Resend 5xx, 408, 429 or network errors retry it; any other 4xx fails it permanently
(`dead`).
"""

from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from app.platform.alerts.email import AlertEmail, send_alert
from app.platform.config import get_settings
from app.platform.jobs.registry import JobContext, JobPayload, JobType, register

DENIALS_PATH = "/admin/agents/denials"
RETENTION_PATH = "/admin/retention"
MAX_LISTED_IDS = 50
"""The most Opportunity UUIDs a purge alert lists; the count covers the rest."""
_transport: httpx.AsyncBaseTransport | None = None
"""Replaces the network in tests (an `httpx.MockTransport`); None in the app."""


class _Alert(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolDenialAlert(_Alert):
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


class PurgeFailedAlert(_Alert):
    """Story 10.6: the `platform.purge` job's last attempt still failed for some Opportunities
    (each rolled back on its own; the others were purged). Counts and UUIDs only."""

    kind: Literal["purge_failed"] = "purge_failed"
    failed_count: int
    failed_opportunity_ids: list[UUID] = Field(max_length=MAX_LISTED_IDS)
    """The first `MAX_LISTED_IDS` that failed."""
    purged_count: int
    attempts: int


Alert = Annotated[ToolDenialAlert | PurgeFailedAlert, Field(discriminator="kind")]


class AlertEmailJob(JobPayload):
    """One alert. Stored flat: the alert's own fields (`kind` among them), so rows queued
    before the union existed (a flat `ToolDenialAlert`) still load."""

    alert: Alert

    @model_validator(mode="before")
    @classmethod
    def _wrap_flat(cls, data: Any) -> Any:
        if isinstance(data, dict) and "alert" not in data:
            return {"alert": data}
        return data

    @model_serializer(mode="wrap")
    def _flatten(self, handler: SerializerFunctionWrapHandler) -> Any:
        return handler(self)["alert"]


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


def purge_alert_email(payload: PurgeFailedAlert, web_base_url: str) -> AlertEmail:
    link = f"{web_base_url.rstrip('/')}{RETENTION_PATH}"
    if payload.failed_count == 0:  # the run itself failed (e.g. the purge role can't connect)
        return AlertEmail(
            subject="[PSA] The retention purge could not run",
            text=(
                f"The daily retention purge gave up after {payload.attempts} attempts without "
                f"purging anything: it could not list the Opportunities due. Check the worker "
                f"logs (`purge.*`) and PSA_PURGE_DATABASE_URL.\n\nRetention: {link}\n"
            ),
        )
    listed = "".join(f"- {opportunity_id}\n" for opportunity_id in payload.failed_opportunity_ids)
    more = payload.failed_count - len(payload.failed_opportunity_ids)
    if more > 0:
        listed += f"- and {more} more\n"
    return AlertEmail(
        subject=f"[PSA] The retention purge failed for {payload.failed_count} Opportunities",
        text=(
            f"The daily retention purge gave up after {payload.attempts} attempts. "
            f"{payload.failed_count} Opportunities past their retention date were not purged "
            f"(each was rolled back); {payload.purged_count} were purged.\n\n"
            f"Not purged:\n{listed}\n"
            f"The next daily run tries them again. Retention: {link}\n"
        ),
    )


def alert_email_for(payload: AlertEmailJob, web_base_url: str) -> AlertEmail:
    alert = payload.alert
    if isinstance(alert, PurgeFailedAlert):
        return purge_alert_email(alert, web_base_url)
    return denial_alert_email(alert, web_base_url)


async def alert_email(ctx: JobContext, payload: AlertEmailJob) -> None:
    settings = get_settings()
    await send_alert(
        settings, alert_email_for(payload, settings.web_base_url), transport=_transport
    )


ALERT_EMAIL = register(
    JobType(
        name="platform.alert_email",
        payload=AlertEmailJob,
        handler=alert_email,
        priority="background",
        timeout_s=60.0,
        max_attempts=5,
    )
)
