"""RFC 9457 problem+json errors, mapped in one place (AD-16).

Body: `{type, title, status, code, detail, instance}`. `code` is stable and machine-readable.
"""

from collections.abc import Mapping
from http import HTTPStatus
from types import MappingProxyType

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.platform.logging import get_logger

PROBLEM_JSON = "application/problem+json"
_log = get_logger(__name__)

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    412: "precondition_failed",
    415: "unsupported_media_type",
    422: "validation_error",
    428: "precondition_required",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class Problem(BaseModel):
    """problem+json body, published in OpenAPI so the generated client is typed."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None


class ProblemError(Exception):
    """Base for typed errors that map to a problem+json response."""

    status: int = 500
    code: str = "internal_error"
    title: str | None = None
    headers: Mapping[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class DbUnavailableError(ProblemError):
    status = 503
    code = "db_unavailable"
    title = "Database unavailable"


class AuthenticationError(ProblemError):
    """Base for 401s: the request carries no valid bearer token. Always sends
    `WWW-Authenticate: Bearer` (RFC 6750). Details never echo the token or its claims."""

    status = 401
    code = "unauthenticated"
    title = "Unauthenticated"
    headers: Mapping[str, str] | None = MappingProxyType(
        {"WWW-Authenticate": 'Bearer error="invalid_token"'}
    )


class TokenMissingError(AuthenticationError):
    code = "token_missing"
    headers = MappingProxyType({"WWW-Authenticate": "Bearer"})


class TokenExpiredError(AuthenticationError):
    code = "token_expired"


class TokenInvalidError(AuthenticationError):
    code = "token_invalid"


class AuthUnavailableError(ProblemError):
    """The identity provider's signing keys (JWKS) could not be fetched."""

    status = 503
    code = "auth_unavailable"
    title = "Authentication unavailable"


class ForbiddenError(ProblemError):
    """`identity.authorize` denied the action (AD-15)."""

    status = 403
    code = "forbidden"
    title = "Forbidden"


class IfMatchRequiredError(ProblemError):
    """A write arrived without an `If-Match` header (AD-11)."""

    status = 428
    code = "if_match_required"
    title = "If-Match required"


class RowVersionMismatchError(ProblemError):
    """The row changed since the client read it (AD-11)."""

    status = 412
    code = "row_version_mismatch"
    title = "Row version mismatch"


def problem_response(
    request: Request,
    status: int,
    code: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        type=f"https://errors.pre-sales-agent/{code}",
        title=title or HTTPStatus(status).phrase,
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
    )
    return JSONResponse(
        body.model_dump(), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


async def _problem_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(
        request, exc.status, exc.code, title=exc.title, detail=exc.detail, headers=exc.headers
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    detail: str | None = exc.detail if isinstance(exc.detail, str) else None
    if detail == HTTPStatus(exc.status_code).phrase:
        detail = None
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(request, exc.status_code, code, detail=detail, headers=headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
    detail = "Invalid fields: " + ", ".join(fields)
    return problem_response(request, 422, "validation_error", detail=detail)


async def _stale_data_error(request: Request, exc: Exception) -> JSONResponse:
    """A concurrent update won the race: SQLAlchemy's versioned UPDATE matched no row."""
    assert isinstance(exc, StaleDataError)
    _log.info("db.stale_data", extra={"path": request.url.path})
    return problem_response(
        request,
        RowVersionMismatchError.status,
        RowVersionMismatchError.code,
        title=RowVersionMismatchError.title,
        detail="The resource was changed by someone else. Reload it and try again.",
    )


async def unhandled_error_response(request: Request, exc: Exception) -> JSONResponse:
    _log.error("request.unhandled_error", exc_info=exc, extra={"path": request.url.path})
    return problem_response(request, 500, "internal_error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StaleDataError, _stale_data_error)
    app.add_exception_handler(Exception, unhandled_error_response)
