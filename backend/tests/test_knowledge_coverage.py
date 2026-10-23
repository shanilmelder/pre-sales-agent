"""`knowledge.get_coverage` (Story 4.1) against a real, migrated Postgres as psa_app: a
product or Integration Type is Ready only with an active Source matching it (product
trimmed and ignoring case, or by tag) whose latest version is embedded. Sources are written
directly; products and tags are unique per test, as the database is shared."""

from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import Coverage
from app.platform.uow import unit_of_work
from tests.conftest import run_async


def _entry(engine: Engine) -> UUID:
    entry_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_catalogue_entries (id, kind, code, status, row_version) "
                "VALUES (:i, 'integration_type', :c, 'active', 1)"
            ),
            {"i": entry_id, "c": f"COV-{uuid4().hex[:8]}"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_catalogue_entry_versions "
                "(entry_id, version, name, definition, changed_by) "
                "VALUES (:i, 1, :n, 'A definition.', :u)"
            ),
            {"i": entry_id, "n": f"Type {uuid4().hex}", "u": uuid4()},
        )
    return entry_id


def _source(
    engine: Engine,
    product: str,
    tags: tuple[UUID, ...] = (),
    *,
    embeds: list[str | None],
    status: str = "active",
) -> UUID:
    """A Source with one version per item of `embeds`: that version's embed status (None:
    no embedding state)."""
    source_id, user = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_sources (id, title, product, owner_id, status, "
                "retired_reason, last_reviewed_on, created_by, row_version) "
                "VALUES (:i, 'Guide', :p, :u, :s, :r, current_date, :u, 1)"
            ),
            {
                "i": source_id,
                "p": product,
                "u": user,
                "s": status,
                "r": "Old" if status == "retired" else None,
            },
        )
        for entry_id in tags:
            conn.execute(
                sa.text("INSERT INTO knowledge_source_tags (source_id, entry_id) VALUES (:s, :e)"),
                {"s": source_id, "e": entry_id},
            )
        for version, embed in enumerate(embeds, start=1):
            params: dict[str, Any] = {"s": source_id, "v": version, "u": user}
            conn.execute(
                sa.text(
                    "INSERT INTO knowledge_source_versions (source_id, version, product_version, "
                    "file_sha256, filename, size_bytes, uploaded_by) "
                    "VALUES (:s, :v, '1.0', :h, 'guide.md', 10, :u)"
                ),
                {**params, "h": uuid4().hex},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO knowledge_source_parses (source_id, version, status, "
                    "text_sha256, char_count, parser) VALUES (:s, :v, 'parsed', :h, 10, 'text')"
                ),
                {**params, "h": uuid4().hex},
            )
            if embed is not None:
                ready = embed == "ready"
                conn.execute(
                    sa.text(
                        "INSERT INTO knowledge_source_embeds (source_id, version, status, "
                        "error_code, chunk_count, model) VALUES (:s, :v, :st, :e, :c, :m)"
                    ),
                    {
                        **params,
                        "st": embed,
                        "e": "internal_error" if embed == "failed" else None,
                        "c": 1 if ready else None,
                        "m": "bge-m3" if ready else None,
                    },
                )
    return source_id


def _coverage(db_url: str, *, products: list[str], types: list[UUID]) -> Coverage:
    async def go() -> Coverage:
        engine = create_async_engine(db_url)
        try:
            async with unit_of_work(engine) as uow:
                return await knowledge.get_coverage(
                    uow, products=products, integration_type_ids=types
                )
        finally:
            await engine.dispose()

    return run_async(go())


def test_a_ready_source_covers_its_product_ignoring_case_and_space(
    sync_engine: Engine, db_url: str
) -> None:
    tag = uuid4().hex
    _source(sync_engine, f"Product {tag}", embeds=["ready"])

    coverage = _coverage(
        db_url,
        products=[f"  PRODUCT {tag.upper()} ", f"product {tag}", "  ", f"Other {tag}"],
        types=[],
    )

    assert [(p.product, p.ready) for p in coverage.products] == [
        (f"PRODUCT {tag.upper()}", True),
        (f"Other {tag}", False),
    ]
    assert coverage.integration_types == []


def test_a_ready_tagged_source_covers_its_integration_types(
    sync_engine: Engine, db_url: str
) -> None:
    covered, uncovered = _entry(sync_engine), _entry(sync_engine)
    _source(sync_engine, f"Product {uuid4().hex}", (covered,), embeds=["ready"])

    coverage = _coverage(db_url, products=[], types=[covered, uncovered, covered])

    assert [(t.id, t.ready) for t in coverage.integration_types] == [
        (str(covered), True),
        (str(uncovered), False),
    ]


def test_only_an_active_source_whose_latest_version_is_embedded_counts(
    sync_engine: Engine, db_url: str
) -> None:
    tag = uuid4().hex
    cases: dict[str, list[str | None]] = {
        "queued": ["queued"],
        "failed": ["failed"],
        "none": [None],
        "newer not ready": ["ready", "embedding"],
        "newer ready": ["queued", "ready"],
    }
    types = {name: _entry(sync_engine) for name in [*cases, "retired"]}
    for name, embeds in cases.items():
        _source(sync_engine, f"{name} {tag}", (types[name],), embeds=embeds)
    _source(sync_engine, f"retired {tag}", (types["retired"],), embeds=["ready"], status="retired")

    coverage = _coverage(
        db_url, products=[f"{name} {tag}" for name in types], types=list(types.values())
    )

    expected = {name: name == "newer ready" for name in types}
    assert {p.product.rsplit(" ", 1)[0]: p.ready for p in coverage.products} == expected
    by_id = {t.id: t.ready for t in coverage.integration_types}
    assert {name: by_id[str(i)] for name, i in types.items()} == expected
