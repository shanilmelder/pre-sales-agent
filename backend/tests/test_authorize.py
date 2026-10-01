"""Central authorization (AD-15): the action catalogue, roles and `authorize`."""

import pytest

from app.modules.identity.application.public import (
    ACTION_NAME_RE,
    POLICY,
    Action,
    Principal,
    Role,
    authorize,
)
from app.platform.actor import Actor
from app.platform.errors import ForbiddenError

ADMIN = Principal(Actor("user", "u-admin"), frozenset({Role.PLATFORM_ADMINISTRATOR}))
ENGINEER = Principal(Actor("user", "u-pse"), frozenset({Role.PRESALES_ENGINEER}))


def test_action_names_follow_module_entity_verb() -> None:
    for action in Action:
        assert ACTION_NAME_RE.match(action.value), action.value
        assert action.value.split(".")[0] == "identity"


@pytest.mark.parametrize("bad", ["identity.user", "Identity.user.assign", "a.b.c.d", "a.b.c-d"])
def test_action_regex_rejects_bad_names(bad: str) -> None:
    assert not ACTION_NAME_RE.match(bad)


def test_nine_roles() -> None:
    assert len(Role) == 9


def test_every_action_has_a_policy_entry() -> None:
    assert set(POLICY) == set(Action)
    assert POLICY[Action.USER_ASSIGN_ROLE] == {Role.PLATFORM_ADMINISTRATOR}
    assert POLICY[Action.USER_REMOVE_ROLE] == {Role.PLATFORM_ADMINISTRATOR}


@pytest.mark.parametrize("action", list(Action))
def test_granting_role_is_authorized(action: Action) -> None:
    authorize(ADMIN, action)  # returns None; raises ForbiddenError when denied


@pytest.mark.parametrize(
    "principal",
    [
        ENGINEER,
        Principal(Actor("user", "u-none")),
        Principal(Actor("agent", "agent-1")),
        Principal(Actor("system", "job-runner")),
    ],
)
@pytest.mark.parametrize("action", list(Action))
def test_no_granting_role_is_forbidden(principal: Principal, action: Action) -> None:
    with pytest.raises(ForbiddenError):
        authorize(principal, action)


def test_policy_cannot_be_mutated_at_runtime() -> None:
    with pytest.raises(TypeError):
        POLICY[Action.USER_ASSIGN_ROLE] = frozenset(Role)  # type: ignore[index]
