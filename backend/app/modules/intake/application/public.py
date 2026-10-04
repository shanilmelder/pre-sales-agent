"""intake's public API. Other modules import intake only from here."""

from app.modules.intake.application.models import (
    AddTextSource,
    ConfirmAllResult,
    Extraction,
    Passage,
    Requirement,
    RequirementChanges,
    RequirementEvidence,
    RequirementList,
    Source,
    SourceList,
    SourceParse,
)
from app.modules.intake.application.parsing import extracted_text, retry_parse
from app.modules.intake.application.passages import get_passage
from app.modules.intake.application.requirement_edits import (
    confirm_all,
    confirm_requirement,
    edit_requirement,
)
from app.modules.intake.application.requirement_refs import (
    RequirementSnapshot,
    RequirementVersionText,
    active_requirement_snapshots,
    requirement_version_texts,
)
from app.modules.intake.application.requirements import list_requirements, start_extraction
from app.modules.intake.application.sources import (
    MISSING_FILE_DETAIL,
    TEXT_BODY_MAX_BYTES,
    IncomingFile,
    add_file,
    add_text,
    list_sources,
    max_body_bytes,
)
from app.modules.intake.domain.sources import (
    EXTENSION_KINDS,
    TEXT_TOO_LONG_MESSAGE,
    SourceKind,
)

__all__ = [
    "EXTENSION_KINDS",
    "MISSING_FILE_DETAIL",
    "TEXT_BODY_MAX_BYTES",
    "TEXT_TOO_LONG_MESSAGE",
    "AddTextSource",
    "ConfirmAllResult",
    "Extraction",
    "IncomingFile",
    "Passage",
    "Requirement",
    "RequirementChanges",
    "RequirementEvidence",
    "RequirementList",
    "RequirementSnapshot",
    "RequirementVersionText",
    "Source",
    "SourceKind",
    "SourceList",
    "SourceParse",
    "active_requirement_snapshots",
    "add_file",
    "add_text",
    "confirm_all",
    "confirm_requirement",
    "edit_requirement",
    "extracted_text",
    "get_passage",
    "list_requirements",
    "list_sources",
    "max_body_bytes",
    "requirement_version_texts",
    "retry_parse",
    "start_extraction",
]
