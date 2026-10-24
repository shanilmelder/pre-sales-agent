"""Persistence for Research Snapshots (Story 5.4). Runs inside the caller's Unit of Work.
`knowledge_research_snapshots` is INSERT-only for the application role."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import insert, select

from app.modules.knowledge.adapters.models import ResearchSnapshotRow
from app.platform.uow import UnitOfWork

R = ResearchSnapshotRow


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    id: UUID
    opportunity_id: UUID
    text_sha256: str


async def insert_snapshot(
    uow: UnitOfWork,
    *,
    snapshot_id: UUID,
    opportunity_id: UUID,
    run_id: UUID | None,
    task_id: UUID | None,
    url: str,
    final_url: str,
    http_status: int,
    content_type: str,
    content_sha256: str,
    text_sha256: str,
    parser: str,
) -> None:
    await uow.session.execute(
        insert(R).values(
            id=snapshot_id,
            opportunity_id=opportunity_id,
            run_id=run_id,
            task_id=task_id,
            url=url,
            final_url=final_url,
            http_status=http_status,
            content_type=content_type,
            content_sha256=content_sha256,
            text_sha256=text_sha256,
            parser=parser,
        )
    )


async def snapshot_refs(uow: UnitOfWork, ids: Sequence[UUID]) -> dict[UUID, SnapshotRef]:
    """These snapshots' Opportunity and extracted-text hash, by id; unknown ids left out."""
    if not ids:
        return {}
    rows = (
        await uow.session.execute(
            select(R.id, R.opportunity_id, R.text_sha256).where(R.id.in_(list(ids)))
        )
    ).all()
    return {
        r.id: SnapshotRef(id=r.id, opportunity_id=r.opportunity_id, text_sha256=r.text_sha256)
        for r in rows
    }
