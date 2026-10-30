"""Seed demo data for a trial or demo environment: a demo presales engineer and a few
Opportunities for people to open, review and extend.

A developer/operator tool, not part of the API process. Idempotent: it only adds what is
missing (a demo user, and the demo Opportunities that are not there yet, matched by customer
name), so re-running is safe. The Opportunities are owned by a seeded "Demo Presales" user
(no one signs in as them); people with a role that reads every Opportunity
(platform_administrator, ...) see them, and can be added as collaborators on any.

It talks to the database as the app does (PSA_DATABASE_URL, the least-privileged app role),
through the same application services the API uses. From `backend/`, or in the api image:

    uv run python -m scripts.seed_demo           # or: python -m scripts.seed_demo
    uv run python -m scripts.seed_demo --dry-run # list what would be created
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.identity.adapters import repository as users
from app.modules.identity.application.provisioning import user_actor
from app.modules.identity.domain.policy import Principal
from app.modules.identity.domain.role_permissions import ROLE_PERMISSIONS
from app.modules.identity.domain.roles import Role
from app.modules.opportunities.application import opportunities
from app.modules.opportunities.application.models import NewOpportunity
from app.platform.config import get_settings
from app.platform.db import create_engine
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork, unit_of_work

SEED_SUB = "seed|demo-presales"
SEED_NAME = "Demo Presales"
SEED_EMAIL = "demo.presales@tiqai.host"


@dataclass(frozen=True)
class Demo:
    customer: str
    title: str
    industry: str
    products: tuple[str, ...]
    due_in_days: int


DEMOS: tuple[Demo, ...] = (
    Demo(
        "Northwind Bank",
        "Digital onboarding platform",
        "Banking",
        ("Customer Portal", "Integration Hub"),
        21,
    ),
    Demo(
        "Contoso Logistics",
        "Fleet visibility and ETA service",
        "Logistics",
        ("Telemetry Gateway", "Analytics Workbench"),
        35,
    ),
    Demo(
        "Fabrikam Health",
        "Patient scheduling modernisation",
        "Healthcare",
        ("Scheduling Engine",),
        14,
    ),
    Demo(
        "Adatum Retail",
        "Omnichannel order management",
        "Retail",
        ("Order Orchestrator", "Integration Hub", "Customer Portal"),
        49,
    ),
    Demo("Tailspin Energy", "Meter data platform", "Energy", ("Telemetry Gateway",), 63),
)


async def ensure_seed_user(uow: UnitOfWork) -> Principal:
    existing = await users.get_by_sub(uow, SEED_SUB)
    if existing is not None:
        user_id = existing.id
    else:
        user_id = new_id()
        await users.insert_if_absent(
            uow, user_id=user_id, auth0_sub=SEED_SUB, name=SEED_NAME, email=SEED_EMAIL
        )
        found = await users.get_by_sub(uow, SEED_SUB)
        if found is None:
            raise RuntimeError("seed user not found after insert")
        user_id = found.id
    await users.replace_roles(uow, user_id, [Role.PRESALES_ENGINEER.value])
    return Principal(
        actor=user_actor(user_id),
        roles=frozenset({Role.PRESALES_ENGINEER}),
        permissions=ROLE_PERMISSIONS[Role.PRESALES_ENGINEER],
    )


async def seed(dry_run: bool) -> int:
    engine = create_engine(get_settings())
    created = 0
    try:
        async with unit_of_work(engine) as uow:
            owner = await ensure_seed_user(uow)
            page = await opportunities.list_mine(uow, owner, page_size=100)
            have = {item.customer_name for item in page.items}
            today = date.today()
            for demo in DEMOS:
                if demo.customer in have:
                    print(f"exists   {demo.customer}")
                    continue
                print(f"{'would create' if dry_run else 'create'}  {demo.customer}: {demo.title}")
                if dry_run:
                    continue
                await opportunities.create(
                    uow,
                    owner,
                    NewOpportunity(
                        title=demo.title,
                        customer_name=demo.customer,
                        industry=demo.industry,
                        products=list(demo.products),
                        target_proposal_date=today + timedelta(days=demo.due_in_days),
                    ),
                )
                created += 1
            if dry_run:
                raise _DryRun
    except _DryRun:
        print("dry run: nothing written")
    finally:
        await engine.dispose()
    print(f"done: {created} Opportunities created")
    return 0


class _DryRun(Exception):
    """Raised to roll the Unit of Work back after a dry run (the seed user is not kept)."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would be created")
    args = parser.parse_args(argv)
    return asyncio.run(seed(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
