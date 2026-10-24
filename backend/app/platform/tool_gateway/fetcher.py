"""The research fetcher (Story 5.4): one allowlisted HTTPS page, streamed into the file store.

HTTPS GET only, through httpx, with no automatic redirects, no cookies, no auth headers and
no proxy or `.netrc` settings from the environment (`trust_env=False`). Each redirect hop's
`Location` (at most `MAX_REDIRECTS`) passes the same allowlist check as the first URL before
it is requested; a disallowed hop is `ToolDenied(not_allowlisted)` and is never requested.

Limits: the whole fetch (every hop) must finish within `timeout_s`; the body is streamed
into `platform.storage` and stops past `max_bytes` (a larger declared `Content-Length` stops
before reading); only `text/html` and `text/plain` are accepted. A failure is
`ToolFailed(reason)` and stores nothing. The caller holds no Unit of Work open (AD-25).
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.platform.storage import BlobStore, BlobTooLargeError, StoredBlob
from app.platform.tool_gateway.allowlist import Allowlist
from app.platform.tool_gateway.port import ToolDenied, ToolFailed

MAX_REDIRECTS = 5
ACCEPTED_TYPES = ("text/html", "text/plain")
USER_AGENT = "psa-research-fetch/1"
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """A fetched page: the requested and final URL, status, media type and the stored raw
    body (unchanged, as served after content decoding)."""

    url: str
    final_url: str
    http_status: int
    content_type: str
    """`text/html` or `text/plain` (parameters dropped)."""
    body: StoredBlob


async def fetch(
    url: str,
    *,
    allowlist: Allowlist,
    store: BlobStore,
    timeout_s: float,
    max_bytes: int,
    topic: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchedPage | ToolDenied | ToolFailed:
    """Fetch `url` (module docstring)."""
    if not allowlist.allows(url, topic):
        return ToolDenied("not_allowlisted")
    try:
        async with asyncio.timeout(timeout_s):
            return await _fetch(url, allowlist, store, timeout_s, max_bytes, topic, transport)
    except TimeoutError:
        return ToolFailed("timeout")


async def _fetch(
    url: str,
    allowlist: Allowlist,
    store: BlobStore,
    timeout_s: float,
    max_bytes: int,
    topic: str | None,
    transport: httpx.AsyncBaseTransport | None,
) -> FetchedPage | ToolDenied | ToolFailed:
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        # A fresh client per hop: no cookie set by one response reaches the next request.
        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html, text/plain;q=0.9"},
        ) as client:
            try:
                async with client.stream("GET", current) as response:
                    status = response.status_code
                    if status in _REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            return ToolFailed("http_error", status)
                        if hop == MAX_REDIRECTS:
                            return ToolFailed("too_many_redirects", status)
                        following = urljoin(current, location)
                        if not allowlist.allows(following, topic):
                            return ToolDenied("not_allowlisted")
                        current = following
                        continue
                    if not 200 <= status < 300:
                        return ToolFailed("http_error", status)
                    media = response.headers.get("content-type", "").split(";")[0]
                    media = media.strip().lower()
                    if media not in ACCEPTED_TYPES:
                        return ToolFailed("unsupported_content", status)
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        return ToolFailed("too_large", status)
                    try:
                        blob = await store.put_stream(response.aiter_bytes(), max_bytes)
                    except BlobTooLargeError:
                        return ToolFailed("too_large", status)
                    return FetchedPage(
                        url=url,
                        final_url=current,
                        http_status=status,
                        content_type=media,
                        body=blob,
                    )
            except httpx.TimeoutException:
                return ToolFailed("timeout")
            except httpx.HTTPError:
                return ToolFailed("http_error")
    return ToolFailed("too_many_redirects")  # pragma: no cover - the loop always returns
