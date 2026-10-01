"""Test tokens: a generated RSA key, a stubbed JWKS endpoint and an app wired to them."""

import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI

from app.main_api import create_app
from app.modules.identity.application.public import TokenValidator
from app.platform.config import Settings

DOMAIN = "psa-test.eu.auth0.com"
ISSUER = f"https://{DOMAIN}/"
AUDIENCE = "https://api.pre-sales-agent.test"
KID = "test-key-1"
NAME_CLAIM = "https://pre-sales-agent/name"
EMAIL_CLAIM = "https://pre-sales-agent/email"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_for(key: rsa.RSAPrivateKey = KEY, kid: str = KID) -> dict[str, Any]:
    jwk: dict[str, Any] = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid=kid, use="sig", alg="RS256")
    return {"keys": [jwk]}


class StubJWKSClient(jwt.PyJWKClient):
    """A real `PyJWKClient` (kid matching, caching) whose HTTP fetch is replaced."""

    def __init__(self, jwks: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        super().__init__(f"https://{DOMAIN}/.well-known/jwks.json", cooldown_duration=0)
        self.jwks = jwks if jwks is not None else jwks_for()
        self.error = error
        self.fetches = 0
        self.on_fetch: list[str] = []

    def fetch_data(self) -> Any:
        self.fetches += 1
        self.on_fetch.append("jwks")
        if self.error is not None:
            raise self.error
        return self.jwks


def claims(sub: str | None = "auth0|test-user", **overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "aud": [AUDIENCE, f"{ISSUER}userinfo"],
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        NAME_CLAIM: "Test Person",
        EMAIL_CLAIM: "person@example.test",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def make_token(
    payload: dict[str, Any] | None = None,
    *,
    key: Any = KEY,
    kid: str | None = KID,
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(
        payload if payload is not None else claims(), key, algorithm=algorithm, headers=headers
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def auth_app(database_url: str, keys: StubJWKSClient | None = None) -> FastAPI:
    settings = Settings(database_url=database_url, auth0_domain=DOMAIN, auth0_audience=AUDIENCE)
    app = create_app(settings)
    app.state.token_validator = TokenValidator(
        domain=DOMAIN, audience=AUDIENCE, keys=keys or StubJWKSClient()
    )
    return app
