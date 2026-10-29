"""Fill an Actuals template downloaded from the app with plausible delivery figures.

Usage (from the repo root):

    cd backend
    uv run python ../demo-data/tools/fill_actuals.py <template.xlsx> <scenario> [out.xlsx]

<scenario> is one of: aldermoor, larkspur, elmbridge. Each scenario overruns the lines whose
Integration Type or Work Package matches its "story" (see PROFILES) and names the failed
Assumptions from the template's "Lists" sheet, so the Reports tab and the drill-down to the
failed Assumption (Stories 10.3, 10.4) have something to show. Every other line lands within
a few percent of its estimate. The output is a normal .xlsx you upload through
Actuals > Import from file.

Only openpyxl is needed (it is already in the backend venv).
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook


@dataclass(frozen=True)
class Overrun:
    match: tuple[str, ...]  # lower-case words looked for in Integration Type / Work Package
    factor: float  # actual = estimate * factor
    cause: str  # variance cause value
    assumption_kind: str  # "contingency" or "condition": which Assumptions to name as failed
    note: str


@dataclass(frozen=True)
class Profile:
    currency: str
    rate: int  # cost per hour
    seed: int
    overruns: tuple[Overrun, ...]
    underrun: tuple[str, ...]  # lines that come in under estimate


PROFILES = {
    "aldermoor": Profile(
        currency="GBP",
        rate=92,
        seed=11,
        overruns=(
            Overrun(
                ("epr", "fhir", "clinical"),
                1.41,
                "integration_complexity",
                "contingency",
                "EPR vendor's FHIR API lacked Appointment write-back; built an HL7 v2 bridge.",
            ),
            Overrun(
                ("testing", "assurance"),
                1.24,
                "customer_delay",
                "condition",
                "Clinical safety case sign-off slipped four weeks waiting for the Trust's CSO.",
            ),
        ),
        underrun=("training", "hypercare"),
    ),
    "larkspur": Profile(
        currency="EUR",
        rate=110,
        seed=23,
        overruns=(
            Overrun(
                ("policy", "migration", "data"),
                1.48,
                "unknown_requirement",
                "contingency",
                "Legacy policy system held 14 undocumented claim status codes to map.",
            ),
            Overrun(
                ("payment",),
                1.16,
                "customer_delay",
                "condition",
                "Bank's payment-file test environment arrived three weeks late.",
            ),
            Overrun(
                ("document", "correspondence"),
                1.12,
                "scope_change",
                "condition",
                "Larkspur added Welsh-language letter templates during delivery.",
            ),
        ),
        underrun=("identity", "sign-on"),
    ),
    "elmbridge": Profile(
        currency="GBP",
        rate=98,
        seed=37,
        overruns=(
            Overrun(
                ("wms",),
                1.52,
                "unknown_requirement",
                "contingency",
                "Tracing the 2009 WMS found 11 interfaces instead of the 6 assumed.",
            ),
            Overrun(
                ("mechanical", "installation"),
                1.25,
                "unknown_requirement",
                "contingency",
                "Core samples showed a thinner slab; extra base plates and anchoring.",
            ),
        ),
        underrun=("project management",),
    ),
}


def _lists(workbook) -> dict[str, list[str]]:
    """Failed Assumption labels by kind, read from the "Lists" sheet."""
    found: dict[str, list[str]] = {"contingency": [], "condition": []}
    if "Lists" not in workbook.sheetnames:
        return found
    in_assumptions = False
    for row in workbook["Lists"].iter_rows(values_only=True):
        first = (row[0] or "") if row else ""
        if first == "Failed Assumptions":
            in_assumptions = True
            continue
        if in_assumptions and first:
            kind = str(row[1] or "").lower()
            for key in found:
                if key in kind:
                    found[key].append(str(first))
    return found


def _header(sheet) -> tuple[int, dict[str, int]]:
    for row in sheet.iter_rows(min_row=1, max_row=10):
        names = {str(c.value).strip(): c.column for c in row if c.value}
        if "Line ID" in names and "Actual h" in names:
            return row[0].row, names
    sys.exit("No 'Line ID' / 'Actual h' header found: is this the downloaded template?")


def fill(template: Path, scenario: str, out: Path) -> None:
    profile = PROFILES[scenario]
    rng = random.Random(profile.seed)
    workbook = load_workbook(template)
    sheet = workbook["Actuals"] if "Actuals" in workbook.sheetnames else workbook.active
    labels = _lists(workbook)
    header_row, col = _header(sheet)
    used: set[str] = set()
    filled = 0

    for row in sheet.iter_rows(min_row=header_row + 1):
        def cell(name: str):
            return sheet.cell(row=row[0].row, column=col[name])

        if not cell("Line ID").value or cell("Estimate h").value in (None, ""):
            continue
        estimate = float(cell("Estimate h").value)
        text = " ".join(
            str(cell(n).value or "") for n in ("Integration Type", "Work Package") if n in col
        ).lower()
        overrun = next((o for o in profile.overruns if any(w in text for w in o.match)), None)

        if overrun:
            actual = estimate * overrun.factor
            cause, note = overrun.cause, overrun.note
            pool = [a for a in labels[overrun.assumption_kind] if a not in used]
            failed = pool[:1]
            used.update(failed)
        elif any(w in text for w in profile.underrun):
            actual = estimate * 0.86
            cause, note, failed = "estimation_error", "Fewer super-users needed hypercare.", []
        else:
            actual = estimate * rng.uniform(0.97, 1.04)
            cause, note, failed = "estimation_error", "", []

        actual = round(actual, 1)
        cell("Kind").value = "final"
        cell("Actual h").value = actual
        if "Duration days" in col:
            cell("Duration days").value = max(1, round(actual / 7.5 / 2))
        if "Cost" in col:
            cell("Cost").value = round(actual * profile.rate, 2)
            cell("Currency").value = profile.currency
        if round(actual, 1) != round(estimate, 1):
            cell("Variance cause").value = cause
        if failed and "Failed Assumptions" in col:
            cell("Failed Assumptions").value = ", ".join(failed)
        if note:
            cell("Note").value = note
        filled += 1

    workbook.save(out)
    print(f"filled {filled} lines -> {out}")
    if not any(labels.values()):
        print("note: no Assumptions in the Lists sheet, so no failed Assumptions were named")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[2] not in PROFILES:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    dest = Path(sys.argv[3]) if len(sys.argv) > 3 else src.with_name(f"{src.stem}-filled.xlsx")
    fill(src, sys.argv[2], dest)
