"""intake's public API. Other modules import intake only from here."""

from app.modules.intake.application.models import (
    AddTextSource,
    Extraction,
    Passage,
    Requirement,
    RequirementEvidence,
    RequirementList,
    Source,
    SourceList,
    SourceParse,
)
from app.modules.intake.application.parsing import extracted_text, retry_parse
from app.modules.intake.application.passages import get_passage
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
    "Extraction",
    "IncomingFile",
    "Passage",
    "Requirement",
    "RequirementEvidence",
    "RequirementList",
    "Source",
    "SourceKind",
    "SourceList",
    "SourceParse",
    "add_file",
    "add_text",
    "extracted_text",
    "get_passage",
    "list_requirements",
    "list_sources",
    "max_body_bytes",
    "retry_parse",
    "start_extraction",
]
