"""Agent Registry routes (Story 7.1) under `/api/v1/registry/agents`. Platform
administrators only: anyone else gets 403. Writes to an existing Agent take its `ETag` back
in `If-Match`."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Response

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.registry.application import public as registry
from app.modules.registry.application.public import (
    AgentConfigVersionList,
    AgentStatusChange,
    NewAgent,
    NewAgentConfig,
    RegistryAgent,
    RegistryAgentList,
)
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "The caller is not a platform administrator (`forbidden`)",
    404: "No Agent with this id (`not_found`)",
    409: "An Agent with this id is already registered (`registry_agent_duplicate`)",
    412: "The Agent changed since the caller read it (`row_version_mismatch`)",
    422: "A field is invalid (the `detail` is the sentence to show; `validation_error`), the "
    "config references a prompt, schema or profile that is not deployed "
    "(`registry_config_not_deployed`), or its output schema is for another contract version "
    "(`registry_config_incompatible_contract`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}
_ETAG_HEADER = {
    "ETag": {
        "description": "The Agent's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Agent as last read (its `row_version`), e.g. `"3"`.',
    ),
]
_AGENT_ID = Annotated[str, Path(max_length=64, description="The Agent's id, e.g. `pm_agent`.")]


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


def _with_etag(response: Response, agent: RegistryAgent) -> RegistryAgent:
    response.headers["ETag"] = etag(agent.row_version)
    return agent


router = APIRouter(prefix="/registry/agents", tags=["registry"])


@router.get("", operation_id="list_registry_agents", responses=_responses(403))
async def list_registry_agents(actor: CurrentPrincipal, uow: UoW) -> RegistryAgentList:
    """Every Agent with its status and current config version, by agent id."""
    return await registry.read_agents(uow, actor)


@router.post(
    "",
    operation_id="register_agent",
    status_code=201,
    responses={
        **_responses(403, 409, 422),
        201: {"description": "The new Agent, with config version 1", "headers": _ETAG_HEADER},
    },
)
async def register_agent(
    body: NewAgent, actor: CurrentPrincipal, uow: UoW, response: Response
) -> RegistryAgent:
    """Register an Agent (`active`) with its config version 1."""
    return _with_etag(response, await registry.register_agent(uow, actor, body))


@router.get(
    "/{agent_id}",
    operation_id="get_registry_agent",
    responses={
        **_responses(403, 404, 422),
        200: {"description": "The Agent", "headers": _ETAG_HEADER},
    },
)
async def get_registry_agent(
    agent_id: _AGENT_ID, actor: CurrentPrincipal, uow: UoW, response: Response
) -> RegistryAgent:
    """One Agent with its status and current config version."""
    return _with_etag(response, await registry.read_agent(uow, actor, agent_id))


@router.get(
    "/{agent_id}/config-versions",
    operation_id="list_agent_config_versions",
    responses=_responses(403, 404, 422),
)
async def list_agent_config_versions(
    agent_id: _AGENT_ID, actor: CurrentPrincipal, uow: UoW
) -> AgentConfigVersionList:
    """Every config version of the Agent, newest first."""
    return await registry.read_versions(uow, actor, agent_id)


@router.post(
    "/{agent_id}/config-versions",
    operation_id="create_agent_config_version",
    status_code=201,
    responses={
        **_responses(403, 404, 412, 422, 428),
        201: {"description": "The Agent, at its new current version", "headers": _ETAG_HEADER},
    },
)
async def create_agent_config_version(
    agent_id: _AGENT_ID,
    body: NewAgentConfig,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> RegistryAgent:
    """Create the Agent's next config version; it becomes current for new runs. Runs in
    progress keep the version they pinned."""
    changed = await registry.create_config_version(uow, actor, agent_id, body, if_match)
    return _with_etag(response, changed)


@router.post(
    "/{agent_id}/status",
    operation_id="set_agent_status",
    responses={
        **_responses(403, 404, 412, 422, 428),
        200: {"description": "The Agent", "headers": _ETAG_HEADER},
    },
)
async def set_agent_status(
    agent_id: _AGENT_ID,
    body: AgentStatusChange,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> RegistryAgent:
    """Set the Agent `active`, `disabled` or `eval_only`. Only active Agents get new tasks;
    running tasks finish. The same status changes nothing."""
    changed = await registry.set_status(uow, actor, agent_id, body, if_match)
    return _with_etag(response, changed)
