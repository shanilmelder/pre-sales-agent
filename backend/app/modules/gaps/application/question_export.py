"""Exporting the approved Clarification Questions for the customer (Story 4.6, demo slice).

`export_questions` covers every `approved` question of the Opportunity's `open` Gaps, grouped
by topic and numbered (`adapters.question_document`), with only the customer's name, a date,
the topics and the question wording. `copy` returns the text; `docx` and `eml` are stored in
`platform.storage` and returned as a short-lived signed link (`platform.downloads`). The
`.eml` is an unsent draft with no recipient: the platform never sends anything.

Allowed for `gaps.clarification_question.send` (the owner and every collaborator, sales
representatives included; other readers 403, everyone else the Opportunity's 404). 409
`no_approved_questions` when there is nothing to export (no file, no event). Appends
`gaps.clarification_question.exported` (format and question ids) with the Opportunity as
subject; no question text is logged or traced.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.question_document import (
    ExportQuestion,
    QuestionDocument,
    build_document,
    file_name,
    plain_text,
    render_docx,
    render_eml,
)
from app.modules.gaps.application.models import QuestionExport, QuestionExportFormat
from app.modules.gaps.application.questions import _authorized
from app.modules.gaps.domain.gaps import QuestionStatus, impact_rank
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import downloads, trace
from app.platform.errors import NoApprovedQuestionsError
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import GapsClarificationQuestionExported
from app.platform.uow import UnitOfWork

OPPORTUNITY_SUBJECT_TYPE = "opportunities.opportunity"
NOTHING_DETAIL = (
    "There are no approved Clarification Questions of open Gaps to export. Approve some first."
)
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportStorage:
    """Where `docx` and `eml` files go, and how their links are signed."""

    store: BlobStore
    signing_key: str
    ttl_s: int


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _render(document: QuestionDocument, export_format: QuestionExportFormat) -> bytes:
    return render_docx(document) if export_format == "docx" else render_eml(document)


async def export_questions(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    export_format: QuestionExportFormat,
    storage: ExportStorage,
    *,
    today: date | None = None,
) -> QuestionExport:
    await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    found = await repo.questions_of_open_gaps(uow, opportunity_id, QuestionStatus.APPROVED.value)
    if not found:
        raise NoApprovedQuestionsError(NOTHING_DETAIL)
    opportunity = await opportunities.get(uow, actor, opportunity_id)
    on = today or datetime.now(UTC).date()
    document = build_document(
        customer_name=opportunity.customer_name,
        on=on,
        questions=[
            ExportQuestion(
                topic=q.topic,
                text=q.text,
                rank=(impact_rank(gap.impact), gap.created_at.isoformat(), str(gap.id)),
            )
            for q, gap in found
        ],
    )
    question_ids = [str(q.id) for q, _ in found]
    if export_format == "copy":
        result = QuestionExport(
            format=export_format, question_count=len(found), text=plain_text(document)
        )
        size = len(result.text or "")
    else:
        content = await asyncio.to_thread(_render, document, export_format)
        blob = await storage.store.put_stream(_one_chunk(content), max_bytes=len(content))
        name = file_name(opportunity.customer_name, on, export_format)
        token, expires_at = downloads.sign(
            storage.signing_key, sha256=blob.sha256, filename=name, ttl_s=storage.ttl_s
        )
        result = QuestionExport(
            format=export_format,
            question_count=len(found),
            url=downloads.link_for(token),
            file_name=name,
            expires_at=expires_at,
        )
        size = blob.size
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionExported(format=export_format, question_ids=question_ids),
        subject_type=OPPORTUNITY_SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "gaps.clarification_questions_exported",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": actor.actor.id,
            "format": export_format,
            "count": len(found),
            "size": size,
        },
    )
    return result
