"""gaps' public API. Other modules import gaps only from here."""

from uuid import UUID

from app.modules.gaps.application import detection
from app.modules.gaps.application.conversion import mark_converted
from app.modules.gaps.application.gap_commands import change_impact, dismiss_gap, reopen_gap
from app.modules.gaps.application.gap_refs import GapSummary, gap_summaries, open_gap_summaries
from app.modules.gaps.application.gaps import irrelevance_share, list_gaps, start_detection
from app.modules.gaps.application.models import (
    ApproveAllResult,
    ApproveSelectedResult,
    ClarificationQuestion,
    Detection,
    Gap,
    GapDismissal,
    GapDismissalRequest,
    GapHistoryEntry,
    GapList,
    GapReopening,
    GapRequirement,
    GapTrigger,
    ImpactChange,
    IrrelevanceShare,
    MarkSentRequest,
    MarkSentResult,
    QuestionChanges,
    QuestionExport,
    QuestionExportFormat,
    QuestionExportRequest,
    QuestionVersion,
)
from app.modules.gaps.application.question_export import ExportStorage, export_questions
from app.modules.gaps.application.questions import (
    approve_all,
    approve_question,
    approve_selected,
    edit_question,
    mark_sent,
    mark_unanswered,
)
from app.modules.gaps.domain.gaps import GapCategory, Impact
from app.platform.uow import UnitOfWork


async def enqueue_detection(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Gap detection of the Opportunity in the caller's Unit of Work (Story 4.3:
    after every accepted Requirement extraction). Coalesces with a detection that is
    queued and not yet started; returns the detection's id."""
    return await detection.enqueue_detection(uow, opportunity_id)


__all__ = [
    "ApproveAllResult",
    "ApproveSelectedResult",
    "ClarificationQuestion",
    "Detection",
    "ExportStorage",
    "Gap",
    "GapCategory",
    "GapDismissal",
    "GapDismissalRequest",
    "GapHistoryEntry",
    "GapList",
    "GapReopening",
    "GapRequirement",
    "GapSummary",
    "GapTrigger",
    "Impact",
    "ImpactChange",
    "IrrelevanceShare",
    "MarkSentRequest",
    "MarkSentResult",
    "QuestionChanges",
    "QuestionExport",
    "QuestionExportFormat",
    "QuestionExportRequest",
    "QuestionVersion",
    "approve_all",
    "approve_question",
    "approve_selected",
    "change_impact",
    "dismiss_gap",
    "edit_question",
    "enqueue_detection",
    "export_questions",
    "gap_summaries",
    "irrelevance_share",
    "list_gaps",
    "mark_converted",
    "mark_sent",
    "mark_unanswered",
    "open_gap_summaries",
    "reopen_gap",
    "start_detection",
]
