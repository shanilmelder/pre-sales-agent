"""Actuals read models and commands (Story 10.1). Hours and percents are floats to 0.1, as
the Estimate's; variance comes from the server, never the browser."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from app.modules.actuals.domain.actuals import (
    FAILED_ASSUMPTIONS_MAX,
    ActualKind,
    VarianceCause,
    VarianceDirection,
)

BATCH_MAX = 500


class CatalogueRef(BaseModel):
    """An Integration Type or Work Package of the catalogue."""

    id: str
    kind: Literal["integration_type", "work_package"]
    name: str


class VarianceView(BaseModel):
    """Actual minus estimate (server-calculated): hours, percent of the estimate (null when
    the estimate is 0, as for Unplanned work), the direction, and the signed label shown,
    e.g. "+5.0 h (13.9%)", with its words, e.g. "Over estimate"."""

    hours: float
    percent: float | None
    direction: VarianceDirection
    label: str
    direction_label: str


class FailedAssumption(BaseModel):
    """A failed Assumption an Actual names, at the version it was named at, with its kind and
    wording from the Actual's Baseline version register."""

    assumption_id: str
    version: int
    kind: str
    wording: str


class ActualVersionView(BaseModel):
    """One version of an Actual (the Inspector's history). `correction_reason` is null for the
    first version."""

    id: str
    version: int
    kind: ActualKind
    milestone_label: str | None
    effort_hours: float
    duration_days: float | None
    cost_minor: int | None
    currency: str | None
    variance_cause: VarianceCause | None
    note: str | None
    failed_assumptions: list[FailedAssumption]
    correction_reason: str | None
    recorded_by_name: str
    recorded_at: datetime


class ActualView(ActualVersionView):
    """An Actual's current version, with what it is recorded against: the Estimate Version
    (id and number), the line (null for Unplanned work), the Integration Types and Work
    Package, its variance (`cost_variance` stays null until Estimate lines carry a cost) and
    its earlier versions, newest first."""

    group_id: str
    line_id: str | None
    estimate_version_id: str
    estimate_version: int
    integration_types: list[CatalogueRef]
    work_package: CatalogueRef | None
    variance: VarianceView
    cost_variance: None = None
    history: list[ActualVersionView]


class ActualsLine(BaseModel):
    """A Baseline line, labelled "L{n}" in grid order, with its estimate, the Integration Types
    of its Requirements and its current Actual (null: "Not recorded", left out of the
    variance)."""

    line_id: str
    label: str
    title: str
    section: str
    estimate_hours: float
    integration_types: list[CatalogueRef]
    actual: ActualView | None
    variance: VarianceView | None
    cost_variance: None = None


class ActualsTotals(BaseModel):
    """The recorded lines and Unplanned work summed: estimate (Unplanned counts 0) and actual
    hours and their variance (null with nothing recorded)."""

    estimate_hours: float
    actual_hours: float
    variance: VarianceView | None
    recorded_line_count: int
    line_count: int
    unplanned_count: int


class ActualsBaseline(BaseModel):
    version_id: str
    version: int
    set_at: datetime


class VersionMismatch(BaseModel):
    """Story 10.1: Actuals recorded against an earlier Baseline version, which stay tied to it:
    e.g. "Actuals recorded against v3; the current Baseline is v5"."""

    recorded_versions: list[int]
    baseline_version: int
    actual_count: int
    message: str


class DeliveryView(BaseModel):
    closed_at: datetime
    closed_by_name: str
    estimate_version: int


class AssumptionOption(BaseModel):
    """An Assumption of the Baseline version's register a failed-Assumption reference may
    name."""

    id: str
    kind: str
    wording: str
    version: int
    line_id: str | None


class CauseOption(BaseModel):
    value: VarianceCause
    label: str
    unplanned: bool


class ActualsView(BaseModel):
    """The Actuals tab. `baseline` null: no Baseline yet (nothing else is filled).
    `open_line_count` lines have no final Actual; `close_blocked_reason` says so (e.g. "4
    lines have no final Actual") or that delivery is closed. `can_record` and `can_close`
    are the caller's (delivery managers only). `row_version` is the tab's ETag for Save
    Actuals and Close delivery."""

    baseline: ActualsBaseline | None
    lines: list[ActualsLine]
    unplanned: list[ActualView]
    totals: ActualsTotals
    assumptions: list[AssumptionOption]
    causes: list[CauseOption]
    open_line_count: int
    close_blocked_reason: str | None
    can_record: bool
    can_close: bool
    delivery: DeliveryView | None
    version_mismatch: VersionMismatch | None
    row_version: int


class ActualFields(BaseModel):
    """What a person enters for an Actual. `effort_hours` (person-hours) and `duration_days`
    (working days) take one decimal place; cost is whole minor units with an ISO-4217
    `currency`, both or neither. A final Actual whose effort differs from the line's estimate
    needs `variance_cause`; `other` also needs `note`. `failed_assumption_ids` must be in the
    Actual's Baseline version register. Unplanned work needs `integration_type_id` or
    `work_package_id` and a cause of `scope_change`, `unknown_requirement` or `other`; a
    line's Actual takes its Integration Types from the line's Requirements instead."""

    model_config = ConfigDict(extra="forbid")

    kind: ActualKind = ActualKind.FINAL
    milestone_label: StrictStr | None = None
    effort_hours: StrictInt | StrictFloat
    duration_days: StrictInt | StrictFloat | None = None
    cost_minor: StrictInt | None = None
    currency: StrictStr | None = None
    variance_cause: VarianceCause | None = None
    note: StrictStr | None = None
    failed_assumption_ids: list[UUID] = Field(
        default_factory=list, max_length=FAILED_ASSUMPTIONS_MAX
    )
    integration_type_id: UUID | None = None
    work_package_id: UUID | None = None


class ActualInput(ActualFields):
    """One entry of **Save Actuals**: a Baseline line's Actual (`line_id`), or Unplanned work
    (no `line_id`). A line that already has an Actual is corrected (a new version); Unplanned
    work is corrected by naming its current `actual_id`. A stated `actual_id` that is no longer
    current is 412."""

    line_id: UUID | None = None
    actual_id: UUID | None = None


class ActualsSave(BaseModel):
    """**Save Actuals**: the entries, saved together; `reason` (1 to 1,000 characters) is
    required when any entry corrects an Actual."""

    model_config = ConfigDict(extra="forbid")

    items: list[ActualInput] = Field(min_length=1, max_length=BATCH_MAX)
    reason: StrictStr | None = None


class ActualCorrection(ActualFields):
    """A correction of one Actual (a new version), with why: `reason`, 1 to 1,000
    characters."""

    reason: StrictStr


class SavedActuals(BaseModel):
    """What **Save Actuals** wrote: how many Actuals were recorded and corrected, and the tab
    as it is now."""

    recorded: int
    corrected: int
    view: ActualsView


# --- imports (Story 10.2) -------------------------------------------------------------------

IMPORT_EXCLUSIONS_MAX = 2000


class ActualsTemplate(BaseModel):
    """The Actuals import template of the Baseline version (`.xlsx`, one row per line): a
    short-lived signed link (`url`, relative to the API origin) to the file, downloaded as
    `file_name`, until `expires_at`."""

    url: str
    file_name: str
    expires_at: datetime
    line_count: int


class ImportRowView(BaseModel):
    """One row of an import's preview, checked now with the manual-entry rules. `status`:
    `create` (the line has no Actual yet), `correct` (it has one: a new version, which needs
    the row's Correction reason or the batch reason; `reason_missing` says the row has none of
    its own), `invalid` (each problem in `problems`, e.g. "Row 7: line ID not in Baseline v3")
    or `skipped` (every Actual field blank). `row` is the sheet's row number."""

    row: int
    status: Literal["create", "correct", "invalid", "skipped"]
    line_id: str | None
    line_label: str | None
    line_title: str | None
    estimate_hours: float | None
    kind: ActualKind | None
    effort_hours: float | None
    variance_cause: VarianceCause | None
    correction_reason: str | None
    reason_missing: bool
    problems: list[str]


class ImportCounts(BaseModel):
    create: int
    correct: int
    invalid: int
    skipped: int


class AppliedCounts(BaseModel):
    """What applying wrote: rows created and corrected, excluded by the person, skipped as
    blank."""

    created: int
    corrected: int
    excluded: int
    skipped: int


class ActualsImportView(BaseModel):
    """An Actuals import. `status`: `queued` and `running` while the worker reads the file,
    `parsed` (the preview: `rows` and `counts`), `failed` (`error_code` and `error_message`;
    **Retry**), `applied` (`applied_at` and `applied`). `repeat_applied_at` and
    `repeat_message` ("This file was already imported on 14 Oct") are set when the same file
    was already applied here: Confirm then needs `confirm_repeat`. `row_version` is the
    Actuals tab's ETag the preview was checked against: Confirm's `If-Match`."""

    id: str
    filename: str
    size_bytes: int
    file_kind: Literal["xlsx", "csv"]
    status: Literal["queued", "running", "parsed", "failed", "applied"]
    error_code: str | None
    error_message: str | None
    uploaded_by_name: str
    created_at: datetime
    estimate_version: int | None
    rows: list[ImportRowView]
    counts: ImportCounts | None
    repeat_applied_at: datetime | None
    repeat_message: str | None
    applied_at: datetime | None
    applied: AppliedCounts | None
    row_version: int


class ActualsImportLatest(BaseModel):
    """The Opportunity's most recent import (null: none yet)."""

    latest: ActualsImportView | None


class ActualsImportApply(BaseModel):
    """**Confirm** an import's preview: `excluded_rows` (sheet row numbers) are left out;
    `reason` (1 to 1,000 characters) is the correction reason of every correcting row that
    has none of its own; `confirm_repeat` must be true when the same file was already
    applied."""

    model_config = ConfigDict(extra="forbid")

    excluded_rows: list[StrictInt] = Field(default_factory=list, max_length=IMPORT_EXCLUSIONS_MAX)
    reason: StrictStr | None = None
    confirm_repeat: bool = False


class AppliedImport(BaseModel):
    """The applied import, with the counts, and the Actuals tab as it is now."""

    imported: ActualsImportView
    actuals: ActualsView
