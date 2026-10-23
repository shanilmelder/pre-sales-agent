"""knowledge's public API. Other modules import knowledge only from here.

Story 3.3: `search` (citable top-k chunks) and `resolve_evidence` (the `knowledge_chunk`
Evidence resolver, also registered with `app.platform.evidence` on import).

Story 3.4: the Checklist commands and views, and `find_applicable_checklists` (the latest
published version of every active Checklist whose scope matches, for Gap detection).

Story 4.1: `get_coverage` (whether active, embedded Sources document the products and
Integration Types in scope).

Story 5.4: the ToolGateway handlers (`tools`, registered on import), Research Snapshots
(`capture_research_snapshot`, the `research_snapshot` Evidence resolver `check_snapshot_refs`,
also registered on import) and `ResearchPage`, what the research fetch returns."""

from app.modules.knowledge.application import tools as tools  # registers the tool handlers
from app.modules.knowledge.application.catalogue import (
    create_entry,
    edit_entry,
    get_catalogue_entry,
    list_catalogue,
    list_entries,
    reactivate_entry,
    read_entry,
    read_versions,
    retire_entry,
    validate_catalogue_ref,
)
from app.modules.knowledge.application.checklist_models import (
    AffectedArea,
    ApplicableChecklist,
    ApplicableItem,
    Checklist,
    ChecklistDraft,
    ChecklistItem,
    ChecklistList,
    ChecklistVersion,
    ChecklistVersionList,
    ChecklistVersionSummary,
    DraftInput,
    DraftItemInput,
    NewChecklist,
    RetireChecklist,
)
from app.modules.knowledge.application.checklists import (
    create_checklist,
    find_applicable_checklists,
    list_checklists,
    open_draft,
    publish_checklist,
    read_checklist,
    read_checklist_version,
    read_checklist_versions,
    retire_checklist,
    save_draft,
)
from app.modules.knowledge.application.coverage import get_coverage
from app.modules.knowledge.application.evidence import check_chunk_refs, resolve_evidence
from app.modules.knowledge.application.models import (
    CatalogueEntry,
    CatalogueList,
    CatalogueVersion,
    CatalogueVersionList,
    EntryChanges,
    NewEntry,
    RetireRequest,
)
from app.modules.knowledge.application.research import (
    EVIDENCE_KIND as RESEARCH_SNAPSHOT_KIND,
)
from app.modules.knowledge.application.research import (
    ResearchPage,
    capture_research_snapshot,
    check_snapshot_refs,
)
from app.modules.knowledge.application.search import search
from app.modules.knowledge.application.source_models import (
    Coverage,
    DownloadLink,
    IntegrationTypeCoverage,
    IntegrationTypeTag,
    KnowledgeEvidence,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    KnowledgeSource,
    KnowledgeSourceEmbed,
    KnowledgeSourceList,
    KnowledgeSourceParse,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionList,
    KnowledgeSpan,
    KnowledgeUserRef,
    ProductCoverage,
    RetireSource,
    SourceChanges,
    SourceText,
)
from app.modules.knowledge.application.sources import (
    add_version,
    download_link,
    edit_source,
    list_sources,
    mark_reviewed,
    max_body_bytes,
    read_source,
    read_text,
    register_source,
    retire_source,
    retry_embed,
    retry_parse,
    search_owners,
)
from app.modules.knowledge.application.sources import (
    read_versions as read_source_versions,
)
from app.modules.knowledge.domain.catalogue import Kind, Status
from app.modules.knowledge.domain.checklists import Domain as ChecklistDomain
from app.modules.knowledge.domain.checklists import Impact as ChecklistImpact
from app.modules.knowledge.domain.checklists import ItemKind as ChecklistItemKind
from app.modules.knowledge.domain.embedding import (
    EVIDENCE_KIND,
    SEARCH_K_DEFAULT,
    SEARCH_K_MAX,
    EmbedErrorCode,
    EmbedStatus,
)

__all__ = [
    "EVIDENCE_KIND",
    "RESEARCH_SNAPSHOT_KIND",
    "SEARCH_K_DEFAULT",
    "SEARCH_K_MAX",
    "AffectedArea",
    "ApplicableChecklist",
    "ApplicableItem",
    "CatalogueEntry",
    "CatalogueList",
    "CatalogueVersion",
    "CatalogueVersionList",
    "Checklist",
    "ChecklistDomain",
    "ChecklistDraft",
    "ChecklistImpact",
    "ChecklistItem",
    "ChecklistItemKind",
    "ChecklistList",
    "ChecklistVersion",
    "ChecklistVersionList",
    "ChecklistVersionSummary",
    "Coverage",
    "DownloadLink",
    "DraftInput",
    "DraftItemInput",
    "EmbedErrorCode",
    "EmbedStatus",
    "EntryChanges",
    "IntegrationTypeCoverage",
    "IntegrationTypeTag",
    "Kind",
    "KnowledgeEvidence",
    "KnowledgeSearchHit",
    "KnowledgeSearchResult",
    "KnowledgeSource",
    "KnowledgeSourceEmbed",
    "KnowledgeSourceList",
    "KnowledgeSourceParse",
    "KnowledgeSourceVersion",
    "KnowledgeSourceVersionList",
    "KnowledgeSpan",
    "KnowledgeUserRef",
    "NewChecklist",
    "NewEntry",
    "ProductCoverage",
    "ResearchPage",
    "RetireChecklist",
    "RetireRequest",
    "RetireSource",
    "SourceChanges",
    "SourceText",
    "Status",
    "add_version",
    "capture_research_snapshot",
    "check_chunk_refs",
    "check_snapshot_refs",
    "create_checklist",
    "create_entry",
    "download_link",
    "edit_entry",
    "edit_source",
    "find_applicable_checklists",
    "get_catalogue_entry",
    "get_coverage",
    "list_catalogue",
    "list_checklists",
    "list_entries",
    "list_sources",
    "mark_reviewed",
    "max_body_bytes",
    "open_draft",
    "publish_checklist",
    "reactivate_entry",
    "read_checklist",
    "read_checklist_version",
    "read_checklist_versions",
    "read_entry",
    "read_source",
    "read_source_versions",
    "read_text",
    "read_versions",
    "register_source",
    "resolve_evidence",
    "retire_checklist",
    "retire_entry",
    "retire_source",
    "retry_embed",
    "retry_parse",
    "save_draft",
    "search",
    "search_owners",
    "validate_catalogue_ref",
]
