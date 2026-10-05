"""What an Estimate export contains (Story 8.8, demo slice). Pure: no DB, no file format.

`build_export` turns the read models the tabs use (`EstimateVersion` and the Opportunity's
Gaps) into an `ExportDocument`: a header and three tables (Estimate, Assumptions, Clarification
Questions). The `.xlsx` and `.docx` renderers only lay this out, so both files carry the same
content. Every number is copied from the read model; nothing here adds hours up.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from app.modules.estimates.application.models import Assumption, EstimateVersion, Totals
from app.modules.estimates.domain.estimates import Section
from app.modules.gaps.application.public import Gap

DRAFT_LABEL = "Draft — not submitted"
NOT_ACCEPTED = "Not accepted"
UNALLOCATED = "Unallocated contingency"
NONE_ROW = "None"
SLUG_MAX = 60
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

SECTION_LABELS: dict[Section, str] = {
    Section.FUNCTIONAL: "Functional",
    Section.INTEGRATION: "Integration",
    Section.DATA: "Data",
    Section.SECURITY: "Security",
    Section.NON_FUNCTIONAL: "Non-functional",
    Section.COMMERCIAL: "Commercial",
}


class ExportFormat(StrEnum):
    XLSX = "xlsx"
    DOCX = "docx"


MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

Cell = str | float | int | None
RowKind = Literal["group", "item", "subtotal", "total"]
"""`group`: a heading row (a section, or Conditions/Contingencies); `item`: a line, an
Assumption or a question; `subtotal` and `total`: server-calculated sums."""


@dataclass(frozen=True, slots=True)
class Row:
    kind: RowKind
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Table:
    """One sheet (xlsx) or section (docx). `number_columns`: the indexes of columns holding
    hours or percentages, right-aligned."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    number_columns: frozenset[int]


@dataclass(frozen=True, slots=True)
class ExportDocument:
    header: tuple[str, ...]
    tables: tuple[Table, ...]


ESTIMATE_COLUMNS = (
    "Section",
    "Line",
    "Basis",
    "Engineer (%)",
    "PM (%)",
    "QA (%)",
    "Effort (h)",
    "Contingency (h)",
    "Total (h)",
)
ASSUMPTION_COLUMNS = (
    "Kind",
    "Wording",
    "Hours",
    "Linked line",
    "Origin Gap",
    "Accepted",
    "Carried",
)
QUESTION_COLUMNS = ("Gap", "Impact", "Topic", "Question", "Question status", "Gap status")
QUESTION_STATUS_LABELS = {"drafted": "Draft", "approved": "Approved"}
"""The exported questions' statuses (Story 4.5); superseded questions are left out."""


_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str) -> str:
    """`text` without the control characters XML can't hold (tab, newline and carriage return
    stay), so neither renderer fails on them."""
    return _XML_ILLEGAL.sub("", text)


def slug(text: str) -> str:
    """An ASCII file-name slug: accents folded, lower case, runs of anything else as one
    `-`; `opportunity` when nothing is left."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return cleaned[:SLUG_MAX].strip("-") or "opportunity"


def file_name(opportunity_title: str, version: int, export_format: ExportFormat) -> str:
    """`{opportunity-slug}-estimate-v{n}.{ext}`."""
    return f"{slug(opportunity_title)}-estimate-v{version}.{export_format.value}"


def export_time(at: datetime) -> str:
    """`2026-10-05 14:32 UTC` (`at` must be timezone-aware)."""
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def register_date(at: datetime) -> str:
    """`5 Oct 2026` (UTC), as the Register shows it."""
    utc = at.astimezone(UTC)
    return f"{utc.day} {MONTHS[utc.month - 1]} {utc.year}"


def accepted_label(assumption: Assumption) -> str:
    if assumption.accepted_at is None:
        return NOT_ACCEPTED
    name = "someone" if assumption.accepted_by is None else assumption.accepted_by.name
    return f"Accepted by {name}, {register_date(assumption.accepted_at)}"


def carried_label(assumption: Assumption) -> str | None:
    v = assumption.carried_from_version
    return None if v is None else f"Carried from v{v}"


def _sums(label: str, totals: Totals, kind: RowKind) -> Row:
    return Row(
        kind,
        (
            label,
            None,
            None,
            None,
            None,
            None,
            totals.effort_hours,
            totals.contingency_hours,
            totals.total_hours,
        ),
    )


def _estimate_table(version: EstimateVersion) -> Table:
    rows: list[Row] = []
    for section in version.sections:
        label = SECTION_LABELS.get(section.section, section.section.value)
        rows.append(Row("group", (label, None, None, None, None, None, None, None, None)))
        for line in section.lines:
            rows.append(
                Row(
                    "item",
                    (
                        label,
                        line.title,
                        line.basis,
                        line.role_mix.engineer,
                        line.role_mix.project_manager,
                        line.role_mix.qa,
                        line.effort_hours,
                        line.contingency_hours,
                        line.total_hours,
                    ),
                )
            )
        rows.append(_sums(f"{label} subtotal", section.subtotal, "subtotal"))
    if version.unallocated_contingency_hours > 0:
        hours = version.unallocated_contingency_hours
        rows.append(Row("item", (UNALLOCATED, None, None, None, None, None, None, hours, hours)))
    rows.append(_sums("Total", version.totals, "total"))
    return Table("Estimate", ESTIMATE_COLUMNS, tuple(rows), frozenset({3, 4, 5, 6, 7, 8}))


def _assumption_row(assumption: Assumption) -> Row:
    contingency = assumption.kind.value == "contingency"
    line: str | None = None
    if contingency:
        line = UNALLOCATED if assumption.line is None else assumption.line.title
    return Row(
        "item",
        (
            "Contingency" if contingency else "Condition",
            assumption.wording,
            assumption.amount_hours,
            line,
            assumption.origin.title,
            accepted_label(assumption),
            carried_label(assumption),
        ),
    )


def _assumptions_table(version: EstimateVersion) -> Table:
    rows: list[Row] = []
    groups = (
        ("Conditions", version.assumptions.conditions),
        ("Contingencies", version.assumptions.contingencies),
    )
    for title, items in groups:
        rows.append(Row("group", (title, None, None, None, None, None, None)))
        if not items:
            rows.append(Row("item", (NONE_ROW, None, None, None, None, None, None)))
        rows.extend(_assumption_row(a) for a in items)
    return Table("Assumptions", ASSUMPTION_COLUMNS, tuple(rows), frozenset({2}))


def _questions_table(gaps: Sequence[Gap]) -> Table:
    rows = [
        Row(
            "item",
            (
                gap.title,
                gap.impact.value.capitalize(),
                gap.question.topic,
                gap.question.text,
                QUESTION_STATUS_LABELS[gap.question.status.value],
                gap.status.value.capitalize(),
            ),
        )
        for gap in gaps
        if gap.question is not None
        and gap.question.status.value in QUESTION_STATUS_LABELS
        and gap.status.value in ("open", "converted")
    ]
    if not rows:
        rows = [Row("item", (NONE_ROW, None, None, None, None, None))]
    return Table("Clarification Questions", QUESTION_COLUMNS, tuple(rows), frozenset())


def build_export(
    *,
    opportunity_title: str,
    version: EstimateVersion,
    gaps: Sequence[Gap],
    exported_at: datetime,
) -> ExportDocument:
    """The export of a draft Estimate Version: header, Estimate, Assumptions Register and
    Clarification Questions."""
    return ExportDocument(
        header=(
            opportunity_title,
            f"Estimate v{version.version} · {DRAFT_LABEL}",
            f"Exported {export_time(exported_at)}",
        ),
        tables=(
            _estimate_table(version),
            _assumptions_table(version),
            _questions_table(gaps),
        ),
    )
