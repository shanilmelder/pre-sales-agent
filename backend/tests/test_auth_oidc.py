"""Generic OIDC providers (Zitadel-style): issuer, claim mapping, roles as an object, permissions
derived from roles, and the userinfo fallback. Auth0 behaviour is covered by `test_auth.py`."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.modules.identity.application.authentication import (
    ClaimMap,
    HttpUserinfo,
    TokenValidator,
)
from app.modules.identity.domain.role_permissions import ROLE_PERMISSIONS
from app.modules.identity.domain.roles import Role
from app.platform.config import Settings
from app.platform.errors import AuthUnavailableError, TokenInvalidError
from tests.auth_tokens import AUDIENCE, StubJWKSClient, claims, make_token

ISSUER = "https://auth.example.test"  # no trailing slash, as Zitadel issues it
ROLES = "urn:zitadel:iam:org:project:roles"
ZITADEL_MAP = ClaimMap(
    email="email", name="name", roles=ROLES, roles_format="keys", permissions_from_roles=True
)


def zitadel_claims(**overrides: Any) -> dict[str, Any]:
    base = claims(
        sub="2871000000000001",
        iss=ISSUER,
        aud=[AUDIENCE, "client-1"],
        email="eng@example.test",
        name="Eng Person",
    )
    base.pop("https://pre-sales-agent/name", None)
    base.pop("https://pre-sales-agent/email", None)
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


class StubUserinfo:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.calls = 0

    def fetch(self, token: str) -> dict[str, Any]:
        self.calls += 1
        return self.profile


def validator(claim_map: ClaimMap = ZITADEL_MAP, userinfo: Any = None) -> TokenValidator:
    return TokenValidator(
        issuer=ISSUER,
        audience=AUDIENCE,
        keys=StubJWKSClient(),
        claims=claim_map,
        userinfo=userinfo,
    )


def validate(v: TokenValidator, payload: dict[str, Any]) -> Any:
    return asyncio.run(v.validate(make_token(payload)))


def test_roles_object_and_standard_claims() -> None:
    identity = validate(
        validator(), zitadel_claims(**{ROLES: {Role.PLATFORM_ADMINISTRATOR.value: {"org": "d"}}})
    )
    assert identity.sub == "2871000000000001"
    assert (identity.name, identity.email) == ("Eng Person", "eng@example.test")
    assert identity.roles == (Role.PLATFORM_ADMINISTRATOR.value,)
    assert identity.malformed_claims == ()


def test_permissions_are_derived_from_roles() -> None:
    role = Role.PLATFORM_ADMINISTRATOR
    identity = validate(validator(), zitadel_claims(**{ROLES: {role.value: {}}}))
    expected = {action.value for action in ROLE_PERMISSIONS[role]}
    assert expected  # the role does hold permissions
    assert set(identity.permissions) == expected


def test_unknown_roles_derive_nothing() -> None:
    identity = validate(validator(), zitadel_claims(**{ROLES: {"made_up_role": {}}}))
    assert identity.roles == ("made_up_role",)
    assert identity.permissions == ()


def test_derivation_is_off_by_default() -> None:
    claim_map = ClaimMap(email="email", name="name", roles=ROLES, roles_format="keys")
    identity = validate(
        validator(claim_map), zitadel_claims(**{ROLES: {Role.PLATFORM_ADMINISTRATOR.value: {}}})
    )
    assert identity.permissions == ()


def test_roles_claim_in_the_wrong_shape_is_malformed_not_fatal() -> None:
    identity = validate(validator(), zitadel_claims(**{ROLES: ["platform_administrator"]}))
    assert identity.roles == ()
    assert identity.malformed_claims == (ROLES,)


def test_issuer_must_match_exactly() -> None:
    with pytest.raises(TokenInvalidError):
        validate(validator(), zitadel_claims(iss=ISSUER + "/"))


def test_missing_email_without_userinfo_is_rejected() -> None:
    with pytest.raises(TokenInvalidError, match="profile claims"):
        validate(validator(), zitadel_claims(email=None))


def test_userinfo_completes_a_token_without_a_profile() -> None:
    userinfo = StubUserinfo(
        {
            "sub": "2871000000000001",
            "email": "from-userinfo@example.test",
            "name": "From Userinfo",
            ROLES: {Role.PLATFORM_ADMINISTRATOR.value: {}},
        }
    )
    identity = validate(validator(userinfo=userinfo), zitadel_claims(email=None, name=None))
    assert (identity.name, identity.email) == ("From Userinfo", "from-userinfo@example.test")
    assert identity.roles == (Role.PLATFORM_ADMINISTRATOR.value,)
    assert userinfo.calls == 1


def test_userinfo_is_not_called_when_the_token_has_an_email() -> None:
    userinfo = StubUserinfo({"sub": "2871000000000001", "email": "other@example.test"})
    identity = validate(validator(userinfo=userinfo), zitadel_claims())
    assert identity.email == "eng@example.test"
    assert userinfo.calls == 0


def test_token_claims_win_over_userinfo() -> None:
    userinfo = StubUserinfo({"sub": "2871000000000001", "email": "x@example.test", "name": "X"})
    identity = validate(validator(userinfo=userinfo), zitadel_claims(email=None))
    assert identity.email == "x@example.test"
    assert identity.name == "Eng Person"  # the token had a name; userinfo's is ignored


def test_userinfo_for_another_subject_is_rejected() -> None:
    userinfo = StubUserinfo({"sub": "someone-else", "email": "x@example.test"})
    with pytest.raises(TokenInvalidError, match="does not match"):
        validate(validator(userinfo=userinfo), zitadel_claims(email=None))


def test_claim_map_from_settings_defaults_to_auth0() -> None:
    assert ClaimMap.from_settings(Settings()) == ClaimMap()


def test_claim_map_from_settings_overrides() -> None:
    settings = Settings(
        auth_email_claim="email",
        auth_roles_claim=ROLES,
        auth_roles_format="keys",
        auth_permissions_from_roles=True,
    )
    claim_map = ClaimMap.from_settings(settings)
    assert (claim_map.email, claim_map.roles) == ("email", ROLES)
    assert claim_map.roles_format == "keys"
    assert claim_map.permissions_from_roles is True
    assert claim_map.name == ClaimMap().name  # untouched settings keep the Auth0 default


class _Userinfo(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:
        type(self).hits += 1
        if self.headers.get("Authorization") == "Bearer rejected":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"sub": "u1", "email": "u1@example.test"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def userinfo_url() -> Any:
    _Userinfo.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Userinfo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/userinfo"
    server.shutdown()


def test_http_userinfo_caches_per_token(userinfo_url: str) -> None:
    source = HttpUserinfo(userinfo_url, timeout_s=2)
    assert source.fetch("tok-a")["email"] == "u1@example.test"
    source.fetch("tok-a")
    assert _Userinfo.hits == 1
    source.fetch("tok-b")
    assert _Userinfo.hits == 2


def test_http_userinfo_rejection_is_an_invalid_token(userinfo_url: str) -> None:
    with pytest.raises(TokenInvalidError):
        HttpUserinfo(userinfo_url, timeout_s=2).fetch("rejected")


def test_http_userinfo_unreachable_is_auth_unavailable() -> None:
    with pytest.raises(AuthUnavailableError):
        HttpUserinfo("http://127.0.0.1:9/userinfo", timeout_s=1).fetch("tok")
