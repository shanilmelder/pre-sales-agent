"""The Auth0 seed script (Story 1.9) against an in-memory fake of the Management API: it
creates what is missing, keeps what is there, and a second run changes nothing."""

import argparse
import json
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from app.modules.identity.domain.roles import Role
from scripts.seed_auth0 import ROLE_PERMISSIONS, parse_assignment, run

AUDIENCE = "https://api.pre-sales-agent"


class FakeTenant:
    def __init__(self) -> None:
        self.api: dict[str, Any] = {
            "id": "rs1",
            "identifier": AUDIENCE,
            "scopes": [{"value": "legacy.kept", "description": "kept"}],
            "enforce_policies": False,
            "token_dialect": "access_token",
        }
        self.roles: dict[str, dict[str, Any]] = {
            "r-existing": {"id": "r-existing", "name": "commercial", "permissions": set()}
        }
        self.user_roles: dict[str, set[str]] = {"auth0|me": set()}
        self.writes = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        body = json.loads(request.content) if request.content else None
        if request.method != "GET":
            self.writes += 1
        if path == f"/api/v2/resource-servers/{AUDIENCE}" and request.method == "GET":
            return httpx.Response(200, json=self.api)
        if path == "/api/v2/resource-servers/rs1" and request.method == "PATCH":
            self.api.update(body)
            return httpx.Response(200, json=self.api)
        if path == "/api/v2/roles" and request.method == "GET":
            roles = [{"id": r["id"], "name": r["name"]} for r in self.roles.values()]
            return httpx.Response(200, json={"roles": roles, "total": len(roles)})
        if path == "/api/v2/roles" and request.method == "POST":
            role_id = f"r-{body['name']}"
            self.roles[role_id] = {"id": role_id, "name": body["name"], "permissions": set()}
            return httpx.Response(200, json={"id": role_id, "name": body["name"]})
        if path.startswith("/api/v2/roles/") and path.endswith("/permissions"):
            role = self.roles[path.split("/")[4]]
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {"permission_name": p, "resource_server_identifier": AUDIENCE}
                        for p in sorted(role["permissions"])
                    ],
                )
            role["permissions"] |= {p["permission_name"] for p in body["permissions"]}
            return httpx.Response(201)
        if path == "/api/v2/users-by-email":
            email = request.url.params["email"]
            if email == "shared@example.com":
                return httpx.Response(200, json=[{"user_id": "auth0|b"}, {"user_id": "auth0|a"}])
            known = email == "me@example.com"
            return httpx.Response(200, json=[{"user_id": "auth0|me"}] if known else [])
        if path == "/api/v2/users/auth0|me/roles":
            if request.method == "GET":
                names = [self.roles[r]["name"] for r in sorted(self.user_roles["auth0|me"])]
                return httpx.Response(200, json=[{"name": n} for n in names])
            self.user_roles["auth0|me"] |= set(body["roles"])
            return httpx.Response(204)
        return httpx.Response(404, json={"path": path})


def _client(tenant: FakeTenant) -> httpx.Client:
    return httpx.Client(
        base_url="https://t.eu.auth0.com", transport=httpx.MockTransport(tenant.handle)
    )


def test_seeds_the_tenant_and_a_second_run_changes_nothing() -> None:
    tenant = FakeTenant()
    assign = [("me@example.com", ["platform_administrator", "presales_engineer"])]
    with _client(tenant) as client:
        first = run(client, AUDIENCE, assign, dry_run=False)
        writes = tenant.writes
        second = run(client, AUDIENCE, assign, dry_run=False)

    assert first.changes and second.changes == []
    assert tenant.writes == writes
    assert tenant.api["enforce_policies"] is True
    assert tenant.api["token_dialect"] == "access_token_authz"
    scopes = {s["value"] for s in tenant.api["scopes"]}
    assert "legacy.kept" in scopes
    assert {"identity.user.list", "identity.user.search"} <= scopes
    by_name = {r["name"]: r for r in tenant.roles.values()}
    assert set(by_name) == {role.value for role in Role}
    assert by_name["commercial"]["id"] == "r-existing"
    for role in Role:
        expected = {p.value for p in ROLE_PERMISSIONS.get(role, frozenset())}
        assert by_name[role.value]["permissions"] == expected
    assert {tenant.roles[r]["name"] for r in tenant.user_roles["auth0|me"]} == {
        "platform_administrator",
        "presales_engineer",
    }


def test_dry_run_reports_changes_and_writes_nothing() -> None:
    tenant = FakeTenant()
    with _client(tenant) as client:
        report = run(client, AUDIENCE, [], dry_run=True)
    assert report.changes
    assert tenant.writes == 0


def test_assigning_to_an_unknown_email_stops() -> None:
    tenant = FakeTenant()
    with _client(tenant) as client, pytest.raises(SystemExit, match="sign in to the app"):
        run(client, AUDIENCE, [("nobody@example.com", ["commercial"])], dry_run=False)


@pytest.mark.parametrize("value", ["me@example.com", "=commercial", "me@example.com=intern"])
def test_bad_assignments_are_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_assignment(value)


def test_assignment_parses() -> None:
    assert parse_assignment(" me@example.com = commercial, head_of_delivery ") == (
        "me@example.com",
        ["commercial", "head_of_delivery"],
    )


def test_assign_lowercases_and_strips_the_email() -> None:
    tenant = FakeTenant()
    with _client(tenant) as client:
        run(client, AUDIENCE, [("  Me@Example.COM ", ["commercial"])], dry_run=False)
    assert {tenant.roles[r]["name"] for r in tenant.user_roles["auth0|me"]} == {"commercial"}


def test_assigning_to_an_email_shared_by_several_users_stops() -> None:
    tenant = FakeTenant()
    with (
        _client(tenant) as client,
        pytest.raises(SystemExit, match=r"auth0\|a, auth0\|b.*Auth0 dashboard"),
    ):
        run(client, AUDIENCE, [("shared@example.com", ["commercial"])], dry_run=False)
    assert tenant.user_roles["auth0|me"] == set()
