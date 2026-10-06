"""Seed Auth0 RBAC for the platform (Story 1.9): the API's permissions and RBAC settings,
the nine roles, which permissions each role holds, and (optionally) users' roles.

A developer tool, run by hand against a tenant; the app never calls the Management API.
Idempotent: it only adds what is missing and never removes permissions, roles or role
assignments, so it is safe to re-run.

Needs a Machine-to-Machine application authorized for the Auth0 Management API with the
scopes `read:resource_servers update:resource_servers read:roles create:roles
update:roles read:users update:users`. From `backend/`:

    AUTH0_DOMAIN=<tenant>.eu.auth0.com AUTH0_AUDIENCE=https://api.pre-sales-agent \
    AUTH0_MGMT_CLIENT_ID=... AUTH0_MGMT_CLIENT_SECRET=... \
    uv run python -m scripts.seed_auth0 --dry-run
    uv run python -m scripts.seed_auth0 \
        --assign you@example.com=platform_administrator,presales_engineer

The Post-Login Action's roles claim is code, not data: add it by hand (README "Auth0 setup").
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import dotenv_values

from app.modules.identity.actions import Action
from app.modules.identity.domain.roles import Role

ROLE_PERMISSIONS: Mapping[Role, frozenset[Action]] = {
    Role.PLATFORM_ADMINISTRATOR: frozenset({Action.USER_LIST, Action.OPPORTUNITY_READ}),
    Role.PRESALES_ENGINEER: frozenset({Action.USER_SEARCH, Action.OPPORTUNITY_CREATE}),
    Role.HEAD_OF_DELIVERY: frozenset({Action.OPPORTUNITY_READ}),
}
"""Which role holds which permission (README "Auth0 setup"). Roles not listed hold none:
their access comes from being an Opportunity's owner or collaborator."""

PERMISSIONS: frozenset[Action] = frozenset().union(*ROLE_PERMISSIONS.values())

PERMISSION_DESCRIPTIONS: Mapping[Action, str] = {
    Action.USER_LIST: "List users and their roles (Admin > Users & roles)",
    Action.USER_SEARCH: "Search users to pick Opportunity collaborators",
    Action.OPPORTUNITY_CREATE: "Create Opportunities",
    Action.OPPORTUNITY_READ: "Read every Opportunity",
}

TIMEOUT = 30.0
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
"""The repo-root `.env`; variables set in the environment win over it."""
TOKEN_DIALECT = "access_token_authz"  # noqa: S105 - Auth0 setting name, not a secret
"""Access tokens carry the `permissions` claim."""


@dataclass
class Report:
    """What the run changed (or, with --dry-run, would change)."""

    changes: list[str] = field(default_factory=list)

    def add(self, change: str) -> None:
        self.changes.append(change)
        print(f"  + {change}")


class Seeder:
    def __init__(self, client: httpx.Client, audience: str, *, dry_run: bool) -> None:
        self.client = client
        self.audience = audience
        self.dry_run = dry_run
        self.report = Report()

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.is_error:
            raise SystemExit(
                f"Auth0 {response.request.method} {response.request.url.path} failed: "
                f"{response.status_code} {response.text[:300]}"
            )
        return response

    def _get(self, path: str, **params: str) -> object:
        return self._check(self.client.get(path, params=params)).json()

    def _write(self, method: str, path: str, body: object, change: str) -> object:
        self.report.add(change)
        if self.dry_run:
            return None
        response = self._check(self.client.request(method, path, json=body))
        return response.json() if response.content else None

    def seed_api(self) -> None:
        """Turn on RBAC and permissions in the token; add the missing permissions."""
        api = self._get(f"/api/v2/resource-servers/{quote(self.audience, safe='')}")
        assert isinstance(api, dict)
        scopes: list[dict[str, str]] = list(api.get("scopes") or [])
        have = {scope["value"] for scope in scopes}
        missing = sorted(p.value for p in PERMISSIONS if p.value not in have)
        patch: dict[str, object] = {}
        if missing:
            patch["scopes"] = scopes + [
                {"value": name, "description": PERMISSION_DESCRIPTIONS[Action(name)]}
                for name in missing
            ]
        if not api.get("enforce_policies"):
            patch["enforce_policies"] = True
        if api.get("token_dialect") != TOKEN_DIALECT:
            patch["token_dialect"] = TOKEN_DIALECT
        if patch:
            self._write(
                "PATCH",
                f"/api/v2/resource-servers/{api['id']}",
                patch,
                f"API {self.audience}: "
                + ", ".join(
                    [f"permissions {missing}"] * bool(missing)
                    + ["RBAC on"] * ("enforce_policies" in patch)
                    + ["permissions in the access token"] * ("token_dialect" in patch)
                ),
            )

    def _roles_by_name(self) -> dict[str, str]:
        roles: dict[str, str] = {}
        page = 0
        while True:
            body = self._get("/api/v2/roles", per_page="100", page=str(page), include_totals="true")
            assert isinstance(body, dict)
            for role in body["roles"]:
                roles[role["name"]] = role["id"]
            if (page + 1) * 100 >= body["total"]:
                return roles
            page += 1

    def seed_roles(self) -> dict[str, str]:
        """Create the missing roles and give each its permissions. Returns name -> id."""
        roles = self._roles_by_name()
        for role in Role:
            if role.value not in roles:
                created = self._write(
                    "POST",
                    "/api/v2/roles",
                    {"name": role.value, "description": role.value.replace("_", " ").capitalize()},
                    f"role {role.value}",
                )
                roles[role.value] = (
                    created["id"] if isinstance(created, dict) else f"<new {role.value}>"
                )
            wanted = ROLE_PERMISSIONS.get(role, frozenset())
            if not wanted:
                continue
            role_id = roles[role.value]
            have: set[str] = set()
            if not role_id.startswith("<new"):
                held = self._get(f"/api/v2/roles/{role_id}/permissions", per_page="100")
                assert isinstance(held, list)
                have = {
                    p["permission_name"]
                    for p in held
                    if p["resource_server_identifier"] == self.audience
                }
            missing = sorted(p.value for p in wanted if p.value not in have)
            if missing:
                self._write(
                    "POST",
                    f"/api/v2/roles/{role_id}/permissions",
                    {
                        "permissions": [
                            {"resource_server_identifier": self.audience, "permission_name": name}
                            for name in missing
                        ]
                    },
                    f"role {role.value}: permissions {missing}",
                )
        return roles

    def assign(self, email: str, role_names: Sequence[str], roles: Mapping[str, str]) -> None:
        """Give the user (by email) the roles they don't hold yet. Auth0 stores emails
        lowercased; an email shared by several Auth0 accounts is refused, not guessed."""
        email = email.strip().lower()
        users = self._get("/api/v2/users-by-email", email=email)
        assert isinstance(users, list)
        if not users:
            raise SystemExit(f"No Auth0 user with email {email}: sign in to the app once first.")
        if len(users) > 1:
            ids = ", ".join(sorted(user["user_id"] for user in users))
            raise SystemExit(
                f"Several Auth0 users have email {email} ({ids}): "
                "assign their roles in the Auth0 dashboard instead."
            )
        for user in users:
            held = self._get(f"/api/v2/users/{quote(user['user_id'], safe='')}/roles")
            assert isinstance(held, list)
            have = {role["name"] for role in held}
            missing = [name for name in role_names if name not in have]
            if missing:
                self._write(
                    "POST",
                    f"/api/v2/users/{quote(user['user_id'], safe='')}/roles",
                    {"roles": [roles[name] for name in missing]},
                    f"user {email} ({user['user_id']}): roles {missing}",
                )


def parse_assignment(value: str) -> tuple[str, list[str]]:
    """`email=role,role` -> (email, [roles]); every role must be a platform `Role`."""
    email, sep, names = value.partition("=")
    roles = [name.strip() for name in names.split(",") if name.strip()]
    known = {role.value for role in Role}
    unknown = [name for name in roles if name not in known]
    if not sep or not email.strip() or not roles or unknown:
        raise argparse.ArgumentTypeError(
            f"expected email=role[,role] with roles from {sorted(known)}; got {value!r}"
        )
    return email.strip(), roles


def management_token(domain: str, client_id: str, client_secret: str) -> str:
    response = httpx.post(
        f"https://{domain}/oauth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": f"https://{domain}/api/v2/",
        },
        timeout=TIMEOUT,
    )
    if response.is_error:
        raise SystemExit(
            f"Could not get a Management API token: {response.status_code} {response.text[:300]}"
        )
    token = response.json()["access_token"]
    assert isinstance(token, str)
    return token


def run(
    client: httpx.Client,
    audience: str,
    assignments: Sequence[tuple[str, list[str]]],
    *,
    dry_run: bool,
) -> Report:
    seeder = Seeder(client, audience, dry_run=dry_run)
    print("API permissions and RBAC settings")
    seeder.seed_api()
    print("Roles and their permissions")
    roles = seeder.seed_roles()
    if assignments:
        print("User roles")
    for email, role_names in assignments:
        seeder.assign(email, role_names, roles)
    return seeder.report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--assign",
        action="append",
        default=[],
        type=parse_assignment,
        metavar="EMAIL=ROLE[,ROLE]",
        help="give a user roles (repeatable); the user must have signed in once",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the changes, make none")
    args = parser.parse_args(argv)

    dotenv = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    env = {
        name: (os.environ.get(name) or dotenv.get(name) or "").strip()
        for name in (
            "AUTH0_DOMAIN",
            "AUTH0_AUDIENCE",
            "AUTH0_MGMT_CLIENT_ID",
            "AUTH0_MGMT_CLIENT_SECRET",
        )
    }
    if missing := [name for name, value in env.items() if not value]:
        print(
            f"Missing {', '.join(missing)}: set them in the environment or in {ENV_FILE}",
            file=sys.stderr,
        )
        return 2
    domain = env["AUTH0_DOMAIN"].removeprefix("https://").rstrip("/")
    token = management_token(domain, env["AUTH0_MGMT_CLIENT_ID"], env["AUTH0_MGMT_CLIENT_SECRET"])
    with httpx.Client(
        base_url=f"https://{domain}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    ) as client:
        report = run(client, env["AUTH0_AUDIENCE"], args.assign, dry_run=args.dry_run)
    verb = "Would make" if args.dry_run else "Made"
    print(f"{verb} {len(report.changes)} change(s).")
    if report.changes and not args.dry_run:
        print("Users see new roles after signing out and back in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
