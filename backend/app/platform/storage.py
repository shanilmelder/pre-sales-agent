"""Content-addressed file storage (AD-18). A local volume in R1; no database access here.

Files are stored unchanged, named by the SHA-256 of their bytes at
`<root>/sha256/ab/cd/<sha256>` and never rewritten once they exist. `put_stream` writes the
incoming chunks to a temp file under `<root>/tmp/` while hashing and counting them, so a
body is never held in memory, then links the finished temp file into place atomically.
Whatever goes wrong (too large, a failed `check`, a cancelled request), the temp file is
removed and nothing is stored.

Reference counts live in `platform_files` (`app.platform.files`), written by the caller in
its Unit of Work after the blob exists. A blob orphaned by a failed transaction is
acceptable in R1.
"""

import asyncio
import contextlib
import hashlib
import os
import re
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.platform.ids import new_id

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BlobTooLargeError(Exception):
    """The stream passed `max_bytes`. Nothing was stored."""


@dataclass(frozen=True, slots=True)
class StoredBlob:
    sha256: str
    size: int


BlobCheck = Callable[[BinaryIO, int], None]
"""Inspects the complete temp file (opened for reading, and its size) before it is stored;
raising rejects it."""


class BlobStore:
    """The file store rooted at `root` (`PSA_STORAGE_DIR`)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, sha256: str) -> Path:
        """Where the blob with this SHA-256 (lowercase hex) lives."""
        if not _SHA256_RE.match(sha256):
            raise ValueError("not a lowercase hex SHA-256")
        return self._root / "sha256" / sha256[:2] / sha256[2:4] / sha256

    async def put_stream(
        self,
        chunks: AsyncIterable[bytes],
        max_bytes: int,
        *,
        check: BlobCheck | None = None,
    ) -> StoredBlob:
        """Store the streamed bytes and return their SHA-256 and size.

        Raises `BlobTooLargeError` as soon as more than `max_bytes` arrive. `check` runs on
        the complete temp file before it is stored; whatever it raises propagates. In both
        cases, and on any other error, the temp file is deleted and nothing is stored. An
        existing blob with the same hash is kept as it is."""
        tmp_dir = self._root / "tmp"
        await asyncio.to_thread(tmp_dir.mkdir, parents=True, exist_ok=True)
        tmp = tmp_dir / f"{new_id()}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            handle = await asyncio.to_thread(tmp.open, "xb")
            try:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise BlobTooLargeError
                    digest.update(chunk)
                    await asyncio.to_thread(handle.write, chunk)
            finally:
                await asyncio.to_thread(handle.close)
            if check is not None:
                await asyncio.to_thread(_run_check, tmp, size, check)
            sha256 = digest.hexdigest()
            await asyncio.to_thread(_link_into_place, tmp, self.path_for(sha256))
            return StoredBlob(sha256=sha256, size=size)
        finally:
            await asyncio.to_thread(_unlink_quietly, tmp)


def _run_check(path: Path, size: int, check: BlobCheck) -> None:
    with path.open("rb") as handle:
        check(handle, size)


def _link_into_place(tmp: Path, final: Path) -> None:
    """Make `final` the stored blob without ever overwriting an existing one: a hard link
    fails if the target exists. Filesystems without hard links fall back to a rename,
    still only when the target is missing."""
    if final.exists():
        return
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(tmp, final)
    except FileExistsError:
        return
    except OSError:
        if not final.exists():
            os.replace(tmp, final)


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
