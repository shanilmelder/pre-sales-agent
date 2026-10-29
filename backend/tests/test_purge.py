"""The controlled retention purge (Story 10.6) against a real, migrated Postgres.

The purge runs as the `psa_purge` role: the owner URL (`PSA_MIGRATIONS_DATABASE_URL`) with
`SET ROLE psa_purge` at connect, so exactly that role's grants apply. Rows are arranged as
`psa_app` with a catalogue-driven seeder that writes one row into every per-Opportunity table
(module tables, their children, the platform's own and the LangGraph checkpoint tables), so a
table added later is seeded and checked too.

Covers the I/O matrix (due lost, not yet due, open, won in the future, shared and sole blobs,
one failing Opportunity, rerun, not configured, the dead-job alert), the schema check that
every table with an `opportunity_id` column is covered by a registered step, the event
payload (ids and counts only) and the roles' privileges.
"""

import importlib.util
import json
import os
import re
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app import main_worker
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.purge import job as purge_job
from app.platform.purge import registry
from app.platform.purge.registry import PurgeStep, RetentionDue, StepResult
from app.platform.storage import BlobStore
from tests.conftest import run_async

main_worker.load_job_types()  # registers every module's purge step and the selector

TODAY = date(2026, 10, 28)
PURGE_EVENT = "platform.purge.completed"
CHECKPOINT_SCHEMA = "orchestration_checkpoints"
SHARED_TABLES = (
    "identity_users",
    "knowledge_sources",
    "knowledge_source_versions",
    "knowledge_catalogue_entries",
    "knowledge_chunks",
    "registry_agents",
    "registry_agent_config_versions",
    "platform_schedules",
)
"""Shared data the purge never touches (and `psa_purge` cannot even read or delete)."""
SHA_COLUMNS = {
    ("intake_source_versions", "file_sha256"),
    ("intake_source_parses", "text_sha256"),
    ("actuals_imports", "file_sha256"),
    ("knowledge_research_snapshots", "content_sha256"),
    ("knowledge_research_snapshots", "text_sha256"),
}
"""The columns that hold a counted file reference (`platform_files`)."""
MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261028_0058_purge_role.py"
)


# --- the purge role ---------------------------------------------------------------------------


@pytest.fixture
def purge_url() -> str:
    owner = os.environ.get("PSA_MIGRATIONS_DATABASE_URL")
    if not owner or not os.environ.get("PSA_DATABASE_URL"):
        pytest.skip("the purge tests need PSA_DATABASE_URL and PSA_MIGRATIONS_DATABASE_URL")
    return owner


def purge_engine(owner_url: str) -> AsyncEngine:
    """The owner's connection acting as `psa_purge` (only its grants apply)."""
    return create_async_engine(
        owner_url, connect_args={"options": "-c role=psa_purge -c timezone=UTC"}
    )


def sync_purge_engine(owner_url: str) -> Engine:
    return sa.create_engine(
        make_url(owner_url), connect_args={"options": "-c role=psa_purge -c timezone=UTC"}
    )


# --- the catalogue-driven seeder ------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str
    nullable: bool
    has_default: bool


@dataclass
class Catalogue:
    columns: dict[str, list[Column]]
    pks: dict[str, list[str]]
    fks: dict[str, list[tuple[list[str], str, list[str], bool]]]
    """table -> [(columns, referenced table, referenced columns, all columns nullable)]"""
    enums: dict[tuple[str, str], str]
    order: list[str]


_ANY = re.compile(r"\(\(\"?(\w+)\"? = ANY \(ARRAY\['([^']+)'")
_ONE = re.compile(r"\(\(\"?(\w+)\"? = '([^']+)'::text\)\)")


def _qualified(table: str) -> str:
    return table if "." in table else f"public.{table}"


def purge_tables(engine: Engine) -> list[str]:
    """Every table the purge empties, checkpoint tables (schema-qualified) included."""
    with engine.connect() as conn:
        checkpoints = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = :s AND column_name = 'thread_id'"
            ),
            {"s": CHECKPOINT_SCHEMA},
        ).scalars()
        names = [f"{CHECKPOINT_SCHEMA}.{t}" for t in checkpoints]
    return sorted(registry.covered_tables() | purge_job.PLATFORM_TABLES) + sorted(names)


def load_catalogue(engine: Engine, tables: list[str]) -> Catalogue:
    regclasses = [_qualified(t) for t in tables]
    with engine.connect() as conn:
        cols = conn.execute(
            sa.text(
                "SELECT c.relname AS tbl, n.nspname AS schema, a.attname AS col, "
                "format_type(a.atttypid, a.atttypmod) AS typ, NOT a.attnotnull AS nullable, "
                "a.atthasdef OR a.attidentity <> '' AS has_default "
                "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE a.attnum > 0 AND NOT a.attisdropped "
                "AND (n.nspname || '.' || c.relname) = ANY(:t) ORDER BY a.attnum"
            ),
            {"t": regclasses},
        ).all()
        constraints = conn.execute(
            sa.text(
                "SELECT c.contype, c.conrelid::regclass::text AS tbl, "
                "c.confrelid::regclass::text AS ref, pg_get_constraintdef(c.oid) AS definition, "
                "ARRAY(SELECT attname FROM unnest(c.conkey) WITH ORDINALITY k(n, i) "
                "  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n "
                "  ORDER BY k.i) AS cols, "
                "ARRAY(SELECT attname FROM unnest(c.confkey) WITH ORDINALITY k(n, i) "
                "  JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n "
                "  ORDER BY k.i) AS refcols "
                "FROM pg_constraint c WHERE c.contype IN ('p', 'f', 'c') "
                "AND c.conrelid = ANY(CAST(:t AS regclass[]))"
            ),
            {"t": regclasses},
        ).all()

    def name(schema: str, table: str) -> str:
        return table if schema == "public" else f"{schema}.{table}"

    columns: dict[str, list[Column]] = {t: [] for t in tables}
    for row in cols:
        columns[name(row.schema, row.tbl)].append(
            Column(row.col, row.typ, row.nullable, row.has_default)
        )
    nullable = {(t, c.name): c.nullable for t, cs in columns.items() for c in cs}
    pks: dict[str, list[str]] = {}
    fks: dict[str, list[tuple[list[str], str, list[str], bool]]] = {t: [] for t in tables}
    enums: dict[tuple[str, str], str] = {}
    for row in constraints:
        table = row.tbl
        if row.contype == "p":
            pks[table] = list(row.cols)
        elif row.contype == "f":
            fks[table].append(
                (
                    list(row.cols),
                    row.ref,
                    list(row.refcols),
                    all(nullable[(table, c)] for c in row.cols),
                )
            )
        else:
            body = row.definition.removeprefix("CHECK ")
            for pattern in (_ANY, _ONE):
                match = pattern.match(body)
                if match:
                    enums.setdefault((table, match.group(1)), match.group(2))
    order: list[str] = []
    pending = list(tables)
    while pending:
        progressed = False
        for table in list(pending):
            parents = {
                ref
                for _, ref, _, optional in fks[table]
                if not optional and ref != table and ref in tables
            }
            if parents <= set(order):
                order.append(table)
                pending.remove(table)
                progressed = True
        assert progressed, f"foreign key cycle among {pending}"
    return Catalogue(columns, pks, fks, enums, order)


@dataclass
class Seeded:
    opportunity_id: UUID
    run_id: UUID
    title: str
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _value(column: Column) -> Any:
    typ = column.sql_type
    if typ == "uuid":
        return uuid4()
    if typ in ("text", "character varying") or typ.startswith("character varying"):
        return f"t{secrets.token_hex(6)}"
    if typ in ("integer", "bigint", "smallint"):
        return 1
    if typ.startswith("numeric") or typ in ("real", "double precision"):
        return 1
    if typ == "boolean":
        return False
    if typ == "date":
        return TODAY
    if typ.startswith("timestamp"):
        return datetime.now(UTC)
    if typ in ("jsonb", "json"):
        return "{}"
    if typ.endswith("[]"):
        return []
    if typ == "bytea":
        return b"x"
    raise AssertionError(f"no seed value for type {typ}")


def seed_opportunity(
    engine: Engine,
    catalogue: Catalogue,
    *,
    outcome: str | None = None,
    recorded_at: datetime | None = None,
    contract_end: date | None = None,
    shas: dict[tuple[str, str], str] | None = None,
    config_version_id: UUID,
    only: tuple[str, ...] | None = None,
) -> Seeded:
    """One row in every purge table (or only those in `only`), tied to a new Opportunity."""
    opportunity_id, run_id = uuid4(), uuid4()
    title = f"Title {secrets.token_hex(4)}"
    seeded = Seeded(opportunity_id, run_id, title)
    overrides: dict[tuple[str, str], Any] = {
        ("opportunities_opportunities", "id"): opportunity_id,
        ("opportunities_opportunities", "title"): title,
        ("opportunities_opportunities", "customer_name"): f"Customer {secrets.token_hex(4)}",
        ("opportunities_opportunities", "outcome"): outcome,
        ("opportunities_opportunities", "outcome_recorded_at"): recorded_at,
        ("opportunities_opportunities", "contract_end_date"): contract_end,
        ("workflows_runs", "id"): run_id,
        ("intake_source_passages", "start"): 0,
        ("intake_source_passages", "end"): 2,
        ("conflicts_positions", "source"): "estimate",
        ("conflicts_positions", "estimate_version_id"): uuid4(),
        ("conflicts_positions", "estimate_version"): 1,
        ("actuals_actuals", "variance_cause"): "scope_change",
        ("reviews_review_replies", "evidence"): "[]",
        ("knowledge_research_snapshots", "http_status"): 200,
        ("assessments_assessments", "config_version_id"): config_version_id,
        ("workflows_tasks", "config_version_id"): config_version_id,
    }
    for key, sha in (shas or {}).items():
        overrides[key] = sha
    if ("intake_source_parses", "text_sha256") in overrides:
        overrides[("intake_source_parses", "status")] = "parsed"
    with engine.begin() as conn:
        for table in catalogue.order:
            if only is not None and table not in only:
                continue
            parent_values: dict[str, Any] = {}
            for cols, ref, refcols, optional in catalogue.fks[table]:
                if optional or ref == table or ref not in seeded.rows:
                    continue
                parent = seeded.rows[ref][0]
                parent_values.update(dict(zip(cols, (parent[c] for c in refcols), strict=True)))
            row: dict[str, Any] = {}
            for column in catalogue.columns[table]:
                key = (table, column.name)
                if key in overrides:
                    row[column.name] = overrides[key]
                elif column.name in parent_values:
                    row[column.name] = parent_values[column.name]
                elif column.name == "opportunity_id":
                    row[column.name] = opportunity_id
                elif column.name in ("run_id", "workflow_run_id"):
                    row[column.name] = run_id
                elif column.name == "thread_id":
                    row[column.name] = str(run_id)
                elif column.nullable or column.has_default:
                    continue
                elif key in catalogue.enums:
                    row[column.name] = catalogue.enums[key]
                else:
                    row[column.name] = _value(column)
            types = {c.name: c.sql_type for c in catalogue.columns[table]}
            names = ", ".join(f'"{n}"' for n in row)
            values = ", ".join(f"CAST(:p{i} AS {types[n]})" for i, n in enumerate(row))
            conn.execute(
                sa.text(f"INSERT INTO {_qualified(table)} ({names}) VALUES ({values})"),
                {f"p{i}": v for i, v in enumerate(row.values())},
            )
            seeded.rows[table] = [row]
    return seeded


def remaining(engine: Engine, catalogue: Catalogue, seeded: Seeded) -> dict[str, int]:
    """Per table, how many of the rows seeded for this Opportunity are still there."""
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table, rows in seeded.rows.items():
            keys = [k for k in catalogue.pks.get(table, []) if k in rows[0]] or [
                c.name
                for c in catalogue.columns[table]
                if c.name in rows[0]
                and not c.sql_type.endswith("[]")
                and c.sql_type not in ("jsonb", "json", "bytea")
            ]
            where = " AND ".join(f'"{k}" = :{k}' for k in keys)
            counts[table] = conn.execute(
                sa.text(f"SELECT count(*) FROM {_qualified(table)} WHERE {where}"),
                {k: rows[0][k] for k in keys},
            ).scalar_one()
    return counts


# --- fixtures ---------------------------------------------------------------------------------


@dataclass
class World:
    catalogue: Catalogue
    config_version_id: UUID
    store: BlobStore


@pytest.fixture
def world(sync_engine: Engine, db_url: str, purge_url: str, tmp_path: Path) -> Iterator[World]:
    from app.orchestration.checkpointer import open_checkpointer

    async def setup() -> None:
        async with open_checkpointer(db_url, setup=True):
            pass

    run_async(setup())  # the checkpointer creates its tables (as psa_app), as the worker does
    with sync_engine.connect() as conn:
        config_version_id = conn.execute(
            sa.text("SELECT id FROM registry_agent_config_versions LIMIT 1")
        ).scalar_one()
    catalogue = load_catalogue(sync_engine, purge_tables(sync_engine))
    yield World(catalogue, config_version_id, BlobStore(tmp_path))


def _sha() -> str:
    return secrets.token_hex(32)


def _file(engine: Engine, store: BlobStore, sha: str, refs: int, *, on_disk: bool = True) -> Path:
    path = store.path_for(sha)
    if on_disk:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"blob")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_files (sha256, size_bytes, ref_count) VALUES (:s, 4, :r)"
            ),
            {"s": sha, "r": refs},
        )
    return path


def _ref_count(engine: Engine, sha: str) -> int:
    with engine.connect() as conn:
        count: int = conn.execute(
            sa.text("SELECT ref_count FROM platform_files WHERE sha256 = :s"), {"s": sha}
        ).scalar_one()
    return count


def _purge_events(engine: Engine, opportunity_id: UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT * FROM platform_trace_events WHERE event_type = :e AND subject_id = :s"
            ),
            {"e": PURGE_EVENT, "s": opportunity_id},
        ).mappings()
        return [dict(row) for row in rows]


def _run(purge_url: str, store: BlobStore, today: date = TODAY) -> purge_job.PurgeReport:
    async def scenario() -> purge_job.PurgeReport:
        engine = purge_engine(purge_url)
        try:
            return await purge_job.run_purge(engine, store, today=today)
        finally:
            await engine.dispose()

    return run_async(scenario())


def _lost(world: World, engine: Engine, recorded: datetime, **kw: Any) -> Seeded:
    return seed_opportunity(
        engine,
        world.catalogue,
        outcome="lost",
        recorded_at=recorded,
        config_version_id=world.config_version_id,
        **kw,
    )


def _open(world: World, engine: Engine, **kw: Any) -> Seeded:
    return seed_opportunity(
        engine, world.catalogue, config_version_id=world.config_version_id, **kw
    )


# --- the schema check -------------------------------------------------------------------------


def test_every_table_with_an_opportunity_id_is_covered_by_a_registered_step(
    sync_engine: Engine,
) -> None:
    with sync_engine.connect() as conn:
        with_column = set(
            conn.execute(
                sa.text(
                    "SELECT c.table_name FROM information_schema.columns c "
                    "JOIN information_schema.tables t USING (table_schema, table_name) "
                    "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
                    "AND c.column_name = 'opportunity_id'"
                )
            ).scalars()
        )
        existing = set(
            conn.execute(
                sa.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ).scalars()
        )
    covered = registry.covered_tables() | purge_job.PLATFORM_TABLES
    assert with_column, "the check should find the per-Opportunity tables"
    assert sorted(with_column - covered) == [], "add these tables to a module's purge step"
    assert sorted(covered - existing) == [], "a step names a table that doesn't exist"
    assert "opportunities_opportunities" in covered


def test_the_migration_grants_exactly_the_covered_tables(sync_engine: Engine) -> None:
    spec = importlib.util.spec_from_file_location("migration_0058", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    covered = registry.covered_tables() | purge_job.PLATFORM_TABLES
    assert set(module.TABLES) == covered
    with sync_engine.connect() as conn:
        for table in sorted(covered):
            for privilege in ("SELECT", "DELETE"):
                allowed = conn.execute(
                    sa.text("SELECT has_table_privilege('psa_purge', :t, :p)"),
                    {"t": table, "p": privilege},
                ).scalar_one()
                assert allowed, (table, privilege)


def test_steps_run_in_dependency_order() -> None:
    modules = [step.module for step in registry.steps()]
    assert modules[-1] == "opportunities"
    for module in ("actuals", "estimates", "intake", "gaps", "workflows", "reviews"):
        assert module in modules


# --- privileges -------------------------------------------------------------------------------


def test_the_app_role_still_cannot_delete_or_update_the_trace(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        for privilege in ("DELETE", "UPDATE", "TRUNCATE"):
            assert not conn.execute(
                sa.text("SELECT has_table_privilege('platform_trace_events', :p)"),
                {"p": privilege},
            ).scalar_one()


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM identity_users WHERE false",
        "SELECT 1 FROM identity_users LIMIT 1",
        "DELETE FROM knowledge_sources WHERE false",
        "SELECT 1 FROM knowledge_source_versions LIMIT 1",
        "DELETE FROM knowledge_catalogue_entries WHERE false",
        "DELETE FROM registry_agents WHERE false",
        "DELETE FROM platform_schedules WHERE false",
        "DELETE FROM platform_files WHERE false",
        "UPDATE platform_trace_events SET actor_id = actor_id WHERE false",
        "CREATE TABLE public.psa_purge_must_not_create (id int)",
    ],
)
def test_the_purge_role_cannot_touch_shared_data(purge_url: str, statement: str) -> None:
    engine = sync_purge_engine(purge_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT current_user")).scalar_one() == "psa_purge"
            with pytest.raises(sa.exc.ProgrammingError) as info:
                conn.execute(sa.text(statement))
            assert isinstance(info.value.orig, psycopg.errors.InsufficientPrivilege)
            conn.rollback()
    finally:
        engine.dispose()


# --- the I/O matrix ---------------------------------------------------------------------------


def test_a_due_lost_opportunity_is_purged_entirely_and_others_are_untouched(
    sync_engine: Engine, purge_url: str, world: World
) -> None:
    shared, sole_upload, sole_text, missing = _sha(), _sha(), _sha(), _sha()
    page, page_text = _sha(), _sha()
    shared_path = _file(sync_engine, world.store, shared, 2)
    sole_path = _file(sync_engine, world.store, sole_upload, 1)
    text_path = _file(sync_engine, world.store, sole_text, 1)
    _file(sync_engine, world.store, missing, 1, on_disk=False)  # its blob is already gone
    page_path = _file(sync_engine, world.store, page, 1)
    page_text_path = _file(sync_engine, world.store, page_text, 1)
    with sync_engine.connect() as conn:
        shared_before = {
            t: conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one()
            for t in SHARED_TABLES
        }

    a = _lost(
        world,
        sync_engine,
        datetime(2023, 1, 1, 9, tzinfo=UTC),
        shas={
            ("intake_source_versions", "file_sha256"): sole_upload,
            ("intake_source_parses", "text_sha256"): sole_text,
            ("actuals_imports", "file_sha256"): missing,
            ("knowledge_research_snapshots", "content_sha256"): page,
            ("knowledge_research_snapshots", "text_sha256"): page_text,
        },
    )
    # The shared blob: held by open B's Source version and a second version of A's Source.
    b = _open(world, sync_engine, shas={("intake_source_versions", "file_sha256"): shared})
    columns = [c.name for c in world.catalogue.columns["intake_source_versions"]]
    chosen = ", ".join(
        {"version": "version + 1", "file_sha256": ":s"}.get(c, f'"{c}"') for c in columns
    )
    with sync_engine.begin() as conn:
        version = a.rows["intake_source_versions"][0]
        conn.execute(
            sa.text(
                f"INSERT INTO intake_source_versions ({', '.join(f'{chr(34)}{c}{chr(34)}' for c in columns)}) "  # noqa: E501
                f"SELECT {chosen} FROM intake_source_versions "
                "WHERE source_id = :id AND version = :v"
            ),
            {"s": shared, "id": version["source_id"], "v": version["version"]},
        )
    assert set(a.rows) == set(world.catalogue.order)
    assert any(t.startswith(CHECKPOINT_SCHEMA) for t in a.rows), "checkpoint rows are seeded"

    report = _run(purge_url, world.store)

    assert a.opportunity_id in report.purged
    assert b.opportunity_id not in report.purged + report.failed
    assert {t: n for t, n in remaining(sync_engine, world.catalogue, a).items() if n} == {}
    with sync_engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM intake_source_versions WHERE file_sha256 = :s"),
                {"s": shared},
            ).scalar_one()
            == 1
        )
    assert set(remaining(sync_engine, world.catalogue, b).values()) == {1}

    # Files: the shared blob loses one reference and stays; sole ones go (a missing one too).
    assert _ref_count(sync_engine, shared) == 1 and shared_path.exists()
    for sha, path in (
        (sole_upload, sole_path),
        (sole_text, text_path),
        (page, page_path),
        (page_text, page_text_path),
    ):
        assert _ref_count(sync_engine, sha) == 0
        assert not path.exists()
    assert _ref_count(sync_engine, missing) == 0

    # One event: no Opportunity on it, the purged UUID as subject, the rule, counts only.
    (event,) = _purge_events(sync_engine, a.opportunity_id)
    assert event["opportunity_id"] is None
    assert (event["actor_type"], event["actor_id"]) == ("system", "platform.purge")
    assert event["subject_type"] == "opportunities.opportunity"
    payload = event["payload"]
    assert set(payload) == {
        "purged_opportunity_id",
        "rule",
        "retention_until",
        "rows_by_module",
        "files_deleted",
    }
    assert payload["purged_opportunity_id"] == str(a.opportunity_id)
    assert payload["rule"] == "lost_3y"
    assert payload["retention_until"] == "2026-01-01"
    assert payload["files_deleted"] == 5
    counts = payload["rows_by_module"]
    for module in (step.module for step in registry.steps()):
        assert counts[module] > 0, module
    assert counts["platform"] >= 4
    seeded_rows = sum(len(rows) for rows in a.rows.values()) + 1  # + the second version
    assert sum(counts.values()) == seeded_rows
    text = json.dumps(payload)
    customer = a.rows["opportunities_opportunities"][0]["customer_name"]
    assert a.title not in text and customer not in text

    # Shared data is untouched.
    with sync_engine.connect() as conn:
        for table, count in shared_before.items():
            after = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert after == count, table

    # Rerun: A is not selected again, nothing else changes.
    rerun = _run(purge_url, world.store)
    assert a.opportunity_id not in rerun.purged + rerun.failed
    assert len(_purge_events(sync_engine, a.opportunity_id)) == 1
    assert set(remaining(sync_engine, world.catalogue, b).values()) == {1}


def test_not_yet_due_open_and_future_won_opportunities_are_untouched(
    sync_engine: Engine, purge_url: str, world: World
) -> None:
    only = ("opportunities_opportunities", "notifications_notifications")
    on_the_day = _lost(world, sync_engine, datetime(2023, 10, 28, 12, tzinfo=UTC), only=only)
    open_one = _open(world, sync_engine, only=only)
    won = seed_opportunity(
        sync_engine,
        world.catalogue,
        outcome="won",
        recorded_at=datetime(2020, 1, 1, tzinfo=UTC),
        contract_end=date(2020, 1, 1),  # retention 1 Jan 2027: still in the future
        config_version_id=world.config_version_id,
        only=only,
    )
    report = _run(purge_url, world.store)
    for seeded in (on_the_day, open_one, won):
        assert seeded.opportunity_id not in report.purged + report.failed
        assert set(remaining(sync_engine, world.catalogue, seeded).values()) == {1}
        assert _purge_events(sync_engine, seeded.opportunity_id) == []

    # The day after its retention date, the lost one is due.
    next_day = _run(purge_url, world.store, today=TODAY + timedelta(days=1))
    assert on_the_day.opportunity_id in next_day.purged
    assert set(remaining(sync_engine, world.catalogue, on_the_day).values()) == {0}


def test_a_won_opportunity_past_contract_end_plus_7_years_is_purged_with_its_rule(
    sync_engine: Engine, purge_url: str, world: World
) -> None:
    won = seed_opportunity(
        sync_engine,
        world.catalogue,
        outcome="won",
        recorded_at=datetime(2018, 1, 1, tzinfo=UTC),
        contract_end=date(2019, 6, 30),
        config_version_id=world.config_version_id,
        only=("opportunities_opportunities", "estimates_baselines", "estimates_estimate_versions"),
    )
    report = _run(purge_url, world.store)
    assert won.opportunity_id in report.purged
    (event,) = _purge_events(sync_engine, won.opportunity_id)
    assert event["payload"]["rule"] == "won_7y"
    assert event["payload"]["retention_until"] == "2026-06-30"
    assert event["payload"]["rows_by_module"]["estimates"] == 2


@pytest.fixture
def failing_for(monkeypatch: pytest.MonkeyPatch) -> Iterator[set[UUID]]:
    """Opportunities in this set make an extra step fail, after the others ran."""
    failing: set[UUID] = set()

    async def fail(session: AsyncSession, opportunity_id: UUID) -> StepResult:
        if opportunity_id in failing:
            raise RuntimeError("step failed")
        return StepResult(rows=0)

    step = PurgeStep(module="zz_failing", order=999, fn=fail, tables=frozenset({"x"}))
    monkeypatch.setattr(registry, "_STEPS", [*registry._STEPS, step])
    yield failing


def _ctx(engine: AsyncEngine, attempt: int, max_attempts: int = 3) -> JobContext:
    return JobContext(
        job_id=uuid4(),
        job_type="platform.purge",
        attempt=attempt,
        max_attempts=max_attempts,
        opportunity_id=None,
        engine=engine,
    )


def _handle(
    db_url: str, purge_url: str, store: BlobStore, attempt: int, monkeypatch: pytest.MonkeyPatch
) -> BaseException | None:
    settings = Settings(database_url=db_url, purge_database_url=purge_url, storage_dir=store._root)
    monkeypatch.setattr(purge_job, "purge_settings", lambda: settings)
    monkeypatch.setattr(purge_job, "create_purge_engine", lambda url, s: purge_engine(url))
    monkeypatch.setattr(purge_job, "today_utc", lambda: TODAY)

    async def scenario() -> BaseException | None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            await purge_job.purge(_ctx(engine, attempt), purge_job.Purge())
        except Exception as exc:
            return exc
        finally:
            await engine.dispose()
        return None

    return run_async(scenario())


def _purge_alerts(engine: Engine, opportunity_id: UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT * FROM platform_jobs WHERE job_type = 'platform.alert_email' "
                "AND payload->>'kind' = 'purge_failed' "
                "AND payload->'failed_opportunity_ids' ? :o"
            ),
            {"o": str(opportunity_id)},
        ).mappings()
        return [dict(row) for row in rows]


def _settle(engine: Engine, job_ids: list[UUID]) -> None:
    """Keep other tests' workers from sending the queued test alert."""
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE platform_jobs SET status = 'succeeded' WHERE id = ANY(:ids)"),
            {"ids": job_ids},
        )


def test_one_failure_rolls_back_only_that_opportunity_and_the_job_retries_then_alerts(
    sync_engine: Engine,
    db_url: str,
    purge_url: str,
    world: World,
    failing_for: set[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sole = _sha()
    path = _file(sync_engine, world.store, sole, 1)
    a = _lost(
        world,
        sync_engine,
        datetime(2023, 1, 1, tzinfo=UTC),
        shas={("intake_source_versions", "file_sha256"): sole},
    )
    b = _lost(world, sync_engine, datetime(2023, 2, 1, tzinfo=UTC))
    failing_for.add(a.opportunity_id)

    # Attempt 1 of 3: A rolls back (rows, refcount, blob, no event), B is purged, it retries.
    error = _handle(db_url, purge_url, world.store, 1, monkeypatch)
    assert isinstance(error, purge_job.PurgeIncompleteError)
    assert set(remaining(sync_engine, world.catalogue, a).values()) == {1}
    assert _ref_count(sync_engine, sole) == 1 and path.exists()
    assert _purge_events(sync_engine, a.opportunity_id) == []
    assert set(remaining(sync_engine, world.catalogue, b).values()) == {0}
    assert len(_purge_events(sync_engine, b.opportunity_id)) == 1
    assert _purge_alerts(sync_engine, a.opportunity_id) == []

    # The last attempt still fails: an alert email is queued (counts and UUIDs only).
    error = _handle(db_url, purge_url, world.store, 3, monkeypatch)
    assert isinstance(error, purge_job.PurgeIncompleteError)
    (alert,) = _purge_alerts(sync_engine, a.opportunity_id)
    _settle(sync_engine, [alert["id"]])
    assert alert["status"] == "queued"
    assert alert["payload"]["failed_count"] >= 1
    assert alert["payload"]["attempts"] == 3
    assert a.title not in json.dumps(alert["payload"])

    # Fixed: the next run purges A.
    failing_for.clear()
    assert _handle(db_url, purge_url, world.store, 1, monkeypatch) is None
    assert set(remaining(sync_engine, world.catalogue, a).values()) == {0}
    assert _ref_count(sync_engine, sole) == 0 and not path.exists()


def test_without_a_purge_url_nothing_is_deleted_and_the_job_succeeds(
    sync_engine: Engine, db_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _lost(
        world,
        sync_engine,
        datetime(2023, 1, 1, tzinfo=UTC),
        only=("opportunities_opportunities",),
    )
    settings = Settings(database_url=db_url)
    assert settings.purge_database_url is None
    monkeypatch.setattr(purge_job, "purge_settings", lambda: settings)

    async def scenario() -> None:
        engine = create_engine(settings)
        try:
            await purge_job.purge(_ctx(engine, 1), purge_job.Purge())
        finally:
            await engine.dispose()

    run_async(scenario())
    assert set(remaining(sync_engine, world.catalogue, a).values()) == {1}
    # Leave nothing due behind for other tests' purges to find.
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE opportunities_opportunities SET outcome = NULL, "
                "outcome_recorded_at = NULL WHERE id = :o"
            ),
            {"o": a.opportunity_id},
        )


def test_a_blank_purge_url_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PSA_PURGE_DATABASE_URL", " ")
    assert Settings().purge_database_url is None


def test_the_purge_job_is_scheduled_daily(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT job_type, interval_s FROM platform_schedules WHERE name = :n"),
            {"n": "platform.purge"},
        ).one()
    assert tuple(row) == ("platform.purge", 86_400)
    assert purge_job.PURGE_JOB.max_attempts >= 2


def test_the_purge_alert_email_holds_counts_and_uuids_only() -> None:
    from app.platform.alerts.jobs import AlertEmailJob, PurgeFailedAlert, alert_email_for

    failed = [uuid4(), uuid4()]
    job = AlertEmailJob.model_validate(
        AlertEmailJob(
            alert=PurgeFailedAlert(
                failed_count=3, failed_opportunity_ids=failed, purged_count=4, attempts=3
            )
        ).model_dump(mode="json")
    )
    email = alert_email_for(job, "https://psa.example.test/")
    assert email.subject == "[PSA] The retention purge failed for 3 Opportunities"
    for value in (*map(str, failed), "- and 1 more", "4 were purged", "after 3 attempts"):
        assert value in email.text
    assert "https://psa.example.test/admin/retention" in email.text
    run_failed = alert_email_for(
        AlertEmailJob(
            alert=PurgeFailedAlert(
                failed_count=0, failed_opportunity_ids=[], purged_count=0, attempts=3
            )
        ),
        "https://psa.example.test",
    )
    assert run_failed.subject == "[PSA] The retention purge could not run"


# --- review fixes: re-check under lock, post-commit blobs, run-linked rows, run failure ---------


def _stale_selection(monkeypatch: pytest.MonkeyPatch, purge_url: str, *ids: UUID) -> None:
    """Make the next run work from a selection taken now (before the test changes things)."""

    async def select() -> list[RetentionDue]:
        engine = purge_engine(purge_url)
        try:
            return [
                d
                for d in await purge_job.due_opportunities(engine, TODAY)
                if d.opportunity_id in ids
            ]
        finally:
            await engine.dispose()

    selected = run_async(select())
    assert {d.opportunity_id for d in selected} == set(ids)

    async def stale(engine: AsyncEngine, today: date) -> list[RetentionDue]:
        return selected

    monkeypatch.setattr(purge_job, "due_opportunities", stale)


def test_an_opportunity_reopened_after_selection_is_untouched(
    sync_engine: Engine, purge_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _lost(world, sync_engine, datetime(2023, 1, 1, tzinfo=UTC))
    _stale_selection(monkeypatch, purge_url, a.opportunity_id)
    with sync_engine.begin() as conn:  # reopened between the selection and the purge
        conn.execute(
            sa.text(
                "UPDATE opportunities_opportunities SET outcome = NULL, "
                "outcome_recorded_at = NULL WHERE id = :o"
            ),
            {"o": a.opportunity_id},
        )
    report = _run(purge_url, world.store)
    assert a.opportunity_id not in report.purged + report.failed
    assert set(remaining(sync_engine, world.catalogue, a).values()) == {1}
    assert _purge_events(sync_engine, a.opportunity_id) == []


def test_an_opportunity_purged_after_selection_gets_no_second_event(
    sync_engine: Engine, purge_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _lost(
        world, sync_engine, datetime(2023, 1, 1, tzinfo=UTC), only=("opportunities_opportunities",)
    )
    _stale_selection(monkeypatch, purge_url, a.opportunity_id)
    first = _run(purge_url, world.store)
    second = _run(purge_url, world.store)  # same (now stale) selection: A is gone
    assert a.opportunity_id in first.purged
    assert a.opportunity_id not in second.purged + second.failed
    assert len(_purge_events(sync_engine, a.opportunity_id)) == 1


def test_a_blob_that_cannot_be_deleted_after_commit_leaves_the_purge_standing(
    sync_engine: Engine, purge_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    sole = _sha()
    path = _file(sync_engine, world.store, sole, 1)
    a = _lost(
        world,
        sync_engine,
        datetime(2023, 1, 1, tzinfo=UTC),
        shas={("intake_source_versions", "file_sha256"): sole},
    )

    async def refuse(self: BlobStore, sha256: str) -> None:
        raise PermissionError("read-only volume")

    monkeypatch.setattr(BlobStore, "delete", refuse)
    report = _run(purge_url, world.store)
    assert a.opportunity_id in report.purged
    assert a.opportunity_id not in report.failed
    assert set(remaining(sync_engine, world.catalogue, a).values()) == {0}
    assert len(_purge_events(sync_engine, a.opportunity_id)) == 1
    assert _ref_count(sync_engine, sole) == 0
    assert path.exists()  # orphaned, not deleted


def _copy(
    engine: Engine, catalogue: Catalogue, table: str, row: dict[str, Any], **changes: Any
) -> Any:
    """Insert a copy of a seeded row with a new `id` and `changes`; the new id."""
    new_id = uuid4()
    values = {**row, "id": new_id, **changes}
    types = {c.name: c.sql_type for c in catalogue.columns[table]}
    names = ", ".join(f'"{n}"' for n in values)
    params = ", ".join(f"CAST(:p{i} AS {types[n]})" for i, n in enumerate(values))
    with engine.begin() as conn:
        conn.execute(
            sa.text(f"INSERT INTO {table} ({names}) VALUES ({params})"),
            {f"p{i}": v for i, v in enumerate(values.values())},
        )
    return new_id


def test_platform_rows_linked_only_through_a_run_are_purged(
    sync_engine: Engine, purge_url: str, world: World
) -> None:
    a = _lost(world, sync_engine, datetime(2023, 1, 1, tzinfo=UTC))
    b = _open(world, sync_engine)
    trace_id = _copy(
        sync_engine,
        world.catalogue,
        "platform_trace_events",
        a.rows["platform_trace_events"][0],
        opportunity_id=None,
    )
    model_id = _copy(
        sync_engine,
        world.catalogue,
        "platform_model_calls",
        a.rows["platform_model_calls"][0],
        opportunity_id=None,
    )
    tool_id = _copy(  # its opportunity_id is NOT NULL: another Opportunity's, A's run
        sync_engine,
        world.catalogue,
        "platform_tool_calls",
        a.rows["platform_tool_calls"][0],
        opportunity_id=b.opportunity_id,
    )
    report = _run(purge_url, world.store)
    assert a.opportunity_id in report.purged
    with sync_engine.connect() as conn:
        for table, row_id in (
            ("platform_trace_events", trace_id),
            ("platform_model_calls", model_id),
            ("platform_tool_calls", tool_id),
        ):
            count = conn.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE id = :i"),
                {"i": row_id},
            ).scalar_one()
            assert count == 0, table
    assert set(remaining(sync_engine, world.catalogue, b).values()) == {1}


def test_a_run_that_cannot_select_alerts_on_its_last_attempt_and_raises(
    sync_engine: Engine,
    db_url: str,
    purge_url: str,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SelectorDown(RuntimeError):
        pass

    async def broken(session: AsyncSession, before: date) -> list[RetentionDue]:
        raise SelectorDown("selector down")

    monkeypatch.setattr(registry, "_SELECTORS", [broken])
    with sync_engine.connect() as conn:
        started = conn.execute(sa.text("SELECT now()")).scalar_one()
    error = _handle(db_url, purge_url, world.store, 3, monkeypatch)
    assert isinstance(error, SelectorDown)
    with sync_engine.connect() as conn:
        alerts = [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_jobs WHERE job_type = 'platform.alert_email' "
                    "AND payload->>'kind' = 'purge_failed' AND created_at >= :t"
                ),
                {"t": started},
            ).mappings()
        ]
    _settle(sync_engine, [alert["id"] for alert in alerts])
    (alert,) = alerts
    assert alert["payload"]["failed_count"] == 0
    assert alert["payload"]["failed_opportunity_ids"] == []
    assert alert["payload"]["attempts"] == 3
