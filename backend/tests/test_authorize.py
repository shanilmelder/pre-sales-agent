"""Central authorization (AD-15): the action catalogue, permission grants (Auth0 RBAC, from
the token), resource-scoped rules and `authorize`.

Principals get the permissions Auth0 issues for their roles under the README seed
(`tests.auth_tokens.SEED_PERMISSIONS`) unless a test says otherwise."""

from uuid import UUID, uuid4

import pytest

from app.modules.identity.application.public import (
    ACTION_NAME_RE,
    ANY_ROLE_GRANTS,
    HUMAN_ONLY_ACTIONS,
    MEMBER_GRANTS,
    OPPORTUNITY_RESOURCE,
    OWNER_GRANTS,
    RELATION_EXCLUDED_ROLES,
    RELATION_REQUIRED_ROLES,
    REVIEWER_GRANTS,
    Action,
    OverrideBasis,
    Principal,
    Resource,
    Role,
    authorize,
    can,
    finding_override_basis,
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
ADMIN_ONLY = (
    Action.USER_LIST,
    Action.CATALOGUE_ENTRY_CREATE,
    Action.CATALOGUE_ENTRY_EDIT,
    Action.CATALOGUE_ENTRY_RETIRE,
    Action.CATALOGUE_ENTRY_REACTIVATE,
    Action.REGISTRY_AGENT_REGISTER,
    Action.REGISTRY_AGENT_CONFIG_CREATE,
    Action.REGISTRY_AGENT_SET_STATUS,
)
MODULES = {
    "actuals",
    # Story 10.6: `platform.retention.read` (Admin > Retention; the purge is platform's).
    "platform",
    "reporting",
    "identity",
    "notifications",
    "opportunities",
    "intake",
    "gaps",
    "estimates",
    "assessments",
    "conflicts",
    "knowledge",
    "registry",
    "workflows",
    "reviews",
}


ACTUALS = (
    Action.ACTUAL_RECORD,
    Action.ACTUAL_CORRECT,
    Action.DELIVERY_CLOSE,
    Action.ACTUAL_IMPORT,
)
OUTCOME = (Action.OUTCOME_RECORD, Action.CONTRACT_END_DATE_UPDATE, Action.OUTCOME_REOPEN)


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


# --- Story 9.7: people-only actions --------------------------------------------------------


def test_setting_the_baseline_is_people_only() -> None:
    assert HUMAN_ONLY_ACTIONS == {Action.ESTIMATE_BASELINE_SET, *ACTUALS, *OUTCOME}


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_no_agent_or_system_may_set_the_baseline_whatever_its_grants(actor_type: str) -> None:
    some_id = uuid4()
    principal = Principal(
        Actor(actor_type, str(some_id)),  # type: ignore[arg-type]
        frozenset({Role.PRESALES_ENGINEER}),
        frozenset(Action),
    )
    resource = _opportunity(some_id, some_id)
    assert not can(principal, Action.ESTIMATE_BASELINE_SET, resource)
    assert not can(principal, Action.ESTIMATE_BASELINE_SET)
    with pytest.raises(ForbiddenError):
        authorize(principal, Action.ESTIMATE_BASELINE_SET, resource)
    assert can(principal, Action.ESTIMATE_VERSION_SUBMIT, resource)  # other grants stand


@pytest.mark.parametrize("action", list(Action))
def test_a_permission_grants_its_action_without_any_role(action: Action) -> None:
    principal, _ = _user(permissions={action})
    assert can(principal, action)
    other = next(a for a in Action if a is not action)
    assert not can(principal, other)


@pytest.mark.parametrize("role", list(Role))
def test_a_role_without_permissions_grants_nothing_on_its_own(role: Role) -> None:
    """Beyond the reads every role holds (`ANY_ROLE_GRANTS`)."""
    principal, _ = _user({role}, permissions=set())
    for action in Action:
        assert can(principal, action) == (action in ANY_ROLE_GRANTS)


def test_any_role_grants_need_a_role() -> None:
    assert ANY_ROLE_GRANTS == {Action.KNOWLEDGE_CHUNK_SEARCH, Action.NOTIFICATION_READ}
    nobody, _ = _user(set(), permissions=set())
    commercial, _ = _user({Role.COMMERCIAL}, permissions=set())
    for action in ANY_ROLE_GRANTS:
        assert not can(nobody, action)
        assert can(commercial, action)


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
        Action.GAP_EDIT,
        Action.GAP_QUESTION_SEND,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.ASSUMPTION_EDIT,
        Action.RISK_CREATE,
        Action.RISK_EDIT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
        Action.ESTIMATE_VERSION_SUBMIT,
        Action.CONFLICT_RESOLVE,
        Action.CONFLICT_ESCALATE,
        Action.DECISION_RESOLVE,
        Action.FINDING_RESOLVE,
        Action.FINDING_OVERRIDE,
        Action.REVIEW_REQUEST_CREATE,
        Action.REVIEW_REQUEST_CANCEL,
        Action.REVIEW_REQUEST_DECIDE,
        Action.REVIEW_REQUEST_REPLY,
        Action.ESTIMATE_VERSION_CREATE,
        Action.ESTIMATE_BASELINE_SET,
        Action.CHALLENGE_RAISE,
        Action.CHALLENGE_CONFIRM,
        Action.CHALLENGE_DECLINE,
        *ACTUALS,
        Action.OUTCOME_RECORD,
    }
    assert MEMBER_GRANTS == {
        Action.OPPORTUNITY_READ,
        Action.SOURCE_ADD,
        Action.EXTRACTION_START,
        Action.REQUIREMENT_EDIT,
        Action.GAP_DETECTION_START,
        Action.GAP_QUESTION_EDIT,
        Action.GAP_EDIT,
        Action.GAP_QUESTION_SEND,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.ASSUMPTION_EDIT,
        Action.RISK_CREATE,
        Action.RISK_EDIT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
        Action.ESTIMATE_VERSION_SUBMIT,
        Action.CONFLICT_RESOLVE,
        Action.CONFLICT_ESCALATE,
        Action.DECISION_RESOLVE,
        Action.FINDING_RESOLVE,
        Action.REVIEW_REQUEST_CREATE,
        Action.REVIEW_REQUEST_CANCEL,
        Action.REVIEW_REQUEST_DECIDE,
        Action.REVIEW_REQUEST_REPLY,
        Action.ESTIMATE_VERSION_CREATE,
        Action.ESTIMATE_BASELINE_SET,
        *ACTUALS,
    }
    assert REVIEWER_GRANTS == {
        Action.OPPORTUNITY_READ,
        Action.REVIEW_REQUEST_DECIDE,
        Action.CHALLENGE_RAISE,
    }
    assert RELATION_EXCLUDED_ROLES == {
        Action.REQUIREMENT_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_DETECTION_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_QUESTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_DRAFT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_ACCEPT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RISK_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RISK_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RED_TEAM_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSESSMENT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_EXPORT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_LINE_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_VERSION_SUBMIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CONFLICT_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CONFLICT_ESCALATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.DECISION_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.FINDING_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.FINDING_OVERRIDE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_CANCEL: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_DECIDE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_REPLY: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_VERSION_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_BASELINE_SET: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_RAISE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_CONFIRM: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_DECLINE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.OUTCOME_RECORD: frozenset({Role.SALES_REPRESENTATIVE}),
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
    assert can(owner, Action.GAP_EDIT, opportunity) is allowed
    assert can(member, Action.GAP_EDIT, opportunity) is allowed
    # Story 4.6: sales representatives send questions too.
    assert can(owner, Action.GAP_QUESTION_SEND, opportunity) is True
    assert can(member, Action.GAP_QUESTION_SEND, opportunity) is True
    assert can(owner, Action.ESTIMATE_DRAFT_START, opportunity) is allowed
    assert can(member, Action.ESTIMATE_DRAFT_START, opportunity) is allowed
    assert can(owner, Action.ASSUMPTION_ACCEPT, opportunity) is allowed
    assert can(member, Action.ASSUMPTION_ACCEPT, opportunity) is allowed
    for action in (Action.ASSUMPTION_EDIT, Action.RISK_CREATE, Action.RISK_EDIT):  # Story 8.5
        assert can(owner, action, opportunity) is allowed
        assert can(member, action, opportunity) is allowed
    assert can(owner, Action.RED_TEAM_START, opportunity) is allowed
    assert can(member, Action.RED_TEAM_START, opportunity) is allowed
    assert can(owner, Action.ASSESSMENT_START, opportunity) is allowed
    assert can(member, Action.ASSESSMENT_START, opportunity) is allowed
    assert can(owner, Action.ESTIMATE_EXPORT, opportunity) is allowed
    assert can(member, Action.ESTIMATE_EXPORT, opportunity) is allowed
    assert can(owner, Action.ESTIMATE_LINE_EDIT, opportunity) is allowed
    assert can(member, Action.ESTIMATE_LINE_EDIT, opportunity) is allowed
    assert can(owner, Action.CONFLICT_RESOLVE, opportunity) is allowed
    assert can(member, Action.CONFLICT_RESOLVE, opportunity) is allowed
    assert can(owner, Action.CONFLICT_ESCALATE, opportunity) is allowed
    assert can(member, Action.CONFLICT_ESCALATE, opportunity) is allowed
    assert can(owner, Action.DECISION_RESOLVE, opportunity) is allowed
    assert can(member, Action.DECISION_RESOLVE, opportunity) is allowed
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


# --- Story 6.6: overriding a Critic or Red Team Finding (R1) --------------------------------


def test_finding_actions_are_catalogued() -> None:
    assert Action.FINDING_RESOLVE.value == "assessments.finding.resolve"
    assert Action.FINDING_OVERRIDE.value == "assessments.finding.override"


@pytest.mark.parametrize("security", [False, True])
def test_override_basis_follows_r1(security: bool) -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    colleague, colleague_id = _user({Role.PRESALES_ENGINEER})
    rep, rep_id = _user({Role.SALES_REPRESENTATIVE})
    sec, sec_id = _user({Role.SECURITY_REVIEWER})
    head, _ = _user({Role.HEAD_OF_DELIVERY})
    admin, _ = _user({Role.PLATFORM_ADMINISTRATOR})
    opportunity = _opportunity(owner_id, colleague_id, rep_id, sec_id)

    def basis(principal: Principal) -> OverrideBasis | None:
        return finding_override_basis(principal, opportunity, security_discipline=security)

    assert basis(owner) == OverrideBasis.OWNER
    assert basis(head) == OverrideBasis.HEAD_OF_DELIVERY
    assert basis(sec) == (OverrideBasis.SECURITY_REVIEWER if security else None)
    for denied in (colleague, rep, admin):
        assert basis(denied) is None
    rep_owner, rep_owner_id = _user({Role.SALES_REPRESENTATIVE})
    assert (
        finding_override_basis(rep_owner, _opportunity(rep_owner_id), security_discipline=security)
        is None
    )


def test_collaborators_except_sales_reps_resolve_findings() -> None:
    owner, owner_id = _user({Role.PRESALES_ENGINEER})
    colleague, colleague_id = _user({Role.PRESALES_ENGINEER})
    rep, rep_id = _user({Role.SALES_REPRESENTATIVE})
    opportunity = _opportunity(owner_id, colleague_id, rep_id)
    assert can(owner, Action.FINDING_RESOLVE, opportunity)
    assert can(colleague, Action.FINDING_RESOLVE, opportunity)
    assert not can(rep, Action.FINDING_RESOLVE, opportunity)
    assert not can(colleague, Action.FINDING_OVERRIDE, opportunity)


# --- Review Requests (Story 9.1) ------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_review_requests_for_owner_and_members_except_sales_reps(role: Role) -> None:
    owner, owner_id = _user({role})
    member, member_id = _user({role})
    opportunity = _opportunity(owner_id, member_id)
    allowed = role is not Role.SALES_REPRESENTATIVE
    for action in (
        Action.REVIEW_REQUEST_CREATE,
        Action.REVIEW_REQUEST_CANCEL,
        Action.REVIEW_REQUEST_DECIDE,
        Action.REVIEW_REQUEST_REPLY,
        Action.ESTIMATE_VERSION_CREATE,
        Action.ESTIMATE_BASELINE_SET,
    ):
        assert can(owner, action, opportunity) is allowed
        assert can(member, action, opportunity) is allowed


@pytest.mark.parametrize("role", list(Role))
def test_challenges_are_the_owners_to_confirm(role: Role) -> None:
    """Story 9.5: the owner raises, confirms and declines; a collaborator does none of it;
    a sales representative never."""
    owner, owner_id = _user({role})
    member, member_id = _user({role})
    opportunity = _opportunity(owner_id, member_id)
    allowed = role is not Role.SALES_REPRESENTATIVE
    for action in (Action.CHALLENGE_RAISE, Action.CHALLENGE_CONFIRM, Action.CHALLENGE_DECLINE):
        assert can(owner, action, opportunity) is allowed
        assert not can(member, action, opportunity)


@pytest.mark.parametrize("role", list(Role))
def test_a_reviewer_collaborator_may_only_read_and_decide(role: Role) -> None:
    """Story 9.3: reading, and deciding (their own request, checked by `reviews`), except as a
    sales representative."""
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    reviewer, reviewer_id = _user({role}, permissions=set())
    opportunity = Resource(
        type=OPPORTUNITY_RESOURCE,
        id=uuid4(),
        owner_id=owner_id,
        reviewer_ids=frozenset({reviewer_id}),
    )
    assert can(reviewer, Action.OPPORTUNITY_READ, opportunity)
    assert can(reviewer, Action.REVIEW_REQUEST_DECIDE, opportunity) is (
        role is not Role.SALES_REPRESENTATIVE
    )
    # Story 9.5: raising a Challenge (while a request is pending, checked by `reviews`).
    assert can(reviewer, Action.CHALLENGE_RAISE, opportunity) is (
        role is not Role.SALES_REPRESENTATIVE
    )
    for action in (OWNER_GRANTS | MEMBER_GRANTS) - REVIEWER_GRANTS:
        assert not can(reviewer, action, opportunity), action


# --- Actuals (Story 10.1): delivery managers who can read the Opportunity -------------------


def test_actuals_relations_need_the_delivery_manager_role() -> None:
    assert RELATION_REQUIRED_ROLES == dict.fromkeys(ACTUALS, frozenset({Role.DELIVERY_MANAGER}))


@pytest.mark.parametrize("role", list(Role))
def test_only_delivery_managers_record_actuals(role: Role) -> None:
    """By relation alone (no permissions) and with the seeded permissions."""
    allowed = role is Role.DELIVERY_MANAGER
    for permissions in (set(), None):
        owner, owner_id = _user({role}, permissions=permissions)
        member, member_id = _user({role}, permissions=permissions)
        opportunity = _opportunity(owner_id, member_id)
        for action in ACTUALS:
            assert can(owner, action, opportunity) is allowed, (role, action)
            assert can(member, action, opportunity) is allowed, (role, action)


def test_a_delivery_manager_with_another_role_keeps_the_grant() -> None:
    _, owner_id = _user({Role.PRESALES_ENGINEER})
    both, both_id = _user({Role.PRESALES_ENGINEER, Role.DELIVERY_MANAGER}, permissions=set())
    assert can(both, Action.ACTUAL_RECORD, _opportunity(owner_id, both_id))


def test_the_delivery_manager_permissions_are_seeded() -> None:
    assert set(ACTUALS) <= _seeded({Role.DELIVERY_MANAGER})
    for role in set(Role) - {Role.DELIVERY_MANAGER}:
        assert not set(ACTUALS) & _seeded({role}), role


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_no_agent_or_system_records_actuals(actor_type: str) -> None:
    some_id = uuid4()
    principal = Principal(
        Actor(actor_type, str(some_id)),  # type: ignore[arg-type]
        frozenset({Role.DELIVERY_MANAGER}),
        frozenset(Action),
    )
    for action in ACTUALS:
        assert not can(principal, action, _opportunity(some_id, some_id))


# --- the Opportunity outcome (Story 10.5) -----------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_the_owner_records_the_outcome_except_as_a_sales_representative(role: Role) -> None:
    """By relation alone, and with the seeded permissions. Collaborators may not."""
    for permissions in (set(), None):
        owner, owner_id = _user({role}, permissions=permissions)
        member, member_id = _user({role}, permissions=permissions)
        opportunity = _opportunity(owner_id, member_id)
        hod = role is Role.HEAD_OF_DELIVERY and permissions is None
        assert can(owner, Action.OUTCOME_RECORD, opportunity) is (
            role is not Role.SALES_REPRESENTATIVE
        ), role
        assert can(member, Action.OUTCOME_RECORD, opportunity) is hod, role


def test_outcome_permissions_are_seeded_to_the_head_of_delivery_and_admin() -> None:
    assert set(OUTCOME) <= _seeded({Role.HEAD_OF_DELIVERY})
    admin = _seeded({Role.PLATFORM_ADMINISTRATOR})
    assert Action.CONTRACT_END_DATE_UPDATE in admin
    assert Action.OUTCOME_REOPEN in admin
    assert Action.OUTCOME_RECORD not in admin
    for role in set(Role) - {Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR}:
        assert not set(OUTCOME) & _seeded({role}), role


@pytest.mark.parametrize("role", list(Role))
def test_only_permissions_change_the_contract_end_or_reopen(role: Role) -> None:
    """No relation grants them: an owner without the permission may not."""
    owner, owner_id = _user({role}, permissions=set())
    for action in (Action.CONTRACT_END_DATE_UPDATE, Action.OUTCOME_REOPEN):
        assert not can(owner, action, _opportunity(owner_id)), (role, action)


@pytest.mark.parametrize("actor_type", ["agent", "system"])
def test_no_agent_or_system_changes_the_outcome(actor_type: str) -> None:
    some_id = uuid4()
    principal = Principal(
        Actor(actor_type, str(some_id)),  # type: ignore[arg-type]
        frozenset({Role.HEAD_OF_DELIVERY}),
        frozenset(Action),
    )
    for action in OUTCOME:
        assert not can(principal, action, _opportunity(some_id, some_id))
