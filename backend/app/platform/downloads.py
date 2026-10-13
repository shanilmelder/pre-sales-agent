"""Short-lived signed download links for stored files (Story 3.2, AD-18).

A module that has checked the caller's access (e.g. knowledge, for an earlier Knowledge
Source version) asks `sign` for a link to a stored blob. The link carries the blob's SHA-256,
the file name to download it as and an expiry, signed with HMAC-SHA256 under
`PSA_DOWNLOAD_SIGNING_KEY`. `GET /api/v1/downloads/{token}` verifies the signature and the
expiry and streams the blob; the token is the credential, so links are meant to be fetched
at once and expire after `PSA_DOWNLOAD_LINK_TTL_S` seconds. A bad, tampered or expired
token is a 403 `forbidden`.

The blob is served unchanged as an attachment (`application/octet-stream`, `nosniff`), never
rendered by the browser. Logs carry the blob's hash only, never the file name.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, ForbiddenError, NotFoundError, Problem
from app.platform.logging import get_logger
from app.platform.storage import BlobStore

DOWNLOADS_PATH = "/api/v1/downloads"
INVALID_LINK = "This download link is invalid or has expired."
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Download:
    """What a verified token grants: one stored blob, downloaded as `filename`."""

    sha256: str
    filename: str
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(key: str, body: str) -> str:
    return _b64(hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest())


def sign(
    key: str, *, sha256: str, filename: str, ttl_s: int, now: float | None = None
) -> tuple[str, datetime]:
    """A token for the blob and the moment it expires."""
    if not _SHA256_RE.match(sha256):
        raise ValueError("not a lowercase hex SHA-256")
    expires = int(time.time() if now is None else now) + ttl_s
    payload = {"h": sha256, "n": filename, "e": expires}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_mac(key, body)}", datetime.fromtimestamp(expires, UTC)


def verify(key: str, token: str, *, now: float | None = None) -> Download:
    """The grant in a token. Raises `ForbiddenError` for anything malformed, tampered with
    or expired."""
    body, dot, signature = token.partition(".")
    if (
        not dot
        or not body
        or not hmac.compare_digest(
            _mac(key, body).encode("ascii"), signature.encode("utf-8", errors="replace")
        )
    ):
        raise ForbiddenError(INVALID_LINK)
    try:
        payload: Any = json.loads(_unb64(body))
        sha256, filename, expires = payload["h"], payload["n"], payload["e"]
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise ForbiddenError(INVALID_LINK) from None
    if (
        not isinstance(sha256, str)
        or not _SHA256_RE.match(sha256)
        or not isinstance(filename, str)
        or not isinstance(expires, int)
        or expires < (time.time() if now is None else now)
    ):
        raise ForbiddenError(INVALID_LINK)
    return Download(
        sha256=sha256, filename=filename, expires_at=datetime.fromtimestamp(expires, UTC)
    )


def link_for(token: str) -> str:
    """The path (relative to the API origin) that serves the token."""
    return f"{DOWNLOADS_PATH}/{token}"


router = APIRouter(tags=["downloads"])
_PROBLEM = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}


@router.get(
    "/downloads/{token}",
    operation_id="download_file",
    response_class=FileResponse,
    responses={
        200: {"description": "The stored file, unchanged, as an attachment"},
        403: {
            "description": "The link is invalid or has expired (`forbidden`)",
            "content": _PROBLEM,
        },
        404: {"description": "The file is no longer stored (`not_found`)", "content": _PROBLEM},
        422: {"description": "The token is not usable (`validation_error`)", "content": _PROBLEM},
    },
)
async def download_file(token: str, request: Request) -> FileResponse:
    """Stream the file a signed link names. The token is the credential: no sign-in."""
    settings: Settings = request.app.state.settings
    grant = verify(settings.download_signing_key, token)
    path = BlobStore(settings.storage_dir).path_for(grant.sha256)
    if not path.is_file():
        raise NotFoundError("The file is no longer available.")
    _log.info("platform.download_served", extra={"sha256": grant.sha256})
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=grant.filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["DOWNLOADS_PATH", "Download", "link_for", "router", "sign", "verify"]
