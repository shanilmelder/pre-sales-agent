"""identity's HTTP routes."""

from typing import Any

from fastapi import APIRouter

from app.modules.identity.application.public import CurrentUserDep, UserProfile
from app.platform.errors import PROBLEM_JSON, Problem

_PROBLEM = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "description": "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
        "content": _PROBLEM,
    },
    503: {"description": "Sign-in service unavailable (`auth_unavailable`)", "content": _PROBLEM},
}

router = APIRouter(tags=["identity"])


@router.get("/me", operation_id="get_me", responses=AUTH_RESPONSES)
async def get_me(user: CurrentUserDep) -> UserProfile:
    """The signed-in user, provisioned with no roles on their first valid token."""
    return UserProfile.of(user)
