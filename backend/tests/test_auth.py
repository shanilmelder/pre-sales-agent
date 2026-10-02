"""Bearer-token validation: every auth failure row of the Story 1.4 Part B I/O matrix.

These run without a database: authentication fails before the Unit of Work opens.
"""

from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main_api import create_app
from app.platform.config import Settings
from tests.auth_tokens import (
    EMAIL_CLAIM,
    OTHER_KEY,
    StubJWKSClient,
    auth_app,
    bearer,
    claims,
    jwks_for,
    make_token,
)
from tests.conftest import UNREACHABLE_DB, make_client
from tests.test_health import assert_problem


def _client(keys: StubJWKSClient | None = None) -> TestClient:
    return make_client(auth_app(UNREACHABLE_DB, keys))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client() as c:
        yield c


def _assert_401(resp: Any, code: str) -> None:
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["WWW-Authenticate"].startswith("Bearer")
    assert_problem(resp.json(), 401, code)
    assert resp.json()["instance"] == "/api/v1/me"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}],
    ids=["absent", "empty", "bearer-without-token", "other-scheme"],
)
def test_missing_token_is_401_token_missing(client: TestClient, headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/me", headers=headers)
    _assert_401(resp, "token_missing")
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_401_token_expired(client: TestClient) -> None:
    token = make_token(claims(exp=1_000_000_000, iat=999_999_000))
    resp = client.get("/api/v1/me", headers=bearer(token))
    _assert_401(resp, "token_expired")
    assert token not in resp.text


def _hs256_token() -> str:
    return jwt.encode(claims(), "x" * 32, algorithm="HS256", headers={"kid": "test-key-1"})


def _none_alg_token() -> str:
    return jwt.encode(claims(), "", algorithm="none", headers={"kid": "test-key-1"})


WRONG_TOKENS = {
    "bad-signature": lambda: make_token(key=OTHER_KEY),
    "alg-hs256": _hs256_token,
    "alg-none": _none_alg_token,
    "wrong-issuer": lambda: make_token(claims(iss="https://evil.eu.auth0.com/")),
    "wrong-audience": lambda: make_token(claims(aud="https://some-other-api")),
    "unknown-kid": lambda: make_token(kid="rotated-away"),
    "no-kid": lambda: make_token(kid=None),
    "missing-exp": lambda: make_token(claims(exp=None)),
    "missing-sub": lambda: make_token(claims(sub=None)),
    "empty-sub": lambda: make_token(claims(sub="")),
    "alg-rs384-real-key": lambda: make_token(algorithm="RS384"),
    "malformed": lambda: "not.a.jwt",
    "garbage": lambda: "garbage",
}


@pytest.mark.parametrize("make", WRONG_TOKENS.values(), ids=WRONG_TOKENS.keys())
def test_wrong_token_is_401_token_invalid(client: TestClient, make: Any) -> None:
    token = make()
    resp = client.get("/api/v1/me", headers=bearer(token))
    _assert_401(resp, "token_invalid")
    assert token not in resp.text


def test_token_without_email_claim_is_401_with_profile_detail(client: TestClient) -> None:
    token = make_token(claims(**{EMAIL_CLAIM: None}))
    resp = client.get("/api/v1/me", headers=bearer(token))
    _assert_401(resp, "token_invalid")
    assert "profile claims" in resp.json()["detail"]


def test_jwks_unreachable_is_503_auth_unavailable() -> None:
    keys = StubJWKSClient(error=jwt.PyJWKClientConnectionError("connection refused"))
    with _client(keys) as client:
        resp = client.get("/api/v1/me", headers=bearer(make_token()))
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), 503, "auth_unavailable")
    assert "refused" not in resp.text


def test_jwks_is_cached_between_requests() -> None:
    keys = StubJWKSClient()
    with _client(keys) as client:
        for _ in range(3):
            client.get("/api/v1/me", headers=bearer(make_token(claims(exp=1_000_000_000))))
    assert keys.fetches == 1


def test_rotated_key_is_picked_up_by_refetching_jwks() -> None:
    keys = StubJWKSClient()
    with _client(keys) as client:
        client.get("/api/v1/me", headers=bearer(make_token(claims(exp=1_000_000_000))))
        keys.jwks = jwks_for(OTHER_KEY, kid="rotated-in")
        token = make_token(claims(exp=1_000_000_000), key=OTHER_KEY, kid="rotated-in")
        resp = client.get("/api/v1/me", headers=bearer(token))
    # The new key validates the signature, so the token gets as far as its expiry check.
    _assert_401(resp, "token_expired")


def test_health_endpoints_stay_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 503  # the DB is down here; the point is: not 401
    assert resp.json()["code"] == "db_unavailable"


def test_validator_uses_tenant_issuer_and_jwks_url() -> None:
    settings = Settings(
        auth0_domain="tenant.eu.auth0.com",
        auth0_audience="https://api.configured.test",
        auth0_jwks_cache_lifespan_s=123,
        auth0_jwks_timeout_s=7,
    )
    app = create_app(settings)
    validator = app.state.token_validator
    assert validator._issuer == "https://tenant.eu.auth0.com/"
    assert validator._audience == settings.auth0_audience
    keys = validator._keys
    assert keys.uri == "https://tenant.eu.auth0.com/.well-known/jwks.json"
    assert keys.jwk_set_cache is not None
    assert keys.jwk_set_cache.lifespan == 123
    assert keys.timeout == 7


def test_openapi_documents_me_with_bearer_security(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    op = spec["paths"]["/api/v1/me"]["get"]
    assert op["operationId"] == "get_me"
    assert {"401", "503"} <= set(op["responses"])
    assert op["security"] == [{"HTTPBearer": []}]
