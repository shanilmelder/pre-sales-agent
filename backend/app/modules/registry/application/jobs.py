"""registry's job type: `registry.test_model_profile`, a custom chat model profile's live test.

Only the worker has the provider keys, and the `api` process never makes a chat call, so the
create and retest commands enqueue this job (`enqueue_profile_test`) in their own Unit of Work.

The handler sends one fixed, non-customer prompt through the process's ModelGateway, with no
Unit of Work open, then records the state (`verified` or `failed`), error code and latency and
appends `registry.model_profile.tested`, in one Unit of Work. The reply is only validated: it
is never stored, traced or logged. The gateway writes the usual `platform_model_calls` row, with
the fixed agent id `model_profile_test`.

A model error (timeout, HTTP error, invalid output) is the test's result, so it isn't retried.
Anything else (the database, a stopping worker) raises so the queue retries; on the final
attempt the profile is first marked `failed` (`test_error`), best effort.

Idempotent: only an `untested` profile is tested, and only an `untested` one takes the result,
so a redelivered job or a profile retired during the call changes nothing.
"""

import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.registry.adapters import repository as repo
from app.modules.registry.domain.model_profiles import SUBJECT_TYPE, CustomProfile, ProfileState
from app.platform import trace
from app.platform.actor import Actor
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    CallerMetadata,
    Message,
    ModelGatewayError,
    StructuredRequest,
)
from app.platform.trace.catalogue import RegistryModelProfileTested
from app.platform.uow import UnitOfWork, unit_of_work

TEST_PROFILE = "registry.test_model_profile"
TEST_AGENT_ID = "model_profile_test"
"""`platform_model_calls.agent_id` of a test call: a free-text column with no constraint."""
TEST_CONFIG_VERSION = "0"
TEST_TIMEOUT_S = 90.0
"""One attempt. The gateway may make 3 for invalid output, all inside the job's 300 s."""
TEST_ERROR = "test_error"
TEST_MESSAGES = (
    Message(role="system", content="You answer with JSON only."),
    Message(role="user", content='Reply with exactly this JSON object: {"status": "ok"}.'),
)
_ACTOR = Actor(type="system", id=TEST_PROFILE)
_log = get_logger(__name__)


class ProbeModelProfile(JobPayload):
    profile_id: UUID


class ProbeReply(BaseModel):
    status: Literal["ok"]


async def enqueue_profile_test(uow: UnitOfWork, profile_id: UUID) -> UUID:
    """Queue the profile's test in the caller's Unit of Work."""
    return await enqueue(uow, ProbeModelProfile(profile_id=profile_id))


async def _record(
    ctx: JobContext, profile: CustomProfile, error_code: str | None, latency_ms: int
) -> None:
    state = ProfileState.VERIFIED if error_code is None else ProfileState.FAILED
    async with unit_of_work(ctx.engine) as uow:
        changed = await repo.record_model_profile_test(
            uow, profile.id, state=state, error_code=error_code, latency_ms=latency_ms
        )
        if not changed:
            _log.info("registry.model_profile_test_ignored", extra={"profile": profile.name})
            return
        await trace.append(
            uow,
            actor=_ACTOR,
            payload=RegistryModelProfileTested(
                profile_id=str(profile.id),
                name=profile.name,
                state="verified" if error_code is None else "failed",
                error_code=error_code,
                latency_ms=latency_ms,
            ),
            subject_type=SUBJECT_TYPE,
            subject_id=profile.id,
        )
    _log.info(
        "registry.model_profile_tested",
        extra={
            "profile": profile.name,
            "state": state.value,
            "error_code": error_code,
            "latency_ms": latency_ms,
        },
    )


async def probe_profile(ctx: JobContext, payload: ProbeModelProfile) -> None:
    async with unit_of_work(ctx.engine) as uow:
        profile = await repo.get_model_profile(uow, payload.profile_id)
    if profile is None or profile.state != ProfileState.UNTESTED:
        return
    request = StructuredRequest(
        messages=TEST_MESSAGES,
        output_model=ProbeReply,
        caller=CallerMetadata(agent_id=TEST_AGENT_ID, config_version=TEST_CONFIG_VERSION),
        profile=profile.name,
        priority="interactive",
        timeout_s=TEST_TIMEOUT_S,
    )
    started = time.perf_counter()
    try:
        result = await provider.current().complete_structured(request)
    except ModelGatewayError as exc:
        await _record(ctx, profile, exc.error_code, round((time.perf_counter() - started) * 1000))
        return
    except Exception:
        if ctx.attempt >= ctx.max_attempts:
            elapsed = round((time.perf_counter() - started) * 1000)
            await _record(ctx, profile, TEST_ERROR, elapsed)
        raise
    await _record(ctx, profile, None, result.latency_ms)


TEST_MODEL_PROFILE = register(
    JobType(
        name=TEST_PROFILE,
        payload=ProbeModelProfile,
        handler=probe_profile,
        priority="interactive",
    )
)
