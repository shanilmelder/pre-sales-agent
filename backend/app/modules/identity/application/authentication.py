"""Bearer-token authentication (Auth0 access tokens for the API audience).

Tokens are validated with PyJWT against the tenant's JWKS: RS256 only, `iss` must be
`https://{domain}/`, `aud` the API identifier, and `exp`, `iss`, `aud`, `sub` are required.
JWKS fetches are blocking (urllib), so they run in a worker thread, and authentication runs
before the request's Unit of Work opens: no network I/O happens inside an open UoW.

Name and email come from namespaced claims a Post-Login Action adds (see README). A token
without the email claim is rejected; a missing name falls back to the email.

Authorization data also comes from the token (AD-15): Auth0 RBAC's `permissions` claim
("Add Permissions in the Access Token") and the namespaced roles claim the Post-Login Action
adds. Both must be lists of strings. A missing claim grants nothing (never a 401); a
malformed claim, or a non-string item in one, is dropped here and reported in
`TokenIdentity.malformed_claims`, so provisioning can log it with the platform user id.
"""

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.platform.config import Settings
from app.platform.errors import (
    AuthUnavailableError,
    TokenExpiredError,
    TokenInvalidError,
    TokenMissingError,
)
from app.platform.logging import get_logger

ALGORITHM = "RS256"
CLAIM_NAMESPACE = "https://pre-sales-agent/"
NAME_CLAIM = f"{CLAIM_NAMESPACE}name"
EMAIL_CLAIM = f"{CLAIM_NAMESPACE}email"
ROLES_CLAIM = f"{CLAIM_NAMESPACE}roles"
PERMISSIONS_CLAIM = "permissions"
REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub"]

_log = get_logger(__name__)


class SigningKeySource(Protocol):
    """What the validator needs from `jwt.PyJWKClient` (tests substitute a stub)."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


@dataclass(frozen=True, slots=True)
class TokenIdentity:
    """The caller, as proven by a valid access token."""

    sub: str
    name: str
    email: str
    roles: tuple[str, ...] = ()
    """Raw role names from the roles claim; unknown values are filtered by provisioning."""
    permissions: tuple[str, ...] = ()
    """Raw permission names from the `permissions` claim; filtered by provisioning."""
    malformed_claims: tuple[str, ...] = ()
    """Claims that were not lists of strings (wholly or partly dropped)."""


class TokenValidator:
    def __init__(self, *, domain: str, audience: str, keys: SigningKeySource) -> None:
        self._issuer = f"https://{domain}/"
        self._audience = audience
        self._keys = keys

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenValidator":
        """Build the production validator. No network I/O happens until the first token."""
        keys = jwt.PyJWKClient(
            f"https://{settings.auth0_domain}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=settings.auth0_jwks_cache_lifespan_s,
            timeout=settings.auth0_jwks_timeout_s,
        )
        return cls(domain=settings.auth0_domain, audience=settings.auth0_audience, keys=keys)

    async def validate(self, token: str) -> TokenIdentity:
        """Return the token's identity or raise a 401 (`token_expired`, `token_invalid`) or
        503 (`auth_unavailable`) `ProblemError`. Details never echo the token or claims."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise TokenInvalidError("The access token is malformed.") from None
        if header.get("alg") != ALGORITHM:
            raise TokenInvalidError("The access token must be signed with RS256.")
        if not isinstance(header.get("kid"), str):
            raise TokenInvalidError("The access token has no signing key id.")

        try:
            key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
        except (jwt.PyJWKClientConnectionError, jwt.PyJWKSetError, ValueError) as exc:
            _log.warning("auth.jwks_unavailable", extra={"exc_type": type(exc).__name__})
            raise AuthUnavailableError("The sign-in service is not reachable.") from None
        except jwt.PyJWKClientError:
            raise TokenInvalidError("The access token's signing key is unknown.") from None

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("The access token has expired.") from None
        except jwt.InvalidTokenError:
            raise TokenInvalidError("The access token is not valid.") from None
        return _identity(claims)


def _identity(claims: dict[str, Any]) -> TokenIdentity:
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise TokenInvalidError("The access token has no subject.")
    email = claims.get(EMAIL_CLAIM)
    if not isinstance(email, str) or not email.strip():
        raise TokenInvalidError(
            "The access token is missing the profile claims (name, email); "
            "check the Auth0 Post-Login Action."
        )
    name = claims.get(NAME_CLAIM)
    if not isinstance(name, str) or not name.strip():
        name = email
    malformed: list[str] = []
    roles = _string_list(claims, ROLES_CLAIM, malformed)
    permissions = _string_list(claims, PERMISSIONS_CLAIM, malformed)
    return TokenIdentity(
        sub=sub,
        name=name.strip(),
        email=email.strip(),
        roles=roles,
        permissions=permissions,
        malformed_claims=tuple(malformed),
    )


def _string_list(claims: dict[str, Any], claim: str, malformed: list[str]) -> tuple[str, ...]:
    """The claim's string items. Absent: empty. Not a list, or holding non-strings: the
    strings it has (none if not a list), and the claim is recorded as malformed."""
    value = claims.get(claim)
    if value is None:
        return ()
    if not isinstance(value, list):
        malformed.append(claim)
        return ()
    items = tuple(item for item in value if isinstance(item, str))
    if len(items) != len(value):
        malformed.append(claim)
    return items


_bearer = HTTPBearer(auto_error=False, description="Auth0 access token for the API audience.")


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenIdentity:
    """FastAPI dependency: the caller's identity from `Authorization: Bearer <token>`."""
    if credentials is None or not credentials.credentials.strip():
        raise TokenMissingError("This request needs an `Authorization: Bearer` access token.")
    validator: TokenValidator = request.app.state.token_validator
    try:
        return await validator.validate(credentials.credentials.strip())
    except (TokenInvalidError, TokenExpiredError) as exc:
        _log.info("auth.token_rejected", extra={"code": exc.code, "path": request.url.path})
        raise
