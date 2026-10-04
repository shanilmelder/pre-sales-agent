"""`platform.storage` (AD-18) and the streaming multipart reader. No DB."""

import hashlib
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import BinaryIO

import pytest
from starlette.requests import ClientDisconnect

from app.platform.multipart import BodyTooLargeError, MultipartError, MultipartFile
from app.platform.storage import BlobStore, BlobTooLargeError
from tests.conftest import run_async


async def _stream(chunks: Iterable[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _tmp_files(root: Path) -> list[Path]:
    tmp = root / "tmp"
    return sorted(tmp.iterdir()) if tmp.exists() else []


# --- BlobStore --------------------------------------------------------------------------------


def test_put_stream_stores_bytes_unchanged_by_sha256(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    data = b"hello " * 1000

    blob = run_async(store.put_stream(_stream([data[:100], b"", data[100:]]), max_bytes=10_000))

    sha = hashlib.sha256(data).hexdigest()
    assert (blob.sha256, blob.size) == (sha, len(data))
    path = store.path_for(sha)
    assert path == tmp_path / "sha256" / sha[:2] / sha[2:4] / sha
    assert path.read_bytes() == data
    assert _tmp_files(tmp_path) == []


def test_existing_blob_is_never_rewritten(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    first = run_async(store.put_stream(_stream([b"same bytes"]), max_bytes=100))
    path = store.path_for(first.sha256)
    before = path.stat().st_mtime_ns
    path_inode = path.stat().st_ino

    second = run_async(store.put_stream(_stream([b"same ", b"bytes"]), max_bytes=100))

    assert second == first
    assert path.stat().st_mtime_ns == before
    assert path.stat().st_ino == path_inode
    assert len(_files_under(tmp_path)) == 1


def test_exactly_max_bytes_is_accepted(tmp_path: Path) -> None:
    blob = run_async(BlobStore(tmp_path).put_stream(_stream([b"x" * 64]), max_bytes=64))
    assert blob.size == 64


def test_too_large_stops_reading_and_leaves_nothing(tmp_path: Path) -> None:
    read: list[int] = []

    async def chunks() -> AsyncIterator[bytes]:
        for i in range(100):
            read.append(i)
            yield b"x" * 10

    with pytest.raises(BlobTooLargeError):
        run_async(BlobStore(tmp_path).put_stream(chunks(), max_bytes=25))

    assert len(read) == 3  # stopped as soon as the limit was passed
    assert _files_under(tmp_path) == []


def test_failed_check_stores_nothing(tmp_path: Path) -> None:
    seen: list[tuple[bytes, int]] = []

    def check(stream: BinaryIO, size: int) -> None:
        seen.append((stream.read(), size))
        raise ValueError("rejected")

    with pytest.raises(ValueError, match="rejected"):
        run_async(BlobStore(tmp_path).put_stream(_stream([b"ab", b"c"]), 100, check=check))

    assert seen == [(b"abc", 3)]
    assert _files_under(tmp_path) == []


def test_failing_stream_leaves_no_temp_file(tmp_path: Path) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"partial"
        raise ConnectionError("client went away")

    with pytest.raises(ConnectionError):
        run_async(BlobStore(tmp_path).put_stream(chunks(), max_bytes=100))
    assert _files_under(tmp_path) == []


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "../" + "a" * 61])
def test_path_for_rejects_non_sha256(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        BlobStore(tmp_path).path_for(bad)


# --- MultipartFile ----------------------------------------------------------------------------

BOUNDARY = "----psa-test-boundary"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


def _part(name: str, data: bytes, filename: str | None = None) -> bytes:
    disposition = f'form-data; name="{name}"'
    if filename is not None:
        disposition += f'; filename="{filename}"'
    return (
        (
            f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + b"\r\n"
    )


def _body(*parts: bytes) -> bytes:
    return b"".join(parts) + f"--{BOUNDARY}--\r\n".encode()


def _split(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


async def _read(reader: MultipartFile) -> tuple[str, bytes]:
    name = await reader.filename()
    data = b"".join([chunk async for chunk in reader.chunks()])
    return name, data


@pytest.mark.parametrize("chunk_size", [1, 7, 1024, 1 << 20])
def test_multipart_streams_the_file_part(chunk_size: int) -> None:
    payload = bytes(range(256)) * 50 + b"\r\n--not-the-boundary\r\n"
    body = _body(_part("note", b"ignored"), _part("file", payload, "call.vtt"))
    reader = MultipartFile(
        _stream(_split(body, chunk_size)), CONTENT_TYPE, field="file", max_body=1 << 20
    )
    assert run_async(_read(reader)) == ("call.vtt", payload)


def test_multipart_filename_is_utf8() -> None:
    body = _body(_part("file", b"x", "Größe.txt"))
    reader = MultipartFile(_stream([body]), CONTENT_TYPE, field="file", max_body=1 << 20)
    assert run_async(_read(reader)) == ("Größe.txt", b"x")


def test_multipart_type_is_known_before_the_file_bytes_are_read() -> None:
    pulled: list[int] = []
    body = _split(_body(_part("file", b"x" * 10_000, "setup.exe")), 256)

    async def chunks() -> AsyncIterator[bytes]:
        for i, chunk in enumerate(body):
            pulled.append(i)
            yield chunk

    reader = MultipartFile(chunks(), CONTENT_TYPE, field="file", max_body=1 << 20)
    assert run_async(reader.filename()) == "setup.exe"
    assert len(pulled) < 3


@pytest.mark.parametrize(
    "body",
    [
        _body(_part("other", b"x", "a.txt")),  # wrong field
        _body(_part("file", b"x")),  # no filename: a plain field, not a file
        b"",
        b"garbage without boundaries",
    ],
)
def test_multipart_without_a_file_part_is_an_error(body: bytes) -> None:
    reader = MultipartFile(_stream([body]), CONTENT_TYPE, field="file", max_body=1 << 20)
    with pytest.raises(MultipartError):
        run_async(_read(reader))


@pytest.mark.parametrize(
    "content_type", [None, "application/json", "multipart/form-data", "text/plain; boundary=x"]
)
def test_multipart_needs_a_multipart_content_type(content_type: str | None) -> None:
    reader = MultipartFile(_stream([b""]), content_type, field="file", max_body=100)
    with pytest.raises(MultipartError):
        run_async(reader.filename())


def test_multipart_body_is_capped() -> None:
    body = _body(_part("junk", b"x" * 5000), _part("file", b"y", "a.txt"))
    reader = MultipartFile(_stream(_split(body, 512)), CONTENT_TYPE, field="file", max_body=2048)
    with pytest.raises(BodyTooLargeError):
        run_async(_read(reader))


def test_multipart_truncated_inside_the_file_is_an_error() -> None:
    body = _body(_part("file", b"z" * 100, "a.txt"))[:-60]
    reader = MultipartFile(_stream([body]), CONTENT_TYPE, field="file", max_body=1 << 20)
    with pytest.raises(MultipartError):
        run_async(_read(reader))


@pytest.mark.parametrize(
    "content_type",
    [
        f"Multipart/Form-Data; boundary={BOUNDARY}",
        f"MULTIPART/FORM-DATA; boundary={BOUNDARY}",
    ],
)
def test_multipart_media_type_ignores_case(content_type: str) -> None:
    body = _body(_part("file", b"x", "a.txt"))
    reader = MultipartFile(_stream([body]), content_type, field="file", max_body=1 << 20)
    assert run_async(_read(reader)) == ("a.txt", b"x")


def test_client_disconnect_mid_upload_is_a_multipart_error_and_stores_nothing(
    tmp_path: Path,
) -> None:
    body = _body(_part("file", b"q" * 4096, "a.txt"))

    async def disconnecting() -> AsyncIterator[bytes]:
        yield body[:1024]
        raise ClientDisconnect

    async def attempt() -> None:
        reader = MultipartFile(disconnecting(), CONTENT_TYPE, field="file", max_body=1 << 20)
        await reader.filename()
        await BlobStore(tmp_path).put_stream(reader.chunks(), max_bytes=1 << 20)

    with pytest.raises(MultipartError):
        run_async(attempt())
    assert _files_under(tmp_path) == []
