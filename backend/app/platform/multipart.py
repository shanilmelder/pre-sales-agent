"""Stream one file out of a `multipart/form-data` request body.

FastAPI's `UploadFile` parses the whole body (spooling it to a temp file) before the
handler runs, so a size limit could only be checked afterwards. `MultipartFile` instead
feeds the raw request stream through python-multipart's push parser and hands out the
named file part's bytes as they arrive. The caller can stop reading at any point (a type
it rejects, a size limit), and the rest of the body is never read.

Other parts are skipped without being kept. The whole body read is capped at `max_body`
bytes, so a client can't make the server read without end.
"""

from collections import deque
from collections.abc import AsyncIterable, AsyncIterator
from typing import TYPE_CHECKING

from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks


class MultipartError(Exception):
    """The body is not usable multipart/form-data, or has no file in the expected field."""


class BodyTooLargeError(Exception):
    """The body passed `max_body` bytes."""


_Event = tuple[str, bytes | dict[bytes, bytes]]


def boundary_of(content_type: str | None) -> bytes:
    """The boundary of a `multipart/form-data` Content-Type. Raises `MultipartError`."""
    media_type, options = parse_options_header(content_type)
    boundary = options.get(b"boundary", b"")
    if media_type.strip().lower() != b"multipart/form-data" or not boundary:
        raise MultipartError("expected multipart/form-data with a boundary")
    return boundary


class MultipartFile:
    """The first part named `field` that carries a filename, read lazily from `body`.

    Call `filename()` first (it reads up to that part's headers), then iterate `chunks()`
    once for its bytes."""

    def __init__(
        self,
        body: AsyncIterable[bytes],
        content_type: str | None,
        *,
        field: str,
        max_body: int,
    ) -> None:
        self._body = aiter(body)
        self._content_type = content_type
        self._field = field.encode()
        self._max_body = max_body
        self._read = 0
        self._events: deque[_Event] = deque()
        self._header_field = b""
        self._header_value = b""
        self._headers: dict[bytes, bytes] = {}
        self._filename: str | None = None
        self._body_done = False
        self._parser: MultipartParser | None = None

    def _get_parser(self) -> MultipartParser:
        """Created on first read, so a bad Content-Type surfaces only when the body is
        actually read (after the caller's authorization)."""
        if self._parser is None:
            callbacks: MultipartCallbacks = {
                "on_part_begin": self._on_part_begin,
                "on_header_field": self._on_header_field,
                "on_header_value": self._on_header_value,
                "on_header_end": self._on_header_end,
                "on_headers_finished": self._on_headers_finished,
                "on_part_data": self._on_part_data,
                "on_part_end": self._on_part_end,
            }
            self._parser = MultipartParser(boundary_of(self._content_type), callbacks)
        return self._parser

    # --- parser callbacks (synchronous; they only queue events) ---------------------------

    def _on_part_begin(self) -> None:
        self._headers = {}
        self._header_field = b""
        self._header_value = b""

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _on_header_end(self) -> None:
        self._headers[self._header_field.lower()] = self._header_value
        self._header_field = b""
        self._header_value = b""

    def _on_headers_finished(self) -> None:
        self._events.append(("headers", dict(self._headers)))

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        self._events.append(("data", bytes(data[start:end])))

    def _on_part_end(self) -> None:
        self._events.append(("end", b""))

    # --- reading ----------------------------------------------------------------------------

    async def _next_event(self) -> _Event | None:
        """The next parser event, reading more of the body as needed; None at its end."""
        parser = self._get_parser()
        while not self._events:
            if self._body_done:
                return None
            try:
                chunk = await anext(self._body)
            except ClientDisconnect as exc:
                raise MultipartError("the client disconnected during the upload") from exc
            except StopAsyncIteration:
                self._body_done = True
                try:
                    parser.finalize()
                except FormParserError as exc:
                    raise MultipartError("malformed multipart body") from exc
                continue
            self._read += len(chunk)
            if self._read > self._max_body:
                raise BodyTooLargeError
            try:
                parser.write(chunk)
            except FormParserError as exc:
                raise MultipartError("malformed multipart body") from exc
        return self._events.popleft()

    async def filename(self) -> str:
        """The file part's filename exactly as sent (decoded as UTF-8). Raises
        `MultipartError` if the body has no such part."""
        if self._filename is not None:
            return self._filename
        while True:
            event = await self._next_event()
            if event is None:
                raise MultipartError(f"no file in field {self._field.decode()!r}")
            kind, value = event
            if kind != "headers" or not isinstance(value, dict):
                continue
            _, options = parse_options_header(
                value.get(b"content-disposition", b"").decode("latin-1")
            )
            if options.get(b"name") != self._field or b"filename" not in options:
                continue
            try:
                self._filename = options[b"filename"].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MultipartError("the filename is not UTF-8") from exc
            return self._filename

    async def chunks(self) -> AsyncIterator[bytes]:
        """The file part's bytes, as they arrive. Ends at the end of the part."""
        if self._filename is None:
            await self.filename()
        while True:
            event = await self._next_event()
            if event is None:
                raise MultipartError("the body ended inside the file part")
            kind, value = event
            if kind == "end":
                return
            if kind == "data" and isinstance(value, bytes):
                yield value
