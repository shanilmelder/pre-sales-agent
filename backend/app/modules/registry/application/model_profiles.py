"""Chat model profiles (every one lives here) and the approved-model allowlist: commands and
queries.

Every command and query here needs `registry.model_profile.manage` (platform administrators);
anyone else gets 403. Writes run in the caller's Unit of Work, trace with no Opportunity, and
follow the rules of `domain.model_profiles`:

- `create_model_profile`: validates, refuses a name another profile has (409
  `registry_model_profile_duplicate`) and a model off the allowlist (422
  `registry_model_not_approved`), then inserts the `untested` row, queues its live test
  (`application.jobs`) and traces `registry.model_profile.created`.
- `retest_model_profile`: a `failed` or `untested` profile (a test job can die without marking
  it) to a clean `untested` with its test queued; any other state is 409
  `registry_model_profile_not_retestable`. The job ignores a profile already tested, so a
  second job is harmless. The result is traced by the job.
- `retire_model_profile`: 409 `registry_model_profile_in_use` while an Agent's current config
  version pins it; the row lock pairs with the one `registry._profile_problem` takes, so a
  concurrent pin and retire can't both pass. Retiring it again is a 200 no-op.
- `add_approved_model` and `remove_approved_model`: the allowlist. Removing an entry leaves
  profiles that name it alone.

For other modules and the worker (no authorization): `chat_profile` and `profile_resolver` find
a profile by name in any state, because a retired profile keeps serving what is pinned to it.
"""

from collections.abc import Awaitable, Callable
from functools import partial
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.registry.adapters import repository as repo
from app.modules.registry.application.jobs import enqueue_profile_test
from app.modules.registry.application.models import (
    ApprovedModelList,
    ApprovedModelView,
    ModelProfileList,
    ModelProfileView,
    NewApprovedModel,
    NewModelProfile,
)
from app.modules.registry.domain import model_profiles as rules
from app.modules.registry.domain.model_profiles import ApprovedModel, CustomProfile, ProfileState
from app.platform import trace
from app.platform.errors import (
    ForbiddenError,
    NotFoundError,
    RegistryApprovedModelDuplicateError,
    RegistryModelNotApprovedError,
    RegistryModelProfileDuplicateError,
    RegistryModelProfileInUseError,
    RegistryModelProfileNotRetestableError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.model_gateway.profiles import (
    ModelProfile,
    UnknownModelProfileError,
)
from app.platform.trace.catalogue import (
    RegistryApprovedModelAdded,
    RegistryApprovedModelRemoved,
    RegistryModelProfileCreated,
    RegistryModelProfileRetired,
)
from app.platform.uow import UnitOfWork, unit_of_work

PROFILE_NOT_FOUND = "No custom model profile with this id."
APPROVED_NOT_FOUND = "No approved model with this id."
_log = get_logger(__name__)


def profile_view(profile: CustomProfile) -> ModelProfileView:
    return ModelProfileView(
        id=str(profile.id),
        name=profile.name,
        provider=profile.provider,
        model=profile.model,
        num_ctx=profile.num_ctx,
        temperature=profile.temperature,
        reasoning_effort=profile.reasoning_effort,
        state=profile.state,
        error_code=profile.error_code,
        latency_ms=profile.latency_ms,
        tested_at=profile.tested_at,
        created_at=profile.created_at,
    )


def approved_view(approved: ApprovedModel) -> ApprovedModelView:
    return ApprovedModelView(
        id=str(approved.id),
        provider=approved.provider,
        model=approved.model,
        created_at=approved.created_at,
    )


def _manager(actor: Principal) -> UUID:
    identity.authorize(actor, Action.REGISTRY_MODEL_PROFILE_MANAGE)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can manage model profiles.")
    return user_id


async def _load(uow: UnitOfWork, profile_id: UUID, *, for_update: bool = False) -> CustomProfile:
    profile = await repo.get_model_profile(uow, profile_id, for_update=for_update)
    if profile is None:
        raise NotFoundError(PROFILE_NOT_FOUND)
    return profile


# --- profiles -------------------------------------------------------------------------------


async def read_model_profiles(uow: UnitOfWork, actor: Principal) -> ModelProfileList:
    """Every custom profile, newest first."""
    _manager(actor)
    return ModelProfileList(items=[profile_view(p) for p in await repo.list_model_profiles(uow)])


async def create_model_profile(
    uow: UnitOfWork, actor: Principal, new: NewModelProfile
) -> ModelProfileView:
    """Store an `untested` profile and queue its live test in this Unit of Work."""
    user_id = _manager(actor)
    try:
        name = rules.profile_name(new.name)
        model = rules.model_id(new.model)
        temperature, effort = rules.sampling(new.provider, new.temperature, new.reasoning_effort)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    await repo.lock_model_profiles(uow)
    if await repo.model_profile_named(uow, name) is not None:
        raise RegistryModelProfileDuplicateError(f"A model profile named {name} already exists.")
    if not await repo.is_approved(uow, new.provider, model):
        raise RegistryModelNotApprovedError(
            f"{model} is not an approved {new.provider} model. Add it to Approved models first."
        )
    profile_id = new_id()
    await repo.insert_model_profile(
        uow,
        profile_id=profile_id,
        name=name,
        provider=new.provider,
        model=model,
        num_ctx=new.num_ctx,
        temperature=temperature,
        reasoning_effort=effort,
        user_id=user_id,
    )
    await enqueue_profile_test(uow, profile_id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryModelProfileCreated(
            profile_id=str(profile_id),
            name=name,
            provider=new.provider,
            model=model,
            num_ctx=new.num_ctx,
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=profile_id,
    )
    _log.info(
        "registry.model_profile_created",
        extra={"profile": name, "model": model, "actor_id": str(user_id)},
    )
    return profile_view(await _load(uow, profile_id))


async def retest_model_profile(
    uow: UnitOfWork, actor: Principal, profile_id: UUID
) -> ModelProfileView:
    """Test a `failed` or `untested` profile again."""
    user_id = _manager(actor)
    profile = await _load(uow, profile_id)
    if not await repo.reset_model_profile_test(uow, profile_id):
        raise RegistryModelProfileNotRetestableError(
            f"{profile.name} is {profile.state.value}: only a failed or pending profile can be "
            "tested again."
        )
    await enqueue_profile_test(uow, profile_id)
    _log.info(
        "registry.model_profile_retest_queued",
        extra={"profile": profile.name, "actor_id": str(user_id)},
    )
    return profile_view(await _load(uow, profile_id))


async def retire_model_profile(
    uow: UnitOfWork, actor: Principal, profile_id: UUID
) -> ModelProfileView:
    """Retire a profile no Agent's current config version pins."""
    user_id = _manager(actor)
    profile = await _load(uow, profile_id, for_update=True)
    if profile.state == ProfileState.RETIRED:
        return profile_view(profile)
    if await repo.profile_is_current(uow, profile.name):
        raise RegistryModelProfileInUseError(
            f"{profile.name} is pinned by an Agent's current config version. Move that Agent "
            "to another profile first."
        )
    await repo.retire_model_profile(uow, profile_id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryModelProfileRetired(
            profile_id=str(profile_id), name=profile.name, from_state=profile.state.value
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=profile_id,
    )
    _log.info(
        "registry.model_profile_retired",
        extra={"profile": profile.name, "actor_id": str(user_id)},
    )
    return profile_view(await _load(uow, profile_id))


# --- the allowlist --------------------------------------------------------------------------


async def read_approved_models(uow: UnitOfWork, actor: Principal) -> ApprovedModelList:
    _manager(actor)
    return ApprovedModelList(items=[approved_view(a) for a in await repo.list_approved_models(uow)])


async def add_approved_model(
    uow: UnitOfWork, actor: Principal, new: NewApprovedModel
) -> ApprovedModelView:
    user_id = _manager(actor)
    try:
        model = rules.model_id(new.model)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    approved = await repo.insert_approved_model(
        uow, approved_id=new_id(), provider=new.provider, model=model, user_id=user_id
    )
    if approved is None:
        raise RegistryApprovedModelDuplicateError(f"{model} is already approved.")
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryApprovedModelAdded(
            approved_model_id=str(approved.id), provider=approved.provider, model=approved.model
        ),
        subject_type=rules.APPROVED_SUBJECT_TYPE,
        subject_id=approved.id,
    )
    _log.info(
        "registry.approved_model_added",
        extra={"provider": approved.provider, "model": model, "actor_id": str(user_id)},
    )
    return approved_view(approved)


async def remove_approved_model(uow: UnitOfWork, actor: Principal, approved_id: UUID) -> None:
    user_id = _manager(actor)
    approved = await repo.delete_approved_model(uow, approved_id)
    if approved is None:
        raise NotFoundError(APPROVED_NOT_FOUND)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=RegistryApprovedModelRemoved(
            approved_model_id=str(approved.id), provider=approved.provider, model=approved.model
        ),
        subject_type=rules.APPROVED_SUBJECT_TYPE,
        subject_id=approved.id,
    )
    _log.info(
        "registry.approved_model_removed",
        extra={
            "provider": approved.provider,
            "model": approved.model,
            "actor_id": str(user_id),
        },
    )


# --- for other modules and the worker (no authorization) --------------------------------------


async def _stored_profile(engine: AsyncEngine, name: str) -> ModelProfile | None:
    async with unit_of_work(engine) as uow:
        profile = await repo.model_profile_named(uow, name)
    return None if profile is None else profile.definition


def profile_resolver(engine: AsyncEngine) -> Callable[[str], Awaitable[ModelProfile | None]]:
    """The `ProfileResolver` the worker gives its ModelGateway. Each lookup opens its own short
    Unit of Work, before the call starts (AD-25)."""
    return partial(_stored_profile, engine)


async def chat_profile(engine: AsyncEngine, name: str) -> ModelProfile:
    """The registry profile called `name`, for budgets that read its context size. Raises
    `UnknownModelProfileError` for a name it doesn't know."""
    stored = await _stored_profile(engine, name)
    if stored is None:
        raise UnknownModelProfileError(f"model profile {name!r} is not defined")
    return stored
