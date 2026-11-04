"""Create a custom chat model profile, the way an administrator does in Admin > Model profiles.

A developer/operator tool, not part of the API process. It calls the same application service as
the API, so the model must already be on the approved-model allowlist, and the profile is stored
`untested` with its live test queued: the worker runs it and the profile becomes `verified` (or
`failed`) within a few seconds. Idempotent: an existing profile with the name is left alone.

The profile is authored by the seeded "Agent model script" user (platform administrator, nobody
signs in as them), the same one `set_agent_model.py` uses. It talks to the database as the app
does (PSA_DATABASE_URL). From `backend/`:

    uv run python -m scripts.create_model_profile anthropic-sonnet-chat anthropic claude-sonnet-5-5

The api image holds only `app/` and `migrations/`, so on a cluster pipe the file into the pod:

    kubectl -n <ns> exec -i deploy/<release>-api -- python - <name> <provider> <model> < scripts/create_model_profile.py

Then pin the Agents to it with `set_agent_model.py <name>` once it is `verified`.
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
from app.modules.registry.application import model_profiles
from app.modules.registry.application.models import NewModelProfile
from app.platform.config import get_settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork, unit_of_work

SCRIPT_SUB = "seed|agent-model-script"
SCRIPT_NAME = "Agent model script"
SCRIPT_EMAIL = "agent-model-script@tiqai.host"


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


async def create(args: argparse.Namespace) -> int:
    engine = create_engine(get_settings())
    try:
        async with unit_of_work(engine) as uow:
            admin = await ensure_script_admin(uow)
            existing = await model_profiles.read_model_profiles(uow, admin)
            if any(profile.name == args.name for profile in existing.items):
                print(f"exists   {args.name}")
                return 0
            view = await model_profiles.create_model_profile(
                uow,
                admin,
                NewModelProfile(
                    name=args.name,
                    provider=args.provider,
                    model=args.model,
                    num_ctx=args.num_ctx,
                    temperature=args.temperature,
                    reasoning_effort=args.reasoning_effort,
                ),
            )
            print(f"created  {view.name}: {view.provider} {view.model} ({view.state})")
    finally:
        await engine.dispose()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="the profile name, e.g. anthropic-sonnet-chat")
    parser.add_argument("provider", choices=["ollama", "openai", "anthropic"])
    parser.add_argument("model", help="an approved model of that provider")
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--reasoning-effort", default=None)
    return asyncio.run(create(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
