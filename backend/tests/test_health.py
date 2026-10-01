"""I/O matrix for `GET /api/v1/health`, unknown routes and unhandled errors."""

from fastapi.testclient import TestClient

from app.main_api import create_app
from app.platform.config import Settings
from tests.conftest import UNREACHABLE_DB, make_client

PROBLEM_KEYS = {"type", "title", "status", "code", "detail", "instance"}


def assert_problem(body: dict[str, object], status: int, code: str) -> None:
    assert set(body) == PROBLEM_KEYS
    assert body["status"] == status
    assert body["code"] == code


def test_health_ok_when_db_reachable(db_up_client: TestClient) -> None:
    resp = db_up_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "1.2.3-test", "db": "ok"}


def test_health_503_problem_when_db_down(db_down_client: TestClient) -> None:
    resp = db_down_client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert_problem(body, 503, "db_unavailable")
    assert body["instance"] == "/api/v1/health"


def test_unknown_route_is_404_problem(db_down_client: TestClient) -> None:
    resp = db_down_client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), 404, "not_found")


def test_wrong_method_is_405_problem(db_down_client: TestClient) -> None:
    resp = db_down_client.post("/api/v1/health")
    assert resp.status_code == 405
    assert_problem(resp.json(), 405, "method_not_allowed")


def test_unhandled_error_is_500_problem_without_details() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DB))

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("secret customer text")

    with make_client(app) as client:
        resp = client.get("/api/v1/boom", headers={"X-Request-ID": "req-500"})
    assert resp.status_code == 500
    assert resp.headers["X-Request-ID"] == "req-500"
    assert resp.headers["content-type"] == "application/problem+json"
    assert_problem(resp.json(), 500, "internal_error")
    assert "secret" not in resp.text


def test_openapi_served_under_api_v1(db_down_client: TestClient) -> None:
    resp = db_down_client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert "/api/v1/health" in spec["paths"]
    assert spec["info"]["version"] == "9.9.9-test"


def test_request_id_is_echoed_or_generated(db_down_client: TestClient) -> None:
    resp = db_down_client.get("/api/v1/nope", headers={"X-Request-ID": "req-123"})
    assert resp.headers["X-Request-ID"] == "req-123"
    assert db_down_client.get("/api/v1/nope").headers["X-Request-ID"]
