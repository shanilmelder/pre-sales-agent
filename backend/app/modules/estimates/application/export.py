"""Export the current draft Estimate Version (Story 8.8, demo slice).

`export_estimate` builds the file in the request, synchronously, from the same read models
the tabs use (`get_estimate`, `gaps.list_gaps`): no job, no storage, no signed URL. Allowed
for `estimates.estimate.export` (the owner and collaborators except sales representatives;
other readers 403, everyone else the Opportunity's 404); 409 `estimate_not_found` when the
Opportunity has no Estimate Version yet. Appends `estimates.estimate_version.exported`
(version and format only); no line, Assumption or question text is logged or traced.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.modules.estimates.adapters.export_docx import render_docx
from app.modules.estimates.adapters.export_xlsx import render_xlsx
from app.modules.estimates.application.estimates import get_estimate
from app.modules.estimates.application.export_content import (
    MEDIA_TYPES,
    ExportDocument,
    ExportFormat,
    build_export,
    file_name,
)
from app.modules.estimates.domain.estimates import VERSION_SUBJECT_TYPE
from app.modules.gaps.application import public as gaps
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.errors import EstimateNotFoundError
from app.platform.logging import get_logger
from app.platform.trace.catalogue import EstimatesEstimateVersionExported
from app.platform.uow import UnitOfWork

NO_ESTIMATE_DETAIL = "This Opportunity has no Estimate to export yet."
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportFile:
    file_name: str
    media_type: str
    content: bytes


def render(document: ExportDocument, export_format: ExportFormat) -> bytes:
    """The file's bytes in the asked format."""
    if export_format is ExportFormat.XLSX:
        return render_xlsx(document)
    return render_docx(document)


async def export_estimate(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    export_format: ExportFormat,
    *,
    now: datetime | None = None,
) -> ExportFile:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_EXPORT, resource)
    view = await get_estimate(uow, actor, opportunity_id)
    version = view.version
    if version is None:
        raise EstimateNotFoundError(NO_ESTIMATE_DETAIL)
    gap_list = await gaps.list_gaps(uow, actor, opportunity_id)
    opportunity = await opportunities.get(uow, actor, opportunity_id)
    document = build_export(
        opportunity_title=opportunity.title,
        version=version,
        gaps=gap_list.items,
        exported_at=now or datetime.now(UTC),
    )
    content = await asyncio.to_thread(render, document, export_format)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesEstimateVersionExported(
            version_id=version.id,
            version=version.version,
            format="xlsx" if export_format is ExportFormat.XLSX else "docx",
        ),
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=UUID(version.id),
        opportunity_id=opportunity_id,
        subject_version=version.row_version,
    )
    _log.info(
        "estimates.estimate_exported",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": version.id,
            "version": version.version,
            "format": export_format.value,
            "bytes": len(content),
            "actor_id": actor.actor.id,
        },
    )
    return ExportFile(
        file_name=file_name(opportunity.title, version.version, export_format),
        media_type=MEDIA_TYPES[export_format],
        content=content,
    )
