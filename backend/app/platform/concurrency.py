"""Optimistic concurrency (AD-11).

Every mutable row mixes in `RowVersioned`. SQLAlchemy uses `row_version` as its
`version_id_col`, so each UPDATE runs `... WHERE row_version = :old` and bumps it; a lost
race raises `StaleDataError`, which the error handlers map to 412 `row_version_mismatch`.

Writes carry the version the client read in `If-Match` (the row's `ETag`, e.g. `"3"`):
missing is 428 `if_match_required`, a different version is 412 `row_version_mismatch`.
"""

import re
from typing import Annotated, Any, Protocol

from fastapi import Depends, Header
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.platform.errors import IfMatchRequiredError, RowVersionMismatchError

_VERSION = r"0|[1-9]\d{0,17}"
_ETAG_RE = re.compile(rf'^"({_VERSION})"$|^({_VERSION})$')


class RowVersioned:
    """Declarative mixin: adds `row_version` and makes it the mapper's version counter."""

    row_version: Mapped[int] = mapped_column(Integer, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.row_version}  # type: ignore[attr-defined]


class HasRowVersion(Protocol):
    @property
    def row_version(self) -> int: ...


def etag(row_version: int) -> str:
    """Strong ETag for a row version, e.g. `"3"`."""
    return f'"{row_version}"'


def parse_if_match(header: str | None) -> int:
    """Return the row version an `If-Match` header names.

    Missing or blank raises `IfMatchRequiredError` (428). Anything that is not a single
    version ETag (lists, weak tags, leading zeros, junk) raises `RowVersionMismatchError`
    (412). `*` is rejected too, deliberately: RFC 9110 lets it match any current
    representation, but writes here must name the explicit row version they read."""
    if header is None or not header.strip():
        raise IfMatchRequiredError("This write needs an If-Match header with the row's ETag.")
    match = _ETAG_RE.match(header.strip())
    if match is None:
        raise RowVersionMismatchError('If-Match must be a single row-version ETag, e.g. "3".')
    return int(match.group(1) or match.group(2))


def check_row_version(expected: int, row: HasRowVersion) -> None:
    """Raise `RowVersionMismatchError` unless the loaded row is at the expected version."""
    if row.row_version != expected:
        raise RowVersionMismatchError(
            "The resource was changed by someone else. Reload it and try again."
        )


def _if_match_version(if_match: Annotated[str | None, Header()] = None) -> int:
    return parse_if_match(if_match)


IfMatch = Annotated[int, Depends(_if_match_version)]
"""Handler parameter type: the `If-Match` row version, or a 428/412 problem+json."""
