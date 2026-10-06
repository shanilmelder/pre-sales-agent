"""Central authorization (AD-15): the action catalogue, permission grants (Auth0 RBAC, from
the token), resource-scoped rules and `authorize`.

Principals get the permissions Auth0 issues for their roles under the README seed
(`tests.auth_tokens.SEED_PERMISSIONS`) unless a test says otherwise."""

from uuid import UUID, uuid4

import pytest

from app.modules.identity.application.public import (
    ACTION_NAME_RE,
    MEMBER_GRANTS,
    OPPORTUNITY_RESOURCE,
    OWNER_GRANTS,
    RELATION_EXCLUDED_ROLES,
    Action,
    Principal,
    Resource,
    Role,
    authorize,
    can,
)
from app.platform.actor import Actor
from app.platform.errors import ForbiddenError
from tests.auth_tokens import permissions_for


def _seeded(roles: set[Role]) -> frozenset[Action]:
    return frozenset(Action(p) for p in permissions_for(r.value for r in roles))


def _principal(actor: Actor, roles: set[Role]) -> Principal:
    return Principal(actor, frozenset(roles), _seeded(roles))


ADMIN = _principal(Actor("user", "u-admin"), {Role.PLATFORM_ADMINISTRATOR})
ENGINEER = _principal(Actor("user", "u-pse"), {Role.PRESALES_ENGINEER})
ADMIN_ONLY = (Action.USER_LIST,)
MODULES = {"identity", "opportunities", "intake", "gaps", "estimates", "assessments"}


def _user(
    roles: set[Role] | None = None, permissions: set[Action] | None = None
) -> tuple[Principal, UUID]:
    user_id = uuid4()
    roles = roles or set()
    granted = _seeded(roles) if permissions is None else frozenset(permissions)
    return Principal(Actor("user", str(user_id)), frozenset(roles), granted), user_id


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


def test_story_1_8_update_action_is_catalogued() -> None:
    assert Action.OPPORTUNITY_UPDATE.value == "opportunities.opportunity.update"


@pytest.mark.parametrize("bad", ["identity.user", "Identity.user.assign", "a.b.c.d", "a.b.c-d"])
def test_action_regex_rejects_bad_names(bad: str) -> None:
    assert not ACTION_NAME_RE.match(bad)


def test_nine_roles() -> None:
    assert len(Role) == 9


def test_role_admin_writes_are_gone_from_the_catalogue() -> None:
    """Roles are assigned in Auth0 since Story 1.9."""
    assert {a.value for a in Action}.isdisjoint(
        {"identity.user.assign_role", "identity.user.remove_role"}
    )


@pytest.mark.parametrize("action", list(Action))
def test_a_permission_grants_its_action_without_any_role(action: Action) -> None:
    principal, _ = _user(permissions={action})
    assert can(principal, action)
    other = next(a for a in Action if a is not action)
    assert not can(principal, other)


@pytest.mark.parametrize("role", list(Role))
def test_a_role_without_permissions_grants_nothing_on_its_own(role: Role) -> None:
    principal, _ = _user({role}, permissions=set())
    for action in Action:
        assert not can(principal, action)


def test_role_without_create_permission_keeps_owner_and_member_access() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER}, permissions=set())
    member, member_id = _user({Role.PRESALES_ENGINEER}, permissions=set())
    resource = _opportunity(owner_id, member_id)
    assert not can(owner, Action.OPPORTUNITY_CREATE)
    assert can(owner, Action.OPPORTUNITY_UPDATE, resource)
    assert can(member, Action.REQUIREMENT_EDIT, resource)


def test_permissions_without_roles_earn_no_relation_grants() -> None:
    owner, owner_id = _user(permissions={Action.OPPORTUNITY_CREATE})
    assert not can(owner, Action.OPPORTUNITY_UPDATE, _opportunity(owner_id))


def test_sales_rep_collaborator_adds_sources_but_cannot_edit_requirements() -> None:
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    rep, rep_id = _user({Role.SALES_REPRESENTATIVE})
    resource = _opportunity(owner_id, rep_id)
    assert can(rep, Action.SOURCE_ADD, resource)
    with pytest.raises(ForbiddenError):
        authorize(rep, Action.REQUIREMENT_EDIT, resource)


def test_resource_scoped_grants() -> None:
    assert OWNER_GRANTS == {
        Action.OPPORTUNITY_READ,
        Action.OPPORTUNITY_UPDATE,
        Action.COLLABORATOR_ADD,
        Action.COLLABORATOR_REMOVE,
        Action.SOURCE_ADD,
        Action.EXTRACTION_START,
        Action.REQUIREMENT_EDIT,
        Action.GAP_DETECTION_START,
        Action.GAP_QUESTION_EDIT,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
    }
    assert MEMBER_GRANTS == {
        Action.OPPORTUNITY_READ,
        Action.SOURCE_ADD,
        Action.EXTRACTION_START,
        Action.REQUIREMENT_EDIT,
        Action.GAP_DETECTION_START,
        Action.GAP_QUESTION_EDIT,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
    }
    assert RELATION_EXCLUDED_ROLES == {
        Action.REQUIREMENT_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_DETECTION_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_QUESTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_DRAFT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_ACCEPT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RED_TEAM_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSESSMENT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_EXPORT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_LINE_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
    }


# --- Requirements (Story 2.6): owner and collaborators, except sales representatives --------


@pytest.mark.parametrize("role", list(Role))
def test_requirement_edit_for_owner_and_members_except_sales_reps(role: Role) -> None:
    owner, owner_id = _user({role})
    member, member_id = _user({role})
    opportunity = _opportunity(owner_id, member_id)
    allowed = role is not Role.SALES_REPRESENTATIVE

    assert can(owner, Action.REQUIREMENT_EDIT, opportunity) is allowed
    assert can(member, Action.REQUIREMENT_EDIT, opportunity) is allowed
    assert can(owner, Action.GAP_DETECTION_START, opportunity) is allowed
    assert can(member, Action.GAP_DETECTION_START, opportunity) is allowed
    assert can(owner, Action.GAP_QUESTION_EDIT, opportunity) is allowed
    assert can(member, Action.GAP_QUESTION_EDIT, opportunity) is allowed
    assert can(owner, Action.ESTIMATE_DRAFT_START, opportunity) is allowed
    assert can(member, Action.ESTIMATE_DRAFT_START, opportunity) is allowed
    assert can(owner, Action.ASSUMPTION_ACCEPT, opportunity) is allowed
    assert can(member, Action.ASSUMPTION_ACCEPT, opportunity) is allowed
    assert can(owner, Action.RED_TEAM_START, opportunity) is allowed
    assert can(member, Action.RED_TEAM_START, opportunity) is allowed
    assert can(owner, Action.ASSESSMENT_START, opportunity) is allowed
    assert can(member, Action.ASSESSMENT_START, opportunity) is allowed
    assert can(owner, Action.ESTIMATE_EXPORT, opportunity) is allowed
    assert can(member, Action.ESTIMATE_EXPORT, opportunity) is allowed
    assert can(owner, Action.ESTIMATE_LINE_EDIT, opportunity) is allowed
    assert can(member, Action.ESTIMATE_LINE_EDIT, opportunity) is allowed
    assert can(member, Action.SOURCE_ADD, opportunity) is True


def test_requirement_edit_needs_a_relation() -> None:
    outsider, _ = _user({Role.PRESALES_ENGINEER})
    head, _ = _user({Role.HEAD_OF_DELIVERY})
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    opportunity = _opportunity(owner_id)

    assert can(outsider, Action.REQUIREMENT_EDIT, opportunity) is False
    assert can(head, Action.REQUIREMENT_EDIT, opportunity) is False
    assert can(head, Action.OPPORTUNITY_READ, opportunity) is True
    assert can(owner, Action.REQUIREMENT_EDIT) is False  # no resource, no relation


def test_a_sales_rep_who_also_holds_another_role_keeps_requirement_edit() -> None:
    member, member_id = _user({Role.SALES_REPRESENTATIVE, Role.PRESALES_ENGINEER})
    _, owner_id = _user({Role.PRESALES_ENGINEER})

    assert can(member, Action.REQUIREMENT_EDIT, _opportunity(owner_id, member_id)) is True


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


def test_relation_exclusions_cannot_be_mutated_at_runtime() -> None:
    with pytest.raises(TypeError):
        RELATION_EXCLUDED_ROLES[Action.SOURCE_ADD] = frozenset(Role)  # type: ignore[index]


# --- Opportunities: role and resource-scoped rules ------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_only_presales_engineers_create(role: Role) -> None:
    principal, _ = _user({role})
    assert can(principal, Action.OPPORTUNITY_CREATE) is (role is Role.PRESALES_ENGINEER)


OWNER_ONLY = (Action.OPPORTUNITY_UPDATE, Action.COLLABORATOR_ADD, Action.COLLABORATOR_REMOVE)


def test_owner_reads_edits_and_manages_collaborators() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    resource = _opportunity(owner_id)
    for action in (Action.OPPORTUNITY_READ, *OWNER_ONLY):
        authorize(owner, action, resource)


def test_owner_and_members_without_roles_are_denied() -> None:
    """A user whose roles were all removed loses access to their Opportunities."""
    owner, owner_id = _user()
    member, member_id = _user()
    resource = _opportunity(owner_id, member_id)
    for action in (Action.OPPORTUNITY_READ, *OWNER_ONLY):
        assert not can(owner, action, resource)
        assert not can(member, action, resource)


def test_owner_and_member_rules_apply_only_to_opportunities() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    member, member_id = _user({Role.PM_REVIEWER})
    other = Resource(
        type="knowledge.document", id=uuid4(), owner_id=owner_id, member_ids=frozenset({member_id})
    )
    for action in (Action.OPPORTUNITY_READ, *OWNER_ONLY):
        assert not can(owner, action, other)
        assert not can(member, action, other)


def test_collaborator_reads_but_does_not_edit_or_manage() -> None:
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    member, member_id = _user({Role.ENGINEERING_REVIEWER})
    resource = _opportunity(owner_id, member_id)
    assert can(member, Action.OPPORTUNITY_READ, resource)
    for action in OWNER_ONLY:
        with pytest.raises(ForbiddenError):
            authorize(member, action, resource)


@pytest.mark.parametrize("role", [Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR])
def test_hod_and_admin_read_every_opportunity_but_do_not_edit_or_manage(role: Role) -> None:
    principal, _ = _user({role})
    resource = _opportunity(uuid4())
    assert can(principal, Action.OPPORTUNITY_READ, resource)
    assert can(principal, Action.OPPORTUNITY_READ)  # role grant: no resource needed
    for action in OWNER_ONLY:
        assert not can(principal, action, resource)
        assert not can(principal, action)


@pytest.mark.parametrize(
    "role", [r for r in Role if r not in {Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR}]
)
def test_other_roles_cannot_read_someone_elses_opportunity(role: Role) -> None:
    principal, _ = _user({role})
    resource = _opportunity(uuid4(), uuid4())
    for action in (Action.OPPORTUNITY_READ, *OWNER_ONLY):
        assert not can(principal, action, resource)
    assert not can(principal, Action.OPPORTUNITY_READ)


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_non_user_actors_get_no_resource_grants(actor_type: str) -> None:
    some_id = uuid4()
    principal = _principal(
        Actor(actor_type, str(some_id)),  # type: ignore[arg-type]
        {Role.PRESALES_ENGINEER},
    )
    resource = _opportunity(some_id, some_id)
    assert not can(principal, Action.OPPORTUNITY_READ, resource)
    assert not can(principal, Action.COLLABORATOR_ADD, resource)


def test_non_uuid_user_actor_gets_no_resource_grants() -> None:
    principal = _principal(Actor("user", "not-a-uuid"), {Role.PRESALES_ENGINEER})
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


# --- Sources (Story 2.1) --------------------------------------------------------------------


def test_story_2_1_source_add_action_is_catalogued() -> None:
    assert Action.SOURCE_ADD.value == "intake.source.add"


@pytest.mark.parametrize("role", list(Role))
def test_owner_and_collaborators_add_sources_whatever_their_role(role: Role) -> None:
    owner, owner_id = _user({role})
    member, member_id = _user({role})
    resource = _opportunity(owner_id, member_id)
    authorize(owner, Action.SOURCE_ADD, resource)
    authorize(member, Action.SOURCE_ADD, resource)


@pytest.mark.parametrize("role", list(Role))
def test_no_role_grants_adding_sources_on_its_own(role: Role) -> None:
    """HoD and admin read every Opportunity but add Sources only as owner or collaborator."""
    principal, _ = _user({role})
    assert not can(principal, Action.SOURCE_ADD)
    with pytest.raises(ForbiddenError):
        authorize(principal, Action.SOURCE_ADD, _opportunity(uuid4(), uuid4()))


def test_roleless_collaborator_cannot_add_sources() -> None:
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    member, member_id = _user()
    assert not can(member, Action.SOURCE_ADD, _opportunity(owner_id, member_id))


# --- Requirement extraction (Story 2.5 Part A) ----------------------------------------------


def test_story_2_5_extraction_start_action_is_catalogued() -> None:
    assert Action.EXTRACTION_START.value == "intake.extraction.start"


@pytest.mark.parametrize("role", list(Role))
def test_owner_and_collaborators_start_extraction_and_no_role_does_alone(role: Role) -> None:
    owner, owner_id = _user({role})
    member, member_id = _user({role})
    resource = _opportunity(owner_id, member_id)
    authorize(owner, Action.EXTRACTION_START, resource)
    authorize(member, Action.EXTRACTION_START, resource)
    reader, _ = _user({role})
    with pytest.raises(ForbiddenError):
        authorize(reader, Action.EXTRACTION_START, resource)
