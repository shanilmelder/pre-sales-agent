"""Actuals import rules (Story 10.2; FR-49). Pure, no I/O.

A file of Actuals has one row per Baseline line, under a header row naming the template's
columns (`COLUMNS`, matched without regard to case or spacing). The worker job reads the
file's cells (in the parse sandbox) and keeps them raw, as strings by column with the sheet
row number (`table_rows`). Each preview and the apply read those raw rows again
(`read_row`) and check them with the manual-entry rules (`domain.actuals`) against the state
of the moment, so no new Actual rule lives here: only how a cell becomes a field.

- A row whose Actual fields are all blank is skipped. A row with Actual fields and no Line ID
  is invalid ("line ID missing"): Unplanned work is entered by hand.
- Kind is blank (final), `Final` or `Milestone`. The variance cause is a cause's value or
  label. Failed Assumptions are `A{n}` labels of the Baseline version's register (its
  `position`), comma-separated. Cost is in major units, converted with the currency's
  minor-unit exponent (ISO 4217).
- Each problem reads "Row 7: line ID not in Baseline v3".
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.actuals.domain.actuals import (
    CAUSE_LABELS,
    CAUSE_REQUIRED,
    FAILED_ASSUMPTIONS_MAX,
    NOTE_REQUIRED,
    REASON_MAX,
    ActualKind,
    VarianceCause,
)

IMPORT_SUBJECT_TYPE = "actuals.import"
MAX_ROWS = 2000
"""The most data rows an import may hold (a Baseline has far fewer lines)."""
MAX_COLUMNS = 40
HEADER_SEARCH_ROWS = 10
"""The header row is looked for among the first rows only."""
CELL_MAX = 4000
"""Longer cell text is cut; the manual-entry rules then reject it as too long."""
IMPORT_EXTENSIONS: dict[str, str] = {".xlsx": "xlsx", ".csv": "csv"}
"""The import allowlist: extension to `file_kind`."""


class ImportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARSED = "parsed"
    FAILED = "failed"
    APPLIED = "applied"


IN_PROGRESS = (ImportStatus.QUEUED.value, ImportStatus.RUNNING.value)


class ImportErrorCode(StrEnum):
    UNREADABLE = "unreadable"
    """Corrupt, encrypted, or not a workbook or CSV the reader understands."""
    TIMEOUT = "timeout"
    """Reading ran past its time limit on the job's final attempt."""
    TOO_LARGE = "too_large"
    """More cells than the reader hands back."""
    MISSING_COLUMNS = "missing_columns"
    """No header row with the Line ID and Actual h columns."""
    TOO_MANY_ROWS = "too_many_rows"
    """More than `MAX_ROWS` data rows."""


ERROR_MESSAGES: dict[ImportErrorCode, str] = {
    ImportErrorCode.UNREADABLE: "The file couldn't be read. Save it again as .xlsx or .csv.",
    ImportErrorCode.TIMEOUT: "Reading the file took too long.",
    ImportErrorCode.TOO_LARGE: "The file has too many cells to read.",
    ImportErrorCode.MISSING_COLUMNS: (
        "No Line ID and Actual h columns were found. Start from the template."
    ),
    ImportErrorCode.TOO_MANY_ROWS: f"The file has more than {MAX_ROWS:,} rows.",
}


class ImportReadError(Exception):
    """The cells can't be turned into import rows. `code` says why."""

    def __init__(self, code: ImportErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    header: str
    actual: bool
    """An Actual field: a row with all of these blank is skipped."""


COLUMNS: tuple[Column, ...] = (
    Column("line_id", "Line ID", actual=False),
    Column("line", "Line", actual=False),
    Column("integration_type", "Integration Type", actual=False),
    Column("work_package", "Work Package", actual=False),
    Column("estimate_hours", "Estimate h", actual=False),
    Column("kind", "Kind", actual=True),
    Column("milestone_label", "Milestone label", actual=True),
    Column("actual_hours", "Actual h", actual=True),
    Column("duration_days", "Duration days", actual=True),
    Column("cost", "Cost", actual=True),
    Column("currency", "Currency", actual=True),
    Column("variance_cause", "Variance cause", actual=True),
    Column("failed_assumptions", "Failed Assumptions", actual=True),
    Column("note", "Note", actual=True),
    Column("correction_reason", "Correction reason", actual=True),
)
REQUIRED_KEYS = frozenset({"line_id", "actual_hours"})
ACTUAL_KEYS = frozenset(c.key for c in COLUMNS if c.actual)
_BY_HEADER = {re.sub(r"\s+", " ", c.header.strip().lower()): c.key for c in COLUMNS}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def cell_text(value: Any) -> str:
    """A cell as text: numbers without a needless `.0` ("41", "41.5"), booleans as TRUE or
    FALSE, other values trimmed; "" for an empty cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN, infinities
            return str(value)
        if value.is_integer():
            return str(int(value))
        # 15 significant digits: a formula's 41.300000000000004 reads as 41.3.
        return format(value, ".15g")
    return str(value).strip()[:CELL_MAX]


def header_map(cells: Sequence[Any]) -> dict[int, str]:
    """The template columns this row names, by cell index (the first of a repeated header
    wins)."""
    found: dict[int, str] = {}
    for index, cell in enumerate(cells[:MAX_COLUMNS]):
        key = _BY_HEADER.get(_norm(cell_text(cell)))
        if key is not None and key not in found.values():
            found[index] = key
    return found


def table_rows(table: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    """The import rows of a read sheet, `[row number, [cells]]` per row: after the header row
    (the first of the first `HEADER_SEARCH_ROWS` rows naming Line ID and Actual h), each row
    with any non-empty template cell as `{"row": n, "values": {key: text}}`. Raises
    `ImportReadError`."""
    header: dict[int, str] | None = None
    header_at = 0
    for position, entry in enumerate(table[:HEADER_SEARCH_ROWS]):
        found = header_map(entry[1])
        if REQUIRED_KEYS <= set(found.values()):
            header, header_at = found, position
            break
    if header is None:
        raise ImportReadError(ImportErrorCode.MISSING_COLUMNS)
    rows: list[dict[str, Any]] = []
    for number, cells in table[header_at + 1 :]:
        values = {
            key: text
            for index, key in header.items()
            if index < len(cells) and (text := cell_text(cells[index]))
        }
        if not values:
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportReadError(ImportErrorCode.TOO_MANY_ROWS)
        rows.append({"row": int(number), "values": values})
    return rows


def is_blank(values: Mapping[str, str]) -> bool:
    """True when every Actual field of the row is empty (the row is skipped)."""
    return not any(values.get(key, "").strip() for key in ACTUAL_KEYS)


# --- reading one row ------------------------------------------------------------------------

ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG",
        "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
    }
)  # fmt: skip
THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})
FOUR_DECIMAL_CURRENCIES = frozenset({"CLF", "UYW"})


def currency_exponent(currency: str | None) -> int:
    """The ISO 4217 minor-unit exponent: 0 for JPY, 3 for BHD, 2 for EUR and unknown codes
    (the same table the web's cost formatter gets from `Intl`)."""
    code = (currency or "").upper()
    if code in ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in THREE_DECIMAL_CURRENCIES:
        return 3
    if code in FOUR_DECIMAL_CURRENCIES:
        return 4
    return 2


LINE_MISSING = "line ID missing"
LINE_UNKNOWN = "line ID not in Baseline v{version}"
KIND_UNKNOWN = "kind must be Final or Milestone"
HOURS_MISSING = "actual hours missing"
NOT_A_NUMBER = "{label} must be a number"
CAUSE_UNKNOWN = "variance cause must be one of: {causes}"
ASSUMPTION_UNKNOWN = "{label} isn't in the Baseline v{version} Assumptions Register"
ASSUMPTION_LABEL = "failed Assumptions are A-numbers such as A1, A3"
COST_PRECISION = "cost has more decimal places than {currency} allows"
ASSUMPTIONS_TOO_MANY = f"at most {FAILED_ASSUMPTIONS_MAX} failed Assumptions per row"
REASON_TOO_LONG = f"correction reason is longer than {REASON_MAX:,} characters"
REASON_MISSING = "correction reason missing"
CAUSE_MISSING = "variance cause missing for a final Actual"
DUPLICATE_ROW_LINE = "this line appears in more than one row"

_ASSUMPTION_RE = re.compile(r"^a(\d{1,6})$", re.IGNORECASE)


def row_message(row: int, text: str) -> str:
    """E.g. "Row 7: line ID not in Baseline v3"."""
    return f"Row {row}: {text}"


def rule_text(field_name: str, message: str) -> str:
    """A manual-entry rule's sentence as a row problem: the known ones in short words, the
    rest as given, lower-cased and without the final stop."""
    if message == CAUSE_REQUIRED:
        return CAUSE_MISSING
    if message == NOTE_REQUIRED:
        return "a variance cause of Other needs a note"
    if field_name == "reason":
        return REASON_MISSING
    if field_name == "line_id" and message.startswith("Each line"):
        return DUPLICATE_ROW_LINE
    text = message.rstrip(".")
    if len(text) > 1 and text[1].isupper():  # an acronym such as ISO stays as it is
        return text
    return text[:1].lower() + text[1:]


_GROUPED_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_DECIMAL_COMMA_RE = re.compile(r"^-?\d*,\d+$")


def _decimal(text: str) -> Decimal | None:
    """A number as typed. A `,` is a thousands separator only in 3-digit groups ("1,250.50");
    a single `,` with no `.` is otherwise a decimal comma ("41,5" is 41.5). None when it isn't
    a number."""
    cleaned = text.replace(" ", "")
    if _GROUPED_RE.match(cleaned):
        cleaned = cleaned.replace(",", "")
    elif _DECIMAL_COMMA_RE.match(cleaned):
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _cause(text: str) -> VarianceCause | str | None:
    """The cause named by value or label; None when blank; the text back when unknown."""
    if not text.strip():
        return None
    wanted = _norm(text).replace("_", " ")
    for cause in VarianceCause:
        if wanted in {cause.value.replace("_", " "), _norm(CAUSE_LABELS[cause])}:
            return cause
    return text


@dataclass(frozen=True, slots=True)
class RowEntry:
    """A row read into an Actual's fields (not yet checked against the manual-entry rules)."""

    row: int
    line_id: UUID
    kind: ActualKind
    effort_hours: Decimal
    milestone_label: str | None = None
    duration_days: Decimal | None = None
    cost_minor: int | None = None
    currency: str | None = None
    variance_cause: VarianceCause | None = None
    failed_assumption_ids: list[UUID] = field(default_factory=list)
    note: str | None = None
    correction_reason: str | None = None


def read_row(
    row: int,
    values: Mapping[str, str],
    *,
    baseline_version: int,
    line_ids: Collection[UUID],
    assumptions: Mapping[int, UUID],
) -> tuple[RowEntry | None, list[str]]:
    """One raw row as an Actual's fields, or the reasons it can't be (each "Row N: ...").
    `assumptions` maps register positions (`A{n}`) to Assumption ids."""
    problems: list[str] = []

    def problem(text: str) -> None:
        problems.append(row_message(row, text))

    def get(key: str) -> str:
        return values.get(key, "").strip()

    line_id: UUID | None = None
    raw_line = get("line_id")
    if not raw_line:
        problem(LINE_MISSING)
    else:
        try:
            line_id = UUID(raw_line)
        except ValueError:
            line_id = None
        if line_id is None or line_id not in line_ids:
            problem(LINE_UNKNOWN.format(version=baseline_version))
            line_id = None

    kind = ActualKind.FINAL
    raw_kind = _norm(get("kind"))
    if raw_kind:
        if raw_kind in {k.value for k in ActualKind}:
            kind = ActualKind(raw_kind)
        else:
            problem(KIND_UNKNOWN)

    effort: Decimal | None = None
    raw_hours = get("actual_hours")
    if not raw_hours:
        problem(HOURS_MISSING)
    elif (effort := _decimal(raw_hours)) is None:
        problem(NOT_A_NUMBER.format(label="actual hours"))

    duration: Decimal | None = None
    if raw := get("duration_days"):
        duration = _decimal(raw)
        if duration is None:
            problem(NOT_A_NUMBER.format(label="duration days"))

    currency = get("currency").upper() or None
    cost_minor: int | None = None
    if raw := get("cost"):
        amount = _decimal(raw)
        if amount is None:
            problem(NOT_A_NUMBER.format(label="cost"))
        else:
            scaled = amount.scaleb(currency_exponent(currency))
            if scaled != scaled.to_integral_value():
                problem(COST_PRECISION.format(currency=currency or "the currency"))
            else:
                cost_minor = int(scaled)

    cause = _cause(get("variance_cause"))
    if cause is not None and not isinstance(cause, VarianceCause):  # a StrEnum is a str too
        problem(CAUSE_UNKNOWN.format(causes=", ".join(CAUSE_LABELS.values())))
        cause = None

    failed: list[UUID] = []
    if raw := get("failed_assumptions"):
        for label in (part.strip() for part in re.split(r"[,;]", raw)):
            if not label:
                continue
            match = _ASSUMPTION_RE.match(label)
            if match is None:
                problem(ASSUMPTION_LABEL)
                break
            found = assumptions.get(int(match.group(1)))
            if found is None:
                problem(ASSUMPTION_UNKNOWN.format(label=label.upper(), version=baseline_version))
                break
            if found not in failed:
                failed.append(found)
        if len(failed) > FAILED_ASSUMPTIONS_MAX:
            problem(ASSUMPTIONS_TOO_MANY)

    if len(get("correction_reason")) > REASON_MAX:
        problem(REASON_TOO_LONG)

    if problems or line_id is None or effort is None:
        return None, problems
    return (
        RowEntry(
            row=row,
            line_id=line_id,
            kind=kind,
            effort_hours=effort,
            milestone_label=get("milestone_label") or None,
            duration_days=duration,
            cost_minor=cost_minor,
            currency=currency,
            variance_cause=cause,
            failed_assumption_ids=failed,
            note=get("note") or None,
            correction_reason=get("correction_reason") or None,
        ),
        [],
    )


def duplicate_message(applied_at: datetime) -> str:
    """E.g. "This file was already imported on 14 Oct"."""
    return f"This file was already imported on {applied_at.day} {applied_at:%b}"
