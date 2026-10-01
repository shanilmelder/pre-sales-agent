import asyncio
import os
import sys
from collections.abc import Coroutine, Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.main_api import create_app
from app.platform.config import Settings

# psycopg's async driver cannot use the Windows Proactor loop.
BACKEND_OPTIONS: dict[str, Any] = (
    {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
)
UNREACHABLE_DB = "postgresql+psycopg://psa:psa@127.0.0.1:1/psa"


def make_client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False, backend_options=BACKEND_OPTIONS)


@pytest.fixture
def db_down_client() -> Iterator[TestClient]:
    settings = Settings(database_url=UNREACHABLE_DB, version="9.9.9-test", db_connect_timeout_s=1)
    with make_client(create_app(settings)) as client:
        yield client


@pytest.fixture
def db_up_client() -> Iterator[TestClient]:
    url = os.environ.get("PSA_DATABASE_URL")
    if not url:
        pytest.skip("PSA_DATABASE_URL not set; the DB-up health test needs a running Postgres")
    settings = Settings(database_url=url, version="1.2.3-test")
    with make_client(create_app(settings)) as client:
        yield client


# --- DB-backed tests (skip without PSA_DATABASE_URL; expect `alembic upgrade head` and the
# least-privileged psa_app role, as CI runs them) -----------------------------------------


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a loop psycopg's async driver accepts (selector loop on Windows)."""
    return asyncio.run(coro, **BACKEND_OPTIONS)


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("PSA_DATABASE_URL")
    if not url:
        pytest.skip("PSA_DATABASE_URL not set; DB-backed tests need a migrated Postgres")
    return url


@pytest.fixture
def sync_engine(db_url: str) -> Iterator[Engine]:
    """Sync engine (psycopg 3) for arranging and asserting DB state around a request."""
    engine = sa.create_engine(db_url, connect_args={"options": "-c timezone=UTC"})
    yield engine
    engine.dispose()


@pytest.fixture
def db_app(db_url: str) -> FastAPI:
    """An app wired to the test database; tests add their own routes before starting it."""
    return create_app(Settings(database_url=db_url))
