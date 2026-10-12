"""identity's HTTP routes."""

from typing import Any

from fastapi import APIRouter

from app.modules.identity.application.public import CurrentUserDep, UserProfile
from app.platform.errors import PROBLEM_JSON, Problem

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "description": "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
        "content": PROBLEM_CONTENT,
    },
    503: {
        "description": "Sign-in service unavailable (`auth_unavailable`)",
        "content": PROBLEM_CONTENT,
    },
}

router = APIRouter(tags=["identity"])


@router.get("/me", operation_id="get_me", responses=AUTH_RESPONSES)
async def get_me(user: CurrentUserDep) -> UserProfile:
    """The signed-in user, provisioned on their first valid token, with the roles and
    permissions that token carries."""
    return UserProfile.of(user)
