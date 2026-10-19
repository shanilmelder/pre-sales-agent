"""intake's public API. Other modules import intake only from here."""

from app.modules.intake.application.file_text import FileTextUnreadableError, read_stored_text
from app.modules.intake.application.models import (
    AddTextSource,
    ConfirmAllResult,
    Extraction,
    Passage,
    PendingChange,
    Requirement,
    RequirementChangeRejection,
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
    accept_requirement_change,
    confirm_all,
    confirm_requirement,
    edit_requirement,
    propose_requirement_change,
    reject_requirement_change,
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
    StoredUpload,
    add_file,
    add_stored_file,
    add_text,
    list_sources,
    max_body_bytes,
    store_upload,
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
    "FileTextUnreadableError",
    "IncomingFile",
    "Passage",
    "PendingChange",
    "Requirement",
    "RequirementChangeRejection",
    "RequirementChanges",
    "RequirementEvidence",
    "RequirementList",
    "RequirementSnapshot",
    "RequirementVersionText",
    "Source",
    "SourceKind",
    "SourceList",
    "SourceParse",
    "StoredUpload",
    "accept_requirement_change",
    "active_requirement_snapshots",
    "add_file",
    "add_stored_file",
    "add_text",
    "confirm_all",
    "confirm_requirement",
    "edit_requirement",
    "extracted_text",
    "get_passage",
    "list_requirements",
    "list_sources",
    "max_body_bytes",
    "propose_requirement_change",
    "read_stored_text",
    "reject_requirement_change",
    "requirement_version_texts",
    "retry_parse",
    "start_extraction",
    "store_upload",
]
