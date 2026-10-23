"""Persistence for Knowledge chunks and embedding state (Story 3.3). Runs inside the caller's
Unit of Work.

Vector search follows AD-14: the query casts the untyped column exactly as the model's
partial HNSW index does (`embedding::vector(<dims>)`) and filters on the same
`embedding_model = '<model>'` literal, so the index can serve it and vectors of different
models are never compared. The model name and dims are inlined as literals (a bound parameter
would hide the predicate from the planner); both come from the fixed embedding profiles and
are checked against `_SAFE_MODEL` first.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.knowledge.adapters.models import (
    ChunkRow,
    SourceEmbedRow,
    SourceParseRow,
    SourceRow,
    SourceTagRow,
    SourceVersionRow,
)
from app.platform.uow import UnitOfWork

E = SourceEmbedRow
C = ChunkRow
_SAFE_MODEL = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")


@dataclass(frozen=True, slots=True)
class EmbedState:
    status: str
    error_code: str | None
    chunk_count: int | None
    model: str | None
    stale: bool = False
    """Still `queued` or `embedding` but untouched for longer than `stale_after_s`: its job
    died without recording a failure (cancelled on timeout, or its lease lost)."""


@dataclass(frozen=True, slots=True)
class EmbedTarget:
    """What the embed job needs about one Source version."""

    embed_status: str | None
    text_sha256: str | None
    product: str
    product_version: str
    integration_type_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class NewChunk:
    ordinal: int
    start: int
    end: int
    text: str = field(repr=False)
    embedding: list[float] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ChunkHit:
    id: UUID
    source_id: UUID
    version: int
    text: str = field(repr=False)
    start: int
    end: int
    title: str = field(repr=False)
    product: str
    product_version: str
    last_reviewed_on: date
    distance: float


@dataclass(frozen=True, slots=True)
class ChunkRef:
    id: UUID
    source_id: UUID
    version: int
    start: int
    end: int
    embedding_model: str


# --- embedding state --------------------------------------------------------------------------


async def embed_state(
    uow: UnitOfWork,
    source_id: UUID,
    version: int,
    *,
    for_update: bool = False,
    stale_after_s: float | None = None,
) -> EmbedState | None:
    stale: Any = sa.false()
    if stale_after_s is not None:
        stale = E.status.in_(("queued", "embedding")) & (
            E.updated_at < func.now() - timedelta(seconds=stale_after_s)
        )
    statement = select(E.status, E.error_code, E.chunk_count, E.model, stale.label("stale")).where(
        E.source_id == source_id, E.version == version
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).one_or_none()
    if row is None:
        return None
    return EmbedState(
        status=row.status,
        error_code=row.error_code,
        chunk_count=row.chunk_count,
        model=row.model,
        stale=bool(row.stale),
    )


async def queue_embed(uow: UnitOfWork, source_id: UUID, version: int) -> bool:
    """Insert the version's `queued` embedding row; False (no change) if it has one."""
    result = await uow.session.execute(
        pg_insert(E)
        .values(source_id=source_id, version=version, status="queued")
        .on_conflict_do_nothing(index_elements=[E.source_id, E.version])
        .returning(E.version)
    )
    return result.one_or_none() is not None


async def update_embed(
    uow: UnitOfWork,
    source_id: UUID,
    version: int,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    chunk_count: int | None = None,
    model: str | None = None,
) -> bool:
    """Move the embedding row to `status` if it is in one of `from_statuses`. False (and no
    change) otherwise."""
    result = await uow.session.execute(
        update(E)
        .where(E.source_id == source_id, E.version == version, E.status.in_(from_statuses))
        .values(
            status=status,
            error_code=error_code,
            chunk_count=chunk_count,
            model=model,
            updated_at=func.now(),
        )
        .returning(E.version)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


async def embed_target(uow: UnitOfWork, source_id: UUID, version: int) -> EmbedTarget | None:
    """The version's embedding status, extracted-text blob, product, product version and the
    Source's current Integration Type tags; None if there is no such version."""
    row = (
        await uow.session.execute(
            select(
                E.status,
                SourceParseRow.status.label("parse_status"),
                SourceParseRow.text_sha256,
                SourceRow.product,
                SourceVersionRow.product_version,
            )
            .select_from(SourceVersionRow)
            .join(SourceRow, SourceRow.id == SourceVersionRow.source_id)
            .join(
                SourceParseRow,
                (SourceParseRow.source_id == SourceVersionRow.source_id)
                & (SourceParseRow.version == SourceVersionRow.version),
            )
            .outerjoin(
                E,
                (E.source_id == SourceVersionRow.source_id)
                & (E.version == SourceVersionRow.version),
            )
            .where(SourceVersionRow.source_id == source_id, SourceVersionRow.version == version)
        )
    ).one_or_none()
    if row is None:
        return None
    tags = (
        await uow.session.execute(
            select(SourceTagRow.entry_id)
            .where(SourceTagRow.source_id == source_id)
            .order_by(SourceTagRow.entry_id)
        )
    ).scalars()
    return EmbedTarget(
        embed_status=row.status,
        text_sha256=row.text_sha256 if row.parse_status == "parsed" else None,
        product=row.product,
        product_version=row.product_version,
        integration_type_ids=list(tags),
    )


# --- chunks -------------------------------------------------------------------------------------


async def insert_chunks(
    uow: UnitOfWork,
    *,
    ids: Sequence[UUID],
    source_id: UUID,
    version: int,
    chunks: Sequence[NewChunk],
    product: str,
    product_version: str,
    integration_type_ids: list[UUID],
    model: str,
    dims: int,
) -> None:
    if not chunks:
        return
    await uow.session.execute(
        insert(C),
        [
            {
                "id": chunk_id,
                "source_id": source_id,
                "version": version,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "start_offset": chunk.start,
                "end_offset": chunk.end,
                "product": product,
                "product_version": product_version,
                "integration_type_ids": integration_type_ids,
                "embedding_model": model,
                "embedding_dims": dims,
                "embedding": chunk.embedding,
            }
            for chunk_id, chunk in zip(ids, chunks, strict=True)
        ],
    )


async def chunk_refs(uow: UnitOfWork, ids: Sequence[UUID]) -> dict[UUID, ChunkRef]:
    if not ids:
        return {}
    rows = (
        await uow.session.execute(
            select(
                C.id, C.source_id, C.version, C.start_offset, C.end_offset, C.embedding_model
            ).where(C.id.in_(list(ids)))
        )
    ).all()
    return {
        r.id: ChunkRef(
            id=r.id,
            source_id=r.source_id,
            version=r.version,
            start=r.start_offset,
            end=r.end_offset,
            embedding_model=r.embedding_model,
        )
        for r in rows
    }


@dataclass(frozen=True, slots=True)
class ChunkText:
    """A chunk with its text and its Source's title (Story 5.4: `knowledge.chunk.read`)."""

    id: UUID
    source_id: UUID
    version: int
    start: int
    end: int
    title: str = field(repr=False)
    text: str = field(repr=False)


async def chunk_texts(uow: UnitOfWork, ids: Sequence[UUID]) -> dict[UUID, ChunkText]:
    """These chunks with their text, by id; unknown ids are left out."""
    if not ids:
        return {}
    rows = (
        await uow.session.execute(
            select(
                C.id, C.source_id, C.version, C.start_offset, C.end_offset, C.text, SourceRow.title
            )
            .join(SourceRow, SourceRow.id == C.source_id)
            .where(C.id.in_(list(ids)))
        )
    ).all()
    return {
        r.id: ChunkText(
            id=r.id,
            source_id=r.source_id,
            version=r.version,
            start=r.start_offset,
            end=r.end_offset,
            title=r.title,
            text=r.text,
        )
        for r in rows
    }


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def search_sql(*, model: str, dims: int, product: bool, tag: bool, product_version: bool) -> str:
    """The search statement for one embedding model (module docstring). Optional filters add
    their own predicate; `:q` is the query vector and `:k` the limit."""
    if not _SAFE_MODEL.match(model) or not 1 <= dims <= 16000:
        raise ValueError("unsafe embedding model name or dims")
    cast = f"c.embedding::vector({dims})"
    filters = [
        f"c.embedding_model = '{model}'",
        "s.status = 'active'",
        "e.status = 'ready'",
        f"e.model = '{model}'",
        "c.version = (SELECT max(v2.version) FROM knowledge_source_versions v2 "
        "WHERE v2.source_id = c.source_id)",
    ]
    if product:
        filters.append("lower(s.product) = lower(:product)")
    if tag:
        filters.append(
            "EXISTS (SELECT 1 FROM knowledge_source_tags t "
            "WHERE t.source_id = c.source_id AND t.entry_id = :integration_type_id)"
        )
    if product_version:
        filters.append("lower(v.product_version) = lower(:product_version)")
    where = "\n  AND ".join(filters)
    return (
        "SELECT c.id, c.source_id, c.version, c.text, c.start_offset, c.end_offset, "
        "s.title, s.product, v.product_version, s.last_reviewed_on, "
        f"{cast} <=> CAST(:q AS vector({dims})) AS distance\n"
        "FROM knowledge_chunks c\n"
        "JOIN knowledge_sources s ON s.id = c.source_id\n"
        "JOIN knowledge_source_versions v ON v.source_id = c.source_id AND v.version = c.version\n"
        "JOIN knowledge_source_embeds e ON e.source_id = c.source_id AND e.version = c.version\n"
        f"WHERE {where}\n"
        f"ORDER BY {cast} <=> CAST(:q AS vector({dims}))\n"
        "LIMIT :k"
    )


async def search(
    uow: UnitOfWork,
    vector: Sequence[float],
    *,
    model: str,
    dims: int,
    k: int,
    product: str | None,
    integration_type_id: UUID | None,
    product_version: str | None,
) -> list[ChunkHit]:
    """The `k` chunks nearest to `vector` (cosine distance) among Ready, active, latest
    Source versions embedded with `model`."""
    statement = search_sql(
        model=model,
        dims=dims,
        product=product is not None,
        tag=integration_type_id is not None,
        product_version=product_version is not None,
    )
    params: dict[str, Any] = {"q": _vector_literal(vector), "k": k}
    if product is not None:
        params["product"] = product.strip()
    if integration_type_id is not None:
        params["integration_type_id"] = integration_type_id
    if product_version is not None:
        params["product_version"] = product_version.strip()
    # pgvector >= 0.8: keep scanning the HNSW index until enough rows pass the filters.
    await uow.session.execute(sa.text("SET LOCAL hnsw.iterative_scan = strict_order"))
    rows = (await uow.session.execute(sa.text(statement), params)).all()
    return [
        ChunkHit(
            id=r.id,
            source_id=r.source_id,
            version=r.version,
            text=r.text,
            start=r.start_offset,
            end=r.end_offset,
            title=r.title,
            product=r.product,
            product_version=r.product_version,
            last_reviewed_on=r.last_reviewed_on,
            distance=float(r.distance),
        )
        for r in rows
    ]
