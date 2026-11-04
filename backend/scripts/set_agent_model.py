"""Point every Agent at one chat model profile, by creating a new config version for each.

A developer/operator tool, not part of the API process. It does what an administrator does in
Admin > Agents, for all Agents at once: for each Agent whose current config version pins another
profile, it creates the next config version, a copy of the current one with only `model_profile`
changed and the patch number of the semver raised, through the same application service the API
uses (so the profile must be `verified` and the config valid, or it stops with the API's error).
Agents that already use the profile are left alone, so re-running is safe. Everything runs in one
transaction: if any Agent fails, none is changed.

The new versions are authored by a seeded "Agent model script" user (platform administrator,
nobody signs in as them). It talks to the database as the app does (PSA_DATABASE_URL). From
`backend/`:

    uv run python -m scripts.set_agent_model anthropic-opus-chat --dry-run
    uv run python -m scripts.set_agent_model anthropic-opus-chat

The api image holds only `app/` and `migrations/`, so on a cluster pipe the file into the pod:

    kubectl -n <ns> exec -i deploy/<release>-api -- python - <profile> [--dry-run] < scripts/set_agent_model.py
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from app.modules.identity.adapters import repository as users
from app.modules.identity.application.provisioning import user_actor
from app.modules.identity.domain.policy import Principal
from app.modules.identity.domain.role_permissions import ROLE_PERMISSIONS
from app.modules.identity.domain.roles import Role
from app.modules.registry.application import registry
from app.modules.registry.application.models import NewAgentConfigVersion
from app.platform.config import get_settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork, unit_of_work

SCRIPT_SUB = "seed|agent-model-script"
SCRIPT_NAME = "Agent model script"
SCRIPT_EMAIL = "agent-model-script@tiqai.host"


class _DryRun(Exception):
    """Raised to roll the Unit of Work back after a dry run (the script user is not kept)."""


async def ensure_script_admin(uow: UnitOfWork) -> Principal:
    existing = await users.get_by_sub(uow, SCRIPT_SUB)
    if existing is not None:
        user_id = existing.id
    else:
        user_id = new_id()
        await users.insert_if_absent(
            uow, user_id=user_id, auth0_sub=SCRIPT_SUB, name=SCRIPT_NAME, email=SCRIPT_EMAIL
        )
        found = await users.get_by_sub(uow, SCRIPT_SUB)
        if found is None:
            raise RuntimeError("script user not found after insert")
        user_id = found.id
    await users.replace_roles(uow, user_id, [Role.PLATFORM_ADMINISTRATOR.value])
    return Principal(
        actor=user_actor(user_id),
        roles=frozenset({Role.PLATFORM_ADMINISTRATOR}),
        permissions=ROLE_PERMISSIONS[Role.PLATFORM_ADMINISTRATOR],
    )


def next_semver(current: str, taken: set[str]) -> str:
    """The current semver with its patch number raised, past any semver the Agent already has."""
    major, minor, patch = (int(part) for part in current.split("."))
    candidate = f"{major}.{minor}.{patch + 1}"
    while candidate in taken:
        patch += 1
        candidate = f"{major}.{minor}.{patch + 1}"
    return candidate


async def set_model(profile: str, dry_run: bool) -> int:
    engine = create_engine(get_settings())
    changed = 0
    try:
        async with unit_of_work(engine) as uow:
            admin = await ensure_script_admin(uow)
            agents = await registry.read_agents(uow, admin)
            for agent in agents.items:
                current = agent.current_config
                if current.model_profile == profile:
                    print(f"already  {agent.agent_id}: {profile} (v{current.version})")
                    continue
                versions = await registry.read_versions(uow, admin, agent.agent_id)
                semver = next_semver(current.semver, {v.semver for v in versions.items})
                print(
                    f"{'would set' if dry_run else 'set'}  {agent.agent_id}: "
                    f"{current.model_profile} -> {profile} (v{current.version} {current.semver}"
                    f" -> v{current.version + 1} {semver})"
                )
                if dry_run:
                    continue
                await registry.create_config_version(
                    uow,
                    admin,
                    agent.agent_id,
                    NewAgentConfigVersion(
                        semver=semver,
                        model_profile=profile,
                        prompt_version=current.prompt_version,
                        input_schema_version=current.input_schema_version,
                        output_schema_version=current.output_schema_version,
                        tool_permissions=list(current.tool_permissions),
                        budgets=dict(current.budgets),
                        reason=f"Use the {profile} model profile",
                    ),
                    str(agent.row_version),
                )
                changed += 1
            if dry_run:
                raise _DryRun
    except _DryRun:
        print("dry run: nothing written")
    finally:
        await engine.dispose()
    print(f"done: {changed} Agents changed")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("profile", help="the chat model profile to pin, e.g. anthropic-opus-chat")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    args = parser.parse_args(argv)
    return asyncio.run(set_model(args.profile, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
