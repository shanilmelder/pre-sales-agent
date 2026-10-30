"""Bearer-token authentication (OIDC access tokens for the API audience).

Written against Auth0 and configurable for any OIDC provider (Zitadel, Keycloak, ...): the
issuer, JWKS URL and the claims that carry the profile and roles are settings
(`PSA_AUTH_*`), and every one defaults to the Auth0 convention.

Tokens are validated with PyJWT against the provider's JWKS: RS256 only, `iss` must be the
configured issuer (default `https://{auth0_domain}/`), `aud` the API identifier, and `exp`,
`iss`, `aud`, `sub` are required. JWKS fetches are blocking (urllib), so they run in a worker
thread, and authentication runs before the request's Unit of Work opens: no network I/O
happens inside an open UoW.

Name and email come from claims (Auth0: namespaced claims a Post-Login Action adds, see
README). A token without the email claim is rejected, unless a userinfo endpoint is
configured: then the profile is fetched from it with the same token (providers whose access
tokens carry no profile, like Zitadel). A missing name falls back to the email.

Authorization data also comes from the token (AD-15): the `permissions` claim (Auth0 RBAC,
"Add Permissions in the Access Token") and a roles claim, either a list of names (Auth0) or an
object keyed by name (Zitadel). Where the provider has no permissions of its own, permissions
are derived from the roles (`auth_permissions_from_roles`). Claims must be lists of strings (or,
for roles in `keys` format, an object). A missing claim grants nothing (never a 401); a
malformed claim, or a non-string item in one, is dropped here and reported in
`TokenIdentity.malformed_claims`, so provisioning can log it with the platform user id.
"""

import asyncio
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.modules.identity.domain.role_permissions import ROLE_PERMISSIONS
from app.modules.identity.domain.roles import Role
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
USERINFO_CACHE_TTL_S = 300
USERINFO_CACHE_MAX = 1024

_log = get_logger(__name__)
_ROLES_BY_VALUE = {role.value: role for role in Role}


class SigningKeySource(Protocol):
    """What the validator needs from `jwt.PyJWKClient` (tests substitute a stub)."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class UserinfoSource(Protocol):
    """Blocking lookup of the OIDC userinfo claims for an access token."""

    def fetch(self, token: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ClaimMap:
    """Which claims carry what. The defaults are the Auth0 conventions."""

    email: str = EMAIL_CLAIM
    name: str = NAME_CLAIM
    roles: str = ROLES_CLAIM
    permissions: str = PERMISSIONS_CLAIM
    roles_format: Literal["list", "keys"] = "list"
    permissions_from_roles: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClaimMap":
        return cls(
            email=settings.auth_email_claim or EMAIL_CLAIM,
            name=settings.auth_name_claim or NAME_CLAIM,
            roles=settings.auth_roles_claim or ROLES_CLAIM,
            permissions=settings.auth_permissions_claim or PERMISSIONS_CLAIM,
            roles_format=settings.auth_roles_format,
            permissions_from_roles=settings.auth_permissions_from_roles,
        )


@dataclass(frozen=True, slots=True)
class TokenIdentity:
    """The caller, as proven by a valid access token."""

    sub: str
    name: str
    email: str
    roles: tuple[str, ...] = ()
    """Raw role names from the roles claim; unknown values are filtered by provisioning."""
    permissions: tuple[str, ...] = ()
    """Raw permission names (the `permissions` claim, plus any derived from the roles);
    filtered by provisioning."""
    malformed_claims: tuple[str, ...] = ()
    """Claims that were not lists of strings (wholly or partly dropped)."""


class HttpUserinfo:
    """The OIDC userinfo endpoint, called with the caller's access token. Responses are cached
    per token (by hash) for a few minutes, so a page of API calls costs one lookup."""

    def __init__(self, url: str, *, timeout_s: float) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def fetch(self, token: str) -> dict[str, Any]:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
        request = urllib.request.Request(  # noqa: S310 - operator-configured https URL
            self._url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise TokenInvalidError(
                    "The identity provider rejected the access token."
                ) from None
            _log.warning("auth.userinfo_unavailable", extra={"status": exc.code})
            raise AuthUnavailableError("The sign-in service is not reachable.") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            _log.warning("auth.userinfo_unavailable", extra={"exc_type": type(exc).__name__})
            raise AuthUnavailableError("The sign-in service is not reachable.") from None
        if not isinstance(data, dict):
            raise AuthUnavailableError("The sign-in service returned an unexpected response.")
        with self._lock:
            self._cache[key] = (now + USERINFO_CACHE_TTL_S, data)
            while len(self._cache) > USERINFO_CACHE_MAX:
                self._cache.popitem(last=False)
        return data


class TokenValidator:
    def __init__(
        self,
        *,
        audience: str,
        keys: SigningKeySource,
        domain: str = "",
        issuer: str | None = None,
        claims: ClaimMap | None = None,
        userinfo: UserinfoSource | None = None,
    ) -> None:
        self._issuer = issuer or f"https://{domain}/"
        self._audience = audience
        self._keys = keys
        self._map = claims or ClaimMap()
        self._userinfo = userinfo

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenValidator":
        """Build the production validator. No network I/O happens until the first token."""
        domain = settings.auth0_domain
        keys = jwt.PyJWKClient(
            settings.auth_jwks_url or f"https://{domain}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=settings.auth0_jwks_cache_lifespan_s,
            timeout=settings.auth0_jwks_timeout_s,
        )
        userinfo = (
            HttpUserinfo(settings.auth_userinfo_url, timeout_s=settings.auth0_jwks_timeout_s)
            if settings.auth_userinfo_url
            else None
        )
        return cls(
            domain=domain,
            issuer=settings.auth_issuer or None,
            audience=settings.auth0_audience,
            keys=keys,
            claims=ClaimMap.from_settings(settings),
            userinfo=userinfo,
        )

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

        if self._userinfo is not None and not _text(claims.get(self._map.email)):
            profile = await asyncio.to_thread(self._userinfo.fetch, token)
            if profile.get("sub") != claims.get("sub"):
                raise TokenInvalidError("The access token does not match its profile.")
            claims = {**profile, **claims}  # the token's own claims win
        return _identity(claims, self._map)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identity(claims: dict[str, Any], claim_map: ClaimMap = ClaimMap()) -> TokenIdentity:  # noqa: B008
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise TokenInvalidError("The access token has no subject.")
    email = _text(claims.get(claim_map.email))
    if not email:
        raise TokenInvalidError(
            "The access token is missing the profile claims (name, email); "
            "check the identity provider's claim configuration."
        )
    name = _text(claims.get(claim_map.name)) or email
    malformed: list[str] = []
    roles = _roles(claims, claim_map, malformed)
    permissions = _string_list(claims, claim_map.permissions, malformed)
    if claim_map.permissions_from_roles:
        permissions = _with_role_permissions(permissions, roles)
    return TokenIdentity(
        sub=sub,
        name=name,
        email=email,
        roles=roles,
        permissions=permissions,
        malformed_claims=tuple(malformed),
    )


def _roles(claims: dict[str, Any], claim_map: ClaimMap, malformed: list[str]) -> tuple[str, ...]:
    if claim_map.roles_format == "list":
        return _string_list(claims, claim_map.roles, malformed)
    value = claims.get(claim_map.roles)
    if value is None:
        return ()
    if not isinstance(value, dict):
        malformed.append(claim_map.roles)
        return ()
    names = tuple(key for key in value if isinstance(key, str))
    if len(names) != len(value):
        malformed.append(claim_map.roles)
    return names


def _with_role_permissions(held: tuple[str, ...], roles: tuple[str, ...]) -> tuple[str, ...]:
    """`held` plus the permissions the known roles grant (unknown roles grant nothing)."""
    derived = {
        action.value
        for name in roles
        if (role := _ROLES_BY_VALUE.get(name)) is not None
        for action in ROLE_PERMISSIONS[role]
    }
    return held + tuple(sorted(derived - set(held)))


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


_bearer = HTTPBearer(auto_error=False, description="Access token for the API audience.")


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
