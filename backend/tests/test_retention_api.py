"""Admin > Retention (Story 10.6): `GET /api/v1/admin/retention` against a real, migrated
Postgres as psa_app. Platform administrators only (`platform.retention.read`; others 403),
the due list uses the domain retention rule (due within 30 days, overdue included, open and
later ones left out), the recent purges come from `platform.purge.completed`, and no route
deletes anything.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.opportunities.domain.opportunity import add_years
from tests import test_opportunities as opportunity_tests
from tests.test_role_admin import _signed_in

client = opportunity_tests.client

URL = "/api/v1/admin/retention"
ADMIN = "platform_administrator"


def _today() -> date:
    return datetime.now(UTC).date()


def _opportunity(
    engine: Engine,
    *,
    outcome: str | None = None,
    recorded_at: datetime | None = None,
    contract_end: date | None = None,
) -> UUID:
    opportunity_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO opportunities_opportunities (id, owner_id, title, customer_name, "
                "products, industry, target_proposal_date, outcome, outcome_recorded_at, "
                "contract_end_date, row_version) VALUES (:id, :owner, 'Secret title', "
                "'Secret customer', ARRAY['P'], 'Retail', :target, :outcome, :recorded, "
                ":contract_end, 1)"
            ),
            {
                "id": opportunity_id,
                "owner": uuid4(),
                "target": _today(),
                "outcome": outcome,
                "recorded": recorded_at,
                "contract_end": contract_end,
            },
        )
    return opportunity_id


def _lost_until(engine: Engine, until: date) -> UUID:
    """A lost Opportunity whose retention date is `until` (recorded 3 years before)."""
    recorded = add_years(until, -3)
    return _opportunity(
        engine,
        outcome="lost",
        recorded_at=datetime(recorded.year, recorded.month, recorded.day, 9, tzinfo=UTC),
    )


def _forget(engine: Engine, *ids: UUID) -> None:
    """Reopen them, so no other test's purge run finds these Opportunities due."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE opportunities_opportunities SET outcome = NULL, "
                "outcome_recorded_at = NULL, contract_end_date = NULL WHERE id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )


def _get(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def test_an_administrator_sees_what_is_due_within_30_days(
    client: TestClient, sync_engine: Engine
) -> None:
    today = _today()
    overdue = _lost_until(sync_engine, today - timedelta(days=5))
    in_10 = _lost_until(sync_engine, today + timedelta(days=10))
    in_30 = _lost_until(sync_engine, today + timedelta(days=30))
    in_31 = _lost_until(sync_engine, today + timedelta(days=31))
    won = _opportunity(
        sync_engine,
        outcome="won",
        recorded_at=datetime.now(UTC),
        contract_end=add_years(today + timedelta(days=20), -7),
    )
    open_one = _opportunity(sync_engine)
    try:
        headers, _ = _signed_in(client, "Ada Admin", ADMIN)
        body = _get(client, headers)
        assert set(body) == {"due", "recent"}
        due = {item["opportunity_id"]: item for item in body["due"]}
        for listed in (overdue, in_10, in_30, won):
            assert str(listed) in due
        for absent in (in_31, open_one):
            assert str(absent) not in due
        assert due[str(in_10)] == {
            "opportunity_id": str(in_10),
            "outcome": "lost",
            "rule": "lost_3y",
            "retention_until": (today + timedelta(days=10)).isoformat(),
        }
        assert due[str(won)]["rule"] == "won_7y"
        assert due[str(won)]["retention_until"] == (today + timedelta(days=20)).isoformat()
        dates = [item["retention_until"] for item in body["due"]]
        assert dates == sorted(dates)
        # Ids, outcomes and dates only: never a title or customer name.
        assert "Secret" not in json.dumps(body)
    finally:
        _forget(sync_engine, overdue, in_10, in_30, in_31, won)


def test_recent_purges_come_from_the_purge_events(client: TestClient, sync_engine: Engine) -> None:
    purged = uuid4()
    payload = {
        "purged_opportunity_id": str(purged),
        "rule": "won_7y",
        "retention_until": "2026-01-31",
        "rows_by_module": {"intake": 12, "opportunities": 2, "platform": 30},
        "files_deleted": 3,
    }
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id, "
                "event_type, subject_type, subject_id, payload, occurred_at) VALUES "
                "(:id, NULL, 'system', 'platform.purge', 'platform.purge.completed', "
                "'opportunities.opportunity', :s, CAST(:p AS jsonb), now())"
            ),
            {"id": uuid4(), "s": purged, "p": json.dumps(payload)},
        )
    headers, _ = _signed_in(client, "Ada Admin", ADMIN)
    recent = _get(client, headers)["recent"]
    assert len(recent) <= 20
    first = recent[0]
    assert first["purged_opportunity_id"] == str(purged)
    assert first["rule"] == "won_7y"
    assert first["rows_by_module"] == {"intake": 12, "opportunities": 2, "platform": 30}
    assert first["files_deleted"] == 3
    assert set(first) == {
        "purged_opportunity_id",
        "rule",
        "rows_by_module",
        "files_deleted",
        "occurred_at",
    }


@pytest.mark.parametrize(
    "roles",
    [
        ("head_of_delivery",),
        ("presales_engineer",),
        ("delivery_manager",),
        ("sales_representative",),
        ("security_reviewer",),
    ],
)
def test_everyone_else_gets_403(client: TestClient, roles: tuple[str, ...]) -> None:
    headers, _ = _signed_in(client, "Someone Else", *roles)
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "forbidden"


def test_an_administrator_without_the_permission_gets_403(client: TestClient) -> None:
    headers, _ = _signed_in(client, "Ada Admin", ADMIN, permissions=["identity.user.list"])
    assert client.get(URL, headers=headers).status_code == 403


def test_no_route_deletes_anything(client: TestClient) -> None:
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    assert set(paths[URL]) == {"get"}
    for path, operations in paths.items():
        if "retention" in path or "purge" in path:
            assert set(operations) == {"get"}, path


def test_no_token_is_401(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
