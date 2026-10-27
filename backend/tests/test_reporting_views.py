"""The reporting views (Story 10.3) against a real, migrated Postgres as psa_app: the row shape
of `reporting_estimate_vs_actual` for planned-line, Unplanned and multi-Integration-Type
Actuals, `reporting_failed_assumptions`, and the grants (SELECT only; INSERT, UPDATE and
DELETE fail).

`seed_opportunity` inserts a delivered (or open) Opportunity with its Estimate Version,
lines, Baseline and Actuals directly, fast enough for the Reports performance test; one test
records Actuals through the API instead, to tie the views to Story 10.1's writes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_opportunities as opportunity_tests
from tests.test_actuals_api import _save, _scene
from tests.test_gaps_detection import rows
from tests.test_intake_parse_job import _alembic

client = opportunity_tests.client

VIEW = "reporting_estimate_vs_actual"
FAILED_VIEW = "reporting_failed_assumptions"


def catalogue_entry(engine: Engine, name: str, kind: str = "integration_type") -> UUID:
    """A catalogue entry with two versions; the views name it by the newer one."""
    entry_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_catalogue_entries (id, kind, code, status, row_version) "
                "VALUES (:i, :k, :c, 'active', 2)"
            ),
            {"i": entry_id, "k": kind, "c": f"RP-{uuid4().hex[:8]}"},
        )
        for version, label in ((1, f"{name} (old)"), (2, name)):
            conn.execute(
                sa.text(
                    "INSERT INTO knowledge_catalogue_entry_versions "
                    "(entry_id, version, name, definition, changed_by) "
                    "VALUES (:i, :v, :n, 'A definition.', :u)"
                ),
                {"i": entry_id, "v": version, "n": label, "u": uuid4()},
            )
    return entry_id


@dataclass
class SeedLine:
    """A Baseline line (`estimate` h) and its current Actual (`actual` h; None: none), or,
    with `estimate=None`, Unplanned work."""

    estimate: str | None
    actual: str | None
    cause: str | None = None
    integration_types: Sequence[UUID] = ()
    work_package: UUID | None = None
    kind: str = "final"
    failed: Sequence[str] = ()
    section: str = "integration"


@dataclass
class Seeded:
    opp_id: UUID
    version_id: UUID
    line_ids: list[UUID | None]
    actual_ids: list[UUID | None]
    assumptions: dict[str, UUID] = field(default_factory=dict)


def seed_opportunity(
    engine: Engine,
    *,
    title: str,
    products: Sequence[str],
    lines: Sequence[SeedLine],
    owner_id: UUID | None = None,
    closed: bool = True,
    closed_at: str | None = None,
    version: int = 3,
    baseline: bool = True,
    assumptions: Sequence[tuple[str, str]] = (),
) -> Seeded:
    """An Opportunity with Estimate Version `version` (approved, the Baseline unless
    `baseline` is false), its lines and current Actuals, named Assumptions (`(name, kind)`),
    and (when `closed`) a Close delivery at `closed_at` (default now)."""
    opp_id, version_id, owner = uuid4(), uuid4(), owner_id or uuid4()
    seeded = Seeded(opp_id, version_id, [], [])
    with engine.begin() as conn:

        def run(sql: str, **params: Any) -> None:
            conn.execute(sa.text(sql), params)

        run(
            "INSERT INTO opportunities_opportunities (id, owner_id, title, customer_name, "
            "products, industry, target_proposal_date, row_version) VALUES (:i, :o, :t, "
            "'[CUSTOMER]', :p, 'Retail', CURRENT_DATE + 30, 1)",
            i=opp_id,
            o=owner,
            t=title,
            p=list(products),
        )
        run(
            "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
            "template_version, uncovered_count, dropped_count, row_version, submitted_at, "
            "created_by) VALUES (:i, :o, :v, 'approved', 'v1', 0, 0, 1, now(), :b)",
            i=version_id,
            o=opp_id,
            v=version,
            b=owner,
        )
        for position, (name, kind) in enumerate(assumptions, start=1):
            assumption_id = uuid4()
            run(
                "INSERT INTO estimates_assumptions (id, version_id, position, kind, wording, "
                "amount_hours, origin_ref, row_version) VALUES (:i, :v, :p, :k, 'Wording', "
                ":h, CAST(:o AS jsonb), 2)",
                i=assumption_id,
                v=version_id,
                p=position,
                k=kind,
                h=Decimal(4) if kind == "contingency" else None,
                o='{"kind": "gap"}',
            )
            seeded.assumptions[name] = assumption_id
        position = 0
        for line in lines:
            line_id = None
            if line.estimate is not None:
                position += 1
                line_id = uuid4()
                run(
                    "INSERT INTO estimates_estimate_lines (id, version_id, position, section, "
                    "title, effort_hours, role_mix, basis) VALUES (:i, :v, :p, :s, :t, :h, "
                    "CAST(:m AS jsonb), 'Basis')",
                    i=line_id,
                    v=version_id,
                    p=position,
                    s=line.section,
                    t=f"Line {position}",
                    h=line.estimate,
                    m='{"engineer": 100, "project_manager": 0, "qa": 0}',
                )
            seeded.line_ids.append(line_id)
            actual_id = None
            if line.actual is not None:
                actual_id = uuid4()
                refs = ",".join(
                    f'{{"assumption_id": "{seeded.assumptions[name]}", "version": 2}}'
                    for name in line.failed
                )
                run(
                    "INSERT INTO actuals_actuals (id, opportunity_id, estimate_version_id, "
                    "estimate_line_id, actual_group_id, version, is_current, "
                    "integration_type_ids, work_package_id, kind, effort_hours, variance_cause, "
                    "failed_assumptions, row_version, recorded_by) VALUES (:i, :o, :v, :l, :g, "
                    "1, true, :its, :wp, :k, :h, :c, CAST(:f AS jsonb), 1, :b)",
                    i=actual_id,
                    o=opp_id,
                    v=version_id,
                    l=line_id,
                    g=uuid4(),
                    its=list(line.integration_types),
                    wp=line.work_package,
                    k=line.kind,
                    h=line.actual,
                    c=line.cause,
                    f=f"[{refs}]",
                    b=owner,
                )
            seeded.actual_ids.append(actual_id)
        if baseline:
            run(
                "INSERT INTO estimates_baselines (id, opportunity_id, estimate_version_id, "
                "set_at, set_by) VALUES (:i, :o, :v, clock_timestamp(), :b)",
                i=uuid4(),
                o=opp_id,
                v=version_id,
                b=owner,
            )
        if closed:
            run(
                "INSERT INTO actuals_deliveries (id, opportunity_id, estimate_version_id, "
                "closed_by, closed_at) VALUES (:i, :o, :v, :b, "
                "COALESCE(CAST(:at AS timestamptz), now()))",
                i=uuid4(),
                o=opp_id,
                v=version_id,
                b=owner,
                at=closed_at,
            )
    return seeded


def view_rows(engine: Engine, opp_id: UUID | str) -> list[dict[str, Any]]:
    return rows(
        engine,
        f"SELECT * FROM {VIEW} WHERE opportunity_id = :o ORDER BY line_label NULLS LAST",
        o=opp_id,
    )


# --- row shape ------------------------------------------------------------------------------


def test_row_shape_planned_unplanned_and_multi_tag(sync_engine: Engine) -> None:
    ewm = catalogue_entry(sync_engine, "SAP EWM")
    sso = catalogue_entry(sync_engine, "SSO and identity")
    wp = catalogue_entry(sync_engine, "Go-live support", kind="work_package")
    s = seed_opportunity(
        sync_engine,
        title="Lakeside returns",
        products=["AutoStore", "Pick station"],
        assumptions=[("a1", "condition"), ("a2", "contingency")],
        lines=[
            SeedLine("36.0", "41.0", "estimation_error", [ewm], failed=["a1", "a2"]),
            SeedLine("20.0", "18.0", "integration_complexity", [ewm, sso]),
            SeedLine("10.0", None),  # not recorded: no row
            SeedLine(None, "12.0", "scope_change", work_package=wp),
        ],
    )
    got = view_rows(sync_engine, s.opp_id)
    assert len(got) == 3
    first, second, unplanned = got

    assert first["actual_id"] == s.actual_ids[0]
    assert (first["opportunity_title"], first["products"]) == (
        "Lakeside returns",
        ["AutoStore", "Pick station"],
    )
    assert first["closed_at"] is not None
    assert (first["estimate_version_id"], first["estimate_version"]) == (s.version_id, 3)
    assert first["is_baseline"] is True
    assert (first["line_id"], first["line_label"]) == (s.line_ids[0], "L1")
    assert (first["estimate_hours"], first["actual_hours"]) == (Decimal("36.0"), Decimal("41.0"))
    assert (first["kind"], first["variance_cause"]) == ("final", "estimation_error")
    assert first["integration_type_ids"] == [ewm]
    assert first["integration_type_names"] == ["SAP EWM"]  # the newest catalogue version
    assert (first["work_package_id"], first["work_package_name"]) == (None, None)
    assert first["failed_count"] == 2

    # Multi-tag: both Integration Types, names in the same order.
    assert second["line_label"] == "L2"
    assert second["integration_type_ids"] == [ewm, sso]
    assert second["integration_type_names"] == ["SAP EWM", "SSO and identity"]

    # Unplanned work: no line, an estimate of 0, the Work Package and its name.
    assert (unplanned["line_id"], unplanned["line_label"]) == (None, None)
    assert unplanned["estimate_hours"] == Decimal("0.0")
    assert unplanned["actual_hours"] == Decimal("12.0")
    assert unplanned["integration_type_ids"] == []
    assert (unplanned["work_package_id"], unplanned["work_package_name"]) == (
        wp,
        "Go-live support",
    )
    assert unplanned["failed_count"] == 0

    failed = rows(
        sync_engine,
        f"SELECT * FROM {FAILED_VIEW} WHERE opportunity_id = :o ORDER BY assumption_kind",
        o=s.opp_id,
    )
    assert [
        (f["actual_id"], f["assumption_id"], f["assumption_version"], f["assumption_kind"])
        for f in failed
    ] == [
        (s.actual_ids[0], s.assumptions["a1"], 2, "condition"),
        (s.actual_ids[0], s.assumptions["a2"], 2, "contingency"),
    ]


def test_labels_follow_the_grid_order_and_flags(sync_engine: Engine) -> None:
    """ "L{n}" counts in template section order, then position (as the Actuals tab); an open
    delivery has no `closed_at`; only the latest Baseline's version is `is_baseline`."""
    s = seed_opportunity(
        sync_engine,
        title="Grid order",
        products=["AutoStore"],
        closed=False,
        lines=[
            SeedLine("5.0", "5.0", section="data"),  # position 1, but the data section
            SeedLine("6.0", "6.0", section="functional"),  # position 2: first in the grid
        ],
    )
    by_line = {r["line_id"]: r for r in view_rows(sync_engine, s.opp_id)}
    assert by_line[s.line_ids[0]]["line_label"] == "L2"
    assert by_line[s.line_ids[1]]["line_label"] == "L1"
    assert all(r["closed_at"] is None for r in by_line.values())
    assert all(r["is_baseline"] for r in by_line.values())

    newer = uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
                "template_version, uncovered_count, dropped_count, row_version, submitted_at) "
                "VALUES (:i, :o, 5, 'approved', 'v1', 0, 0, 1, now())"
            ),
            {"i": newer, "o": s.opp_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_baselines (id, opportunity_id, estimate_version_id, "
                "set_at, set_by) VALUES (:i, :o, :v, clock_timestamp(), :b)"
            ),
            {"i": uuid4(), "o": s.opp_id, "v": newer, "b": uuid4()},
        )
    got = view_rows(sync_engine, s.opp_id)
    assert {(r["estimate_version"], r["is_baseline"]) for r in got} == {(3, False)}


def test_only_current_actuals_and_milestones_keep_their_kind(sync_engine: Engine) -> None:
    s = seed_opportunity(
        sync_engine,
        title="Milestones",
        products=["AutoStore"],
        lines=[SeedLine("10.0", "4.0", kind="milestone"), SeedLine("8.0", "8.0")],
    )
    with sync_engine.begin() as conn:  # a correction leaves the old version not current
        conn.execute(
            sa.text("UPDATE actuals_actuals SET is_current = false WHERE id = :i"),
            {"i": s.actual_ids[1]},
        )
    (row,) = view_rows(sync_engine, s.opp_id)
    assert (row["actual_id"], row["kind"]) == (s.actual_ids[0], "milestone")


def test_actuals_recorded_through_the_api_appear(client: TestClient, sync_engine: Engine) -> None:
    scene = _scene(client, sync_engine)
    item = {
        "effort_hours": 8,
        "variance_cause": "scope_change",
        "integration_type_id": str(scene.entry),
    }
    planned = {"line_id": scene.l1, "effort_hours": 41, "variance_cause": "estimation_error"}
    resp = _save(client, scene.dm, scene.opp_id, [planned, item])
    assert resp.status_code == 200, resp.text
    got = view_rows(sync_engine, scene.opp_id)
    assert [(r["line_label"], r["estimate_hours"], r["actual_hours"]) for r in got] == [
        ("L1", Decimal("36.0"), Decimal("41.0")),
        (None, Decimal("0.0"), Decimal("8.0")),
    ]
    assert all(r["integration_type_ids"] == [scene.entry] for r in got)
    assert all(r["integration_type_names"] == ["ERP integration"] for r in got)
    assert all(r["closed_at"] is None and r["is_baseline"] for r in got)


# --- grants ---------------------------------------------------------------------------------


@pytest.mark.parametrize("view", [VIEW, FAILED_VIEW])
def test_psa_app_may_only_select(sync_engine: Engine, view: str) -> None:
    """The default privileges grant INSERT, UPDATE and DELETE on every new relation; the
    migration revokes them, so psa_app holds SELECT only, and every write fails."""
    (privileges,) = rows(
        sync_engine,
        "SELECT has_table_privilege(current_user, :v, 'SELECT') AS s, "
        "has_table_privilege(current_user, :v, 'INSERT') AS i, "
        "has_table_privilege(current_user, :v, 'UPDATE') AS u, "
        "has_table_privilege(current_user, :v, 'DELETE') AS d, "
        "has_table_privilege(current_user, :v, 'TRUNCATE') AS t",
        v=view,
    )
    assert privileges == {"s": True, "i": False, "u": False, "d": False, "t": False}
    for statement in (
        f"INSERT INTO {view} (actual_id) VALUES (gen_random_uuid())",
        f"UPDATE {view} SET opportunity_id = opportunity_id",
        f"DELETE FROM {view}",
    ):
        with pytest.raises(sa.exc.DBAPIError):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement))


def test_the_migration_goes_down_and_up(sync_engine: Engine) -> None:
    _alembic("downgrade", "0053_actuals_actuals")
    try:
        assert (
            rows(
                sync_engine,
                "SELECT table_name FROM information_schema.views "
                "WHERE table_name LIKE 'reporting_%'",
            )
            == []
        )
    finally:
        _alembic("upgrade", "head")
    names = rows(
        sync_engine,
        "SELECT table_name FROM information_schema.views WHERE table_name LIKE 'reporting_%' "
        "ORDER BY table_name",
    )
    assert [n["table_name"] for n in names] == [VIEW, FAILED_VIEW]
