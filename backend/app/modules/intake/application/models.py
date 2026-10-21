"""Read models for Opportunity Sources (Story 2.1), their parse state (Story 2.2),
Requirements (Story 2.5) and cited passages (Story 2.5 Part B), and the Requirement
commands' bodies (Stories 2.6 and 2.7)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.intake.domain.parsing import ParseErrorCode, ParseStatus
from app.modules.intake.domain.requirements import (
    MERGE_MAX,
    MERGE_MIN,
    REJECT_REASON_MAX,
    REQUIREMENT_TEXT_MAX,
    SPLIT_PARTS,
    Classification,
    ExtractionErrorCode,
    ExtractionStatus,
    RequirementOrigin,
    RequirementStatus,
)
from app.modules.intake.domain.sources import TEXT_MAX_CHARS, SourceKind
from app.modules.opportunities.application.public import UserRef


class SourceParse(BaseModel):
    """The parse state of a Source's latest version. `error_code` is set only when
    `failed`."""

    status: ParseStatus
    error_code: ParseErrorCode | None


class Source(BaseModel):
    """An Opportunity Source with its latest version. `filename`, `size_bytes`,
    `uploaded_by`, `uploaded_at` and `parse` describe that version; `version_count` counts
    them all. `parse` is null only for a version with no parse state."""

    id: str
    kind: SourceKind
    filename: str
    version: int = Field(ge=1)
    version_count: int = Field(ge=1)
    size_bytes: int = Field(ge=1)
    uploaded_by: UserRef
    uploaded_at: datetime
    created_at: datetime
    parse: SourceParse | None


class SourceList(BaseModel):
    """An Opportunity's Sources, newest first."""

    items: list[Source]


class OpportunitySourceText(BaseModel):
    """The extracted text of a parsed Source version, exactly as stored (Story 2.3).
    `char_count` is in Unicode code points."""

    version: int = Field(ge=1)
    char_count: int
    text: str


class OpportunitySourceDownloadLink(BaseModel):
    """A short-lived signed link to a Source version's original file (Story 2.3). `url` is
    relative to the API origin."""

    url: str
    expires_at: datetime


class AddTextSource(BaseModel):
    """Pasted text to add as a Source (Story 2.1 Part B). Only its shape is checked here;
    the trimming, length and character rules are the command's, so their rejections carry
    the UI sentences."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(
        description="The pasted text. Trimmed, it must be 1 to "
        f"{TEXT_MAX_CHARS:,} characters with no NUL character or lone surrogate."
    )


# --- Requirements (Story 2.5 Part A) --------------------------------------------------------


class RequirementEvidence(BaseModel):
    """A Source passage a Requirement cites. `label` is `S<n> · <file name>`, where `n` is
    the Source's position among the Opportunity's Sources, oldest first."""

    passage_id: str
    source_id: str
    source_version: int = Field(ge=1)
    filename: str
    label: str


class PendingChange(BaseModel):
    """A change extraction proposes to a human-locked Requirement (Story 2.7): the proposed
    text and classification, and the new passages it would cite (`evidence`). A person
    accepts it or rejects it with a reason."""

    id: str
    text: str
    classification: Classification
    evidence: list[RequirementEvidence]
    proposed_at: datetime


class Requirement(BaseModel):
    """An active Requirement of the Opportunity with the passages it cites. `origin` is
    `human` once a person edited it (Story 2.6); `confirmed_at` and `confirmed_by` are set
    once confirmed. `last_changed_by`: the person behind the latest edit or confirmation
    (null when the latest change was extraction's). `pending_change`: the open change
    proposed to it, if any (Story 2.7). `number`: its stable `R<n>` within the Opportunity,
    never reused (Story 2.6). A Requirement a person created has origin `human` and no
    Evidence. `row_version` goes back in `If-Match`."""

    id: str
    number: int = Field(ge=1)
    text: str
    classification: Classification
    origin: RequirementOrigin
    locked_by_human: bool
    version: int = Field(ge=1)
    row_version: int = Field(ge=1)
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by: UserRef | None
    last_changed_by: UserRef | None
    evidence: list[RequirementEvidence]
    pending_change: PendingChange | None


class Extraction(BaseModel):
    """The Opportunity's latest Requirement extraction. `error_code` is set only when
    `failed`; `source_count` once it has read its Sources."""

    status: ExtractionStatus
    error_code: ExtractionErrorCode | None
    source_count: int | None


class RequirementList(BaseModel):
    """The Opportunity's active Requirements by number (oldest first), and its latest
    extraction (null when none has been queued yet). `can_start_extraction`: whether the
    caller may start (retry) an extraction; `can_edit_requirements`: whether they may edit,
    confirm, create, delete, split and merge the Requirements (Story 2.6). The UI only uses
    them to hide controls; the API decides."""

    items: list[Requirement]
    extraction: Extraction | None
    can_start_extraction: bool
    can_edit_requirements: bool


class RequirementChanges(BaseModel):
    """A human edit of a Requirement (Story 2.6). Fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr | None = Field(
        default=None,
        description=f"The new text. Trimmed, it must be 1 to {REQUIREMENT_TEXT_MAX:,} characters.",
    )
    classification: Classification | None = None


class RequirementChangeRejection(BaseModel):
    """Why a person rejects a pending Requirement change (Story 2.7)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(
        description=f"Trimmed, it must be 1 to {REJECT_REASON_MAX} characters."
    )


_TEXT_DESCRIPTION = f"Trimmed, it must be 1 to {REQUIREMENT_TEXT_MAX:,} characters."


class RequirementDraft(BaseModel):
    """A new Requirement's text and classification, as a person wrote it (Story 2.6)."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(description=_TEXT_DESCRIPTION)
    classification: Classification


class RequirementDeletion(BaseModel):
    """Why a person deletes a Requirement (Story 2.6)."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(
        description=f"Trimmed, it must be 1 to {REJECT_REASON_MAX} characters."
    )


class RequirementSplit(BaseModel):
    """The two Requirements one Requirement is split into (Story 2.6)."""

    model_config = ConfigDict(extra="forbid")

    parts: list[RequirementDraft] = Field(min_length=SPLIT_PARTS, max_length=SPLIT_PARTS)


class MergedRequirementRef(BaseModel):
    """A Requirement to merge, at the row version the caller read (its `If-Match`)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    row_version: int = Field(ge=1)


class RequirementMerge(BaseModel):
    """The Requirements to merge (distinct, each at the row version the caller read) and the
    merged Requirement's text and classification (Story 2.6)."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[MergedRequirementRef] = Field(min_length=MERGE_MIN, max_length=MERGE_MAX)
    text: StrictStr = Field(description=_TEXT_DESCRIPTION)
    classification: Classification


class RemovedRequirement(BaseModel):
    """A Requirement that left the active list: `deleted` by a person (Story 2.6)."""

    id: str
    status: RequirementStatus
    version: int = Field(ge=1)


class SplitResult(BaseModel):
    """The two Requirements a split made, in the order of the parts."""

    items: list[Requirement]


class ConfirmAllResult(BaseModel):
    """How many Requirements **Confirm all** confirmed (those not confirmed already)."""

    count: int = Field(ge=0)


class Passage(BaseModel):
    """A cited Source passage in its surrounding text (Story 2.5 Part B). `text` is the
    cited span exactly; `before` and `after` hold up to 300 code points of context each,
    cut at whitespace, with `…` on a side that was cut (none at the start or end of the
    text). `label` is `S<n> · <file name>`, as in a Requirement's evidence."""

    passage_id: str
    source_id: str
    source_version: int = Field(ge=1)
    filename: str
    label: str
    before: str
    text: str
    after: str
