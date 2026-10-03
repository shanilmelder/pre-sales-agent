"""Central authorization (AD-15): the action catalogue, roles, resource-scoped rules and
`authorize`."""

from uuid import UUID, uuid4

import pytest

from app.modules.identity.application.public import (
    ACTION_NAME_RE,
    MEMBER_GRANTS,
    OPPORTUNITY_RESOURCE,
    OWNER_GRANTS,
    POLICY,
    Action,
    Principal,
    Resource,
    Role,
    authorize,
    can,
)
from app.platform.actor import Actor
from app.platform.errors import ForbiddenError

ADMIN = Principal(Actor("user", "u-admin"), frozenset({Role.PLATFORM_ADMINISTRATOR}))
ENGINEER = Principal(Actor("user", "u-pse"), frozenset({Role.PRESALES_ENGINEER}))
ADMIN_ONLY = (Action.USER_LIST, Action.USER_ASSIGN_ROLE, Action.USER_REMOVE_ROLE)
MODULES = {"identity", "opportunities"}


def _user(roles: set[Role] | None = None) -> tuple[Principal, UUID]:
    user_id = uuid4()
    return Principal(Actor("user", str(user_id)), frozenset(roles or set())), user_id


def _opportunity(owner: UUID, *members: UUID) -> Resource:
    return Resource(
        type=OPPORTUNITY_RESOURCE, id=uuid4(), owner_id=owner, member_ids=frozenset(members)
    )


def test_action_names_follow_module_entity_verb() -> None:
    for action in Action:
        assert ACTION_NAME_RE.match(action.value), action.value
        assert action.value.split(".")[0] in MODULES


def test_story_1_7_actions_are_catalogued() -> None:
    assert {a.value for a in Action} >= {
        "opportunities.opportunity.create",
        "opportunities.opportunity.read",
        "opportunities.collaborator.add",
        "opportunities.collaborator.remove",
        "identity.user.search",
    }


@pytest.mark.parametrize("bad", ["identity.user", "Identity.user.assign", "a.b.c.d", "a.b.c-d"])
def test_action_regex_rejects_bad_names(bad: str) -> None:
    assert not ACTION_NAME_RE.match(bad)


def test_nine_roles() -> None:
    assert len(Role) == 9


def test_every_action_has_a_policy_entry() -> None:
    assert set(POLICY) == set(Action)
    for action in ADMIN_ONLY:
        assert POLICY[action] == {Role.PLATFORM_ADMINISTRATOR}
    assert POLICY[Action.OPPORTUNITY_CREATE] == {Role.PRESALES_ENGINEER}
    assert POLICY[Action.OPPORTUNITY_READ] == {
        Role.HEAD_OF_DELIVERY,
        Role.PLATFORM_ADMINISTRATOR,
    }
    assert POLICY[Action.COLLABORATOR_ADD] == frozenset()
    assert POLICY[Action.COLLABORATOR_REMOVE] == frozenset()
    assert POLICY[Action.USER_SEARCH] == {Role.PRESALES_ENGINEER}


def test_resource_scoped_grants() -> None:
    assert OWNER_GRANTS == {
        Action.OPPORTUNITY_READ,
        Action.COLLABORATOR_ADD,
        Action.COLLABORATOR_REMOVE,
    }
    assert MEMBER_GRANTS == {Action.OPPORTUNITY_READ}


@pytest.mark.parametrize("action", ADMIN_ONLY)
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
@pytest.mark.parametrize("action", ADMIN_ONLY)
def test_no_granting_role_is_forbidden(principal: Principal, action: Action) -> None:
    with pytest.raises(ForbiddenError):
        authorize(principal, action)


def test_policy_cannot_be_mutated_at_runtime() -> None:
    with pytest.raises(TypeError):
        POLICY[Action.USER_ASSIGN_ROLE] = frozenset(Role)  # type: ignore[index]


# --- Opportunities: role and resource-scoped rules ------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_only_presales_engineers_create(role: Role) -> None:
    principal, _ = _user({role})
    assert can(principal, Action.OPPORTUNITY_CREATE) is (role is Role.PRESALES_ENGINEER)


def test_owner_reads_and_manages_collaborators() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    resource = _opportunity(owner_id)
    for action in (Action.OPPORTUNITY_READ, Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE):
        authorize(owner, action, resource)


def test_owner_and_members_without_roles_are_denied() -> None:
    """A user whose roles were all removed loses access to their Opportunities."""
    owner, owner_id = _user()
    member, member_id = _user()
    resource = _opportunity(owner_id, member_id)
    for action in (Action.OPPORTUNITY_READ, Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE):
        assert not can(owner, action, resource)
        assert not can(member, action, resource)


def test_owner_and_member_rules_apply_only_to_opportunities() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    member, member_id = _user({Role.PM_REVIEWER})
    other = Resource(
        type="knowledge.document", id=uuid4(), owner_id=owner_id, member_ids=frozenset({member_id})
    )
    for action in (Action.OPPORTUNITY_READ, Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE):
        assert not can(owner, action, other)
        assert not can(member, action, other)


def test_collaborator_reads_but_does_not_manage() -> None:
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    member, member_id = _user({Role.ENGINEERING_REVIEWER})
    resource = _opportunity(owner_id, member_id)
    assert can(member, Action.OPPORTUNITY_READ, resource)
    for action in (Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE):
        with pytest.raises(ForbiddenError):
            authorize(member, action, resource)


@pytest.mark.parametrize("role", [Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR])
def test_hod_and_admin_read_every_opportunity_but_do_not_manage(role: Role) -> None:
    principal, _ = _user({role})
    resource = _opportunity(uuid4())
    assert can(principal, Action.OPPORTUNITY_READ, resource)
    assert can(principal, Action.OPPORTUNITY_READ)  # role grant: no resource needed
    assert not can(principal, Action.COLLABORATOR_ADD, resource)
    assert not can(principal, Action.COLLABORATOR_REMOVE, resource)


@pytest.mark.parametrize(
    "role", [r for r in Role if r not in {Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR}]
)
def test_other_roles_cannot_read_someone_elses_opportunity(role: Role) -> None:
    principal, _ = _user({role})
    resource = _opportunity(uuid4(), uuid4())
    for action in (Action.OPPORTUNITY_READ, Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE):
        assert not can(principal, action, resource)
    assert not can(principal, Action.OPPORTUNITY_READ)


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_non_user_actors_get_no_resource_grants(actor_type: str) -> None:
    some_id = uuid4()
    principal = Principal(
        Actor(actor_type, str(some_id)),  # type: ignore[arg-type]
        frozenset({Role.PRESALES_ENGINEER}),
    )
    resource = _opportunity(some_id, some_id)
    assert not can(principal, Action.OPPORTUNITY_READ, resource)
    assert not can(principal, Action.COLLABORATOR_ADD, resource)


def test_non_uuid_user_actor_gets_no_resource_grants() -> None:
    principal = Principal(Actor("user", "not-a-uuid"), frozenset({Role.PRESALES_ENGINEER}))
    assert principal.user_id is None
    assert not can(principal, Action.OPPORTUNITY_READ, _opportunity(uuid4()))


def test_resource_without_owner_grants_nothing() -> None:
    principal, _ = _user({Role.PRESALES_ENGINEER})
    resource = Resource(type=OPPORTUNITY_RESOURCE, id=uuid4())
    assert not can(principal, Action.OPPORTUNITY_READ, resource)


def test_user_search_is_for_presales_engineers_only() -> None:
    engineer, _ = _user({Role.PRESALES_ENGINEER})
    authorize(engineer, Action.USER_SEARCH)
    for roles in ({Role.COMMERCIAL}, {Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR}, None):
        principal, _ = _user(roles)
        with pytest.raises(ForbiddenError):
            authorize(principal, Action.USER_SEARCH)
