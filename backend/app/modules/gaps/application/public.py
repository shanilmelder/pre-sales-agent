"""gaps' public API. Other modules import gaps only from here."""

from uuid import UUID

from app.modules.gaps.application import answer_matching, detection
from app.modules.gaps.application.answer_matching import confirm_match, reject_match
from app.modules.gaps.application.conversion import mark_converted
from app.modules.gaps.application.gap_commands import change_impact, dismiss_gap, reopen_gap
from app.modules.gaps.application.gap_refs import (
    GapSummary,
    gap_summaries,
    open_gap_counts,
    open_gap_summaries,
)
from app.modules.gaps.application.gaps import irrelevance_share, list_gaps, start_detection
from app.modules.gaps.application.models import (
    AnswerPassage,
    AnswerRequest,
    AnswerSuggestion,
    ApproveAllResult,
    ApproveSelectedResult,
    ClarificationQuestion,
    Detection,
    Gap,
    GapAnswer,
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
    answer_question,
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


async def enqueue_answer_matching(
    uow: UnitOfWork, *, opportunity_id: UUID, source_id: UUID, version: int
) -> UUID | None:
    """Queue `gaps.match_answers` for a newly parsed Source version in the caller's Unit of
    Work (Story 4.7: after every successful parse); skipped (None) when no Clarification
    Question is `sent` or `unanswered`."""
    return await answer_matching.enqueue_answer_matching(
        uow, opportunity_id=opportunity_id, source_id=source_id, version=version
    )


__all__ = [
    "AnswerPassage",
    "AnswerRequest",
    "AnswerSuggestion",
    "ApproveAllResult",
    "ApproveSelectedResult",
    "ClarificationQuestion",
    "Detection",
    "ExportStorage",
    "Gap",
    "GapAnswer",
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
    "answer_question",
    "approve_all",
    "approve_question",
    "approve_selected",
    "change_impact",
    "confirm_match",
    "dismiss_gap",
    "edit_question",
    "enqueue_answer_matching",
    "enqueue_detection",
    "export_questions",
    "gap_summaries",
    "irrelevance_share",
    "list_gaps",
    "mark_converted",
    "mark_sent",
    "mark_unanswered",
    "open_gap_counts",
    "open_gap_summaries",
    "reject_match",
    "reopen_gap",
    "start_detection",
]
