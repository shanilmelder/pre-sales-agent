"""Every new platform error maps to problem+json with its stable code."""

import pytest
from fastapi import FastAPI
from sqlalchemy.orm.exc import StaleDataError

from app.main_api import create_app
from app.platform.config import Settings
from app.platform.errors import (
    _HTTP_CODES,
    ForbiddenError,
    IfMatchRequiredError,
    ProblemError,
    RowVersionMismatchError,
)
from tests.conftest import UNREACHABLE_DB, make_client
from tests.test_health import assert_problem


def _app_raising(exc: Exception) -> FastAPI:
    app = create_app(Settings(database_url=UNREACHABLE_DB))

    @app.post("/api/v1/raise")
    async def raise_it() -> None:
        raise exc

    return app


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ForbiddenError("nope"), 403, "forbidden"),
        (IfMatchRequiredError(), 428, "if_match_required"),
        (RowVersionMismatchError(), 412, "row_version_mismatch"),
        (StaleDataError("UPDATE matched 0 rows"), 412, "row_version_mismatch"),
    ],
)
def test_errors_map_to_problem_json(exc: Exception, status: int, code: str) -> None:
    with make_client(_app_raising(exc)) as client:
        resp = client.post("/api/v1/raise")
    assert resp.status_code == status
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert_problem(body, status, code)
    assert body["instance"] == "/api/v1/raise"


def test_stale_data_detail_does_not_leak_sql() -> None:
    with make_client(_app_raising(StaleDataError("UPDATE secret_table"))) as client:
        resp = client.post("/api/v1/raise")
    assert "secret_table" not in resp.text


def test_new_errors_are_problem_errors_and_428_has_a_code() -> None:
    for cls in (ForbiddenError, IfMatchRequiredError, RowVersionMismatchError):
        assert issubclass(cls, ProblemError)
    assert _HTTP_CODES[428] == "precondition_required"
