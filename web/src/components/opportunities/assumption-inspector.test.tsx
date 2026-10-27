import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AssumptionAcceptInput,
  AssumptionAcceptResult,
  AssumptionEditInput,
  EstimateItemEditResult,
  RiskEditInput,
} from "@/app/opportunities/actions";
import type { EstimateResult } from "@/app/opportunities/data";
import type {
  Assumption,
  EstimateLine,
  EstimateVersion,
  EstimateView,
  Risk,
} from "@/lib/estimates";
import { axeViolations } from "@/test/axe";

const loadEstimate = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<EstimateResult>>());
const acceptAssumption = vi.hoisted(() =>
  vi.fn<(input: AssumptionAcceptInput) => Promise<AssumptionAcceptResult>>(),
);
const editAssumption = vi.hoisted(() =>
  vi.fn<(input: AssumptionEditInput) => Promise<EstimateItemEditResult>>(),
);
const editRisk = vi.hoisted(() => vi.fn<(input: RiskEditInput) => Promise<EstimateItemEditResult>>());
vi.mock("@/app/opportunities/actions", () => ({
  loadEstimate,
  acceptAssumption,
  acceptAllAssumptions: vi.fn(),
  editAssumption,
  editRisk,
  editEstimateLine: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/estimate",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { EstimateSection } from "./estimate-grid";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const L1 = "00000000-0000-7000-8000-0000000000d2";
const L2 = "00000000-0000-7000-8000-0000000000d3";

function line(id: string, position: number, title: string): EstimateLine {
  return {
    id,
    position,
    section: "integration",
    title,
    basis: "[BASIS]",
    role_mix: { engineer: 60, project_manager: 20, qa: 20 },
    effort_hours: 10,
    contingency_hours: 0,
    total_hours: 10,
    role_hours: { engineer: 6, project_manager: 2, qa: 2 },
    requirements: [],
    row_version: 1,
    edited: false,
    edited_by_name: null,
    edited_at: null,
    edit_reason: null,
    edit_carried_from_version: null,
    conflicts: [],
  };
}

function assumption(
  n: number,
  kind: "condition" | "contingency",
  options: { accepted?: boolean; superseded?: boolean; unknown?: boolean; hours?: number } = {},
): Assumption {
  return {
    id: `00000000-0000-7000-8000-0000000000a${n}`,
    position: n,
    kind,
    wording: `[WORDING ${n}]`,
    amount_hours: kind === "contingency" ? (options.hours ?? 8) : null,
    line: kind === "contingency" ? { id: L1, title: "[LINE 1]" } : null,
    origin_kind: "gap",
    origin: {
      id: `00000000-0000-7000-8000-0000000000e${n}`,
      title: `[GAP ${n}]`,
      category: "integration_details",
      impact: "high",
      why_it_matters: options.unknown ? "Unknown to the customer: [WHY]" : `[WHY ${n}]`,
      status: options.superseded ? "superseded" : options.accepted ? "converted" : "open",
    },
    origin_superseded: options.superseded ?? false,
    origin_is_unknown: options.unknown ?? false,
    accepted_by: options.accepted ? { id: "u1", name: "[NAME]" } : null,
    accepted_at: options.accepted ? "2026-10-05T09:00:00Z" : null,
    row_version: options.accepted ? 2 : 1,
    carried_from_version: null,
  };
}

function risk(n: number, likelihood: Risk["likelihood"], impact: Risk["impact"]): Risk {
  return {
    id: `00000000-0000-7000-8000-0000000000b${n}`,
    position: n,
    description: `[RISK ${n}]`,
    likelihood,
    impact,
    origin_kind: "gap",
    origin: {
      id: `00000000-0000-7000-8000-0000000000f${n}`,
      title: `[RISK GAP ${n}]`,
      category: "data_volumes",
      impact: "medium",
      why_it_matters: "[WHY R]",
      status: "converted",
    },
    origin_superseded: false,
    row_version: 1,
    carried_from_version: null,
  };
}

function version(
  items: Assumption[],
  risks: Risk[] = [],
  overrides: Partial<EstimateVersion> = {},
): EstimateVersion {
  const accepted = items.filter((a) => a.accepted_at).length;
  const totals = {
    effort_hours: 20,
    contingency_hours: 8,
    total_hours: 28,
    role_hours: { engineer: 12, project_manager: 4, qa: 4 },
  };
  return {
    id: "00000000-0000-7000-8000-0000000000c1",
    version: 1,
    status: "draft",
    template_version: "demo-1",
    roles: ["engineer", "project_manager", "qa"],
    uncovered_count: 0,
    dropped_count: 0,
    row_version: 1,
    created_at: "2026-10-05T09:00:00Z",
    sections: [
      {
        section: "integration",
        lines: [line(L1, 1, "[LINE 1]"), line(L2, 2, "[LINE 2]")],
        subtotal: totals,
      },
    ],
    totals,
    proposal_status: "succeeded",
    assumptions: {
      conditions: items.filter((a) => a.kind === "condition"),
      contingencies: items.filter((a) => a.kind === "contingency"),
      contingency_hours: 8,
    },
    counts: { total: items.length, accepted, not_accepted: items.length - accepted },
    unconverted_gaps: [],
    unallocated_contingency_hours: 0,
    risks,
    uncarried_edit_count: 0,
    uncarried_edits_from_version: null,
    source: "assessments",
    source_run: 1,
    ...overrides,
  };
}

function view(v: EstimateVersion, may = true): EstimateView {
  return {
    version: v,
    draft: { status: "succeeded", error_code: null },
    can_start_draft: may,
    can_accept_assumptions: may,
    can_export: false,
    can_edit_lines: false,
    can_edit_assumptions: may,
    can_create_risks: may,
    can_edit_risks: may,
    assessment_running: false,
    blockers: { to_submit: [], to_baseline: [] },
    can_submit: false,
    can_request_review: false,
    can_create_version: false,
    baseline: null,
    is_current: true,
    can_set_baseline: false,
  };
}

function renderSection(initial: EstimateView) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <EstimateSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const register = () => screen.getByTestId("assumptions-register");
const row = (n: number) =>
  register().querySelector<HTMLElement>(`[data-assumption-id$="a${n}"]`) as HTMLElement;
const pane = () => screen.getByRole("complementary", { name: "Details" });

const TWO = [assumption(1, "condition", { accepted: true }), assumption(2, "contingency")];

beforeEach(() => {
  loadEstimate.mockReset();
  acceptAssumption.mockReset();
  editAssumption.mockReset();
  editRisk.mockReset();
});

describe("the Register rows (Story 8.5)", () => {
  it("show the ID chip, the wording, '{kind} · from Gap: {title}', the line and the status", async () => {
    const { container } = renderSection(view(version(TWO)));

    expect(within(row(1)).getByText("A1")).toBeTruthy();
    expect(within(row(2)).getByText("A2")).toBeTruthy();
    expect(within(row(1)).getByText("Condition ·")).toBeTruthy();
    expect(within(row(2)).getByText("Contingency · 8.0 h ·")).toBeTruthy();
    expect(within(row(2)).getByRole("button", { name: "from Gap: [GAP 2]" })).toBeTruthy();
    expect(within(row(2)).getByText("Line: [LINE 1]")).toBeTruthy();
    expect(within(register()).getByText("1 not accepted block submit")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("strike a superseded origin through with a 'superseded' label, and name an Unknown", () => {
    renderSection(
      view(
        version([
          assumption(1, "condition", { superseded: true }),
          assumption(2, "condition", { unknown: true }),
        ]),
      ),
    );

    const chip = within(row(1)).getByRole("button", { name: /from Gap: \[GAP 1\]/ });
    expect(chip.querySelector("s")?.textContent).toBe("[GAP 1]");
    expect(within(chip).getByText("(superseded)")).toBeTruthy();
    expect(within(row(2)).getByRole("button", { name: "from Unknown: [GAP 2]" })).toBeTruthy();
  });

  it("open the Assumption inspector on a click of the row, or Enter on it", async () => {
    const user = userEvent.setup();
    renderSection(view(version(TWO)));

    await user.click(within(row(2)).getByText("Line: [LINE 1]"));
    expect(within(pane()).getByText("Contingency · A2")).toBeTruthy();
    expect(within(pane()).getByRole("heading", { name: "[WORDING 2]" })).toBeTruthy();
    expect(row(2).hasAttribute("data-selected")).toBe(true);

    within(row(1)).getByRole("button", { name: "[WORDING 1]" }).focus();
    await user.keyboard("{Enter}");
    expect(within(pane()).getByText("Condition · A1")).toBeTruthy();
    expect(within(pane()).getByText("Accepted by [NAME] · 5 Oct 2026")).toBeTruthy();
    // The origin chip still opens the Gap.
    await user.click(within(row(1)).getByRole("button", { name: "from Gap: [GAP 1]" }));
    expect(within(pane()).getByRole("heading", { name: "[GAP 1]" })).toBeTruthy();
  });
});

describe("the Assumption inspector", () => {
  it("shows the origin card, Not accepted with Accept, and the Edit Assumption form", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(version(TWO)));
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));

    const p = pane();
    const card = p.querySelector("[data-origin-card]") as HTMLElement;
    expect(within(card).getByText("[GAP 2]")).toBeTruthy();
    expect(within(card).getByText("[WHY 2]")).toBeTruthy();
    expect(within(card).getByText("Status: Open")).toBeTruthy();
    expect(within(p).getByText("Not accepted")).toBeTruthy();
    expect(within(p).getByRole("button", { name: "Accept" })).toBeTruthy();
    const form = within(p).getByRole("form", { name: "Edit Assumption" });
    expect((within(form).getByRole("radio", { name: "Contingency" }) as HTMLInputElement).checked).toBe(
      true,
    );
    expect((within(form).getByLabelText("Hours") as HTMLInputElement).value).toBe("8.0");
    expect((within(form).getByLabelText("Line") as HTMLSelectElement).value).toBe(L1);
    expect(within(form).getByText("Saving clears the acceptance. Recorded in the Decision Trace.")).toBeTruthy();
    expect(within(form).getByRole("button", { name: "Save change" })).toHaveProperty("disabled", true);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("saves the hours with a reason and the grid refreshes from the server", async () => {
    const user = userEvent.setup();
    const edited = { ...assumption(2, "contingency", { hours: 10 }), row_version: 2 };
    const after = version([TWO[0], edited], [], {
      totals: { ...version(TWO).totals, contingency_hours: 10, total_hours: 30 },
    });
    editAssumption.mockResolvedValue({ kind: "ok", estimate: view(after) });
    renderSection(view(version(TWO)));
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));
    const form = within(pane()).getByRole("form", { name: "Edit Assumption" });

    const hoursField = within(form).getByLabelText("Hours");
    await user.clear(hoursField);
    await user.type(hoursField, "10");
    const save = within(form).getByRole("button", { name: "Save change" });
    expect(save).toHaveProperty("disabled", true); // no reason yet
    await user.type(within(form).getByLabelText("Reason for the change"), "Bigger spike");
    await user.click(save);

    expect(editAssumption).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      assumptionId: TWO[1].id,
      rowVersion: 1,
      kind: "contingency",
      wording: "[WORDING 2]",
      amountHours: 10,
      lineId: L1,
      reason: "Bigger spike",
    });
    await waitFor(() =>
      expect(screen.getByRole("table").querySelector("tr[data-totals]")?.textContent).toContain("30.0"),
    );
  });

  it("flips a Condition to a Contingency on a line, and back without hours or line", async () => {
    const user = userEvent.setup();
    editAssumption.mockResolvedValue({ kind: "ok", estimate: view(version(TWO)) });
    renderSection(view(version(TWO)));
    await user.click(within(row(1)).getByRole("button", { name: "[WORDING 1]" }));
    const form = within(pane()).getByRole("form", { name: "Edit Assumption" });
    expect(within(form).queryByLabelText("Hours")).toBeNull();

    await user.click(within(form).getByRole("radio", { name: "Contingency" }));
    const save = within(form).getByRole("button", { name: "Save change" });
    await user.type(within(form).getByLabelText("Reason for the change"), "Absorb it");
    expect(save).toHaveProperty("disabled", true); // hours are needed
    // The rule shows only once something is typed.
    expect(within(form).queryByText("A Contingency needs 0.5 to 1,000 hours.")).toBeNull();
    await user.type(within(form).getByLabelText("Hours"), "0.2");
    expect(within(form).getByText("A Contingency needs 0.5 to 1,000 hours.")).toBeTruthy();
    await user.clear(within(form).getByLabelText("Hours"));
    await user.type(within(form).getByLabelText("Hours"), "12");
    await user.selectOptions(within(form).getByLabelText("Line"), L2);
    await user.click(save);

    expect(editAssumption).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "contingency", amountHours: 12, lineId: L2, rowVersion: 2 }),
    );
  });

  it("on 412 shows who changed it with Reload, and saves nothing", async () => {
    const user = userEvent.setup();
    editAssumption.mockResolvedValue({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(version(TWO)) });
    renderSection(view(version(TWO)));
    await user.click(within(row(1)).getByRole("button", { name: "[WORDING 1]" }));
    const form = within(pane()).getByRole("form", { name: "Edit Assumption" });

    await user.type(within(form).getByLabelText("Wording"), " more");
    await user.type(within(form).getByLabelText("Reason for the change"), "Clarify");
    await user.click(within(form).getByRole("button", { name: "Save change" }));

    const alert = await within(pane()).findByRole("alert");
    expect(alert.textContent).toContain("Changed by [OTHER] since you opened it.");
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    expect(loadEstimate).toHaveBeenCalledWith(OPP_ID, null);
  });

  it("after a 412 with a reason typed, Reload takes the new values and row version", async () => {
    const user = userEvent.setup();
    editAssumption.mockResolvedValueOnce({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    const changed = { ...TWO[0], wording: "[WORDING 1 NEW]", row_version: 3 };
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(version([changed, TWO[1]])) });
    editAssumption.mockResolvedValueOnce({ kind: "ok", estimate: view(version([changed, TWO[1]])) });
    renderSection(view(version(TWO)));
    await user.click(within(row(1)).getByRole("button", { name: "[WORDING 1]" }));
    let form = within(pane()).getByRole("form", { name: "Edit Assumption" });
    await user.type(within(form).getByLabelText("Wording"), " more");
    await user.type(within(form).getByLabelText("Reason for the change"), "Clarify");
    await user.click(within(form).getByRole("button", { name: "Save change" }));
    const alert = await within(pane()).findByRole("alert");

    await user.click(within(alert).getByRole("button", { name: "Reload" }));

    form = within(pane()).getByRole("form", { name: "Edit Assumption" });
    await waitFor(() =>
      expect((within(form).getByLabelText("Wording") as HTMLTextAreaElement).value).toBe(
        "[WORDING 1 NEW]",
      ),
    );
    await user.type(within(form).getByLabelText("Wording"), " again");
    await user.click(within(form).getByRole("button", { name: "Save change" }));
    expect(editAssumption).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowVersion: 3, wording: "[WORDING 1 NEW] again", reason: "Clarify" }),
    );
  });

  it.each([
    [{ kind: "stale", changedBy: "[OTHER]" } as const, "Changed by [OTHER] since you opened it."],
    [{ kind: "gap-not-open" } as const, /Its Gap is no longer open/],
  ])("Accept in the inspector says why it failed and can be pressed again", async (result, text) => {
    const user = userEvent.setup();
    acceptAssumption.mockResolvedValue(result);
    renderSection(view(version(TWO)));
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));
    const accept = within(pane()).getByRole("button", { name: "Accept" });

    await user.click(accept);

    expect(await within(pane()).findByText(text)).toBeTruthy();
    expect(accept).toHaveProperty("disabled", false);
    expect(loadEstimate).not.toHaveBeenCalled();
  });

  it("Accept in the inspector accepts with If-Match and reads the Estimate again", async () => {
    const user = userEvent.setup();
    const accepted = assumption(2, "contingency", { accepted: true });
    acceptAssumption.mockResolvedValue({ kind: "ok", assumption: accepted });
    loadEstimate.mockResolvedValue({
      kind: "ok",
      estimate: view(version([TWO[0], accepted])),
    });
    renderSection(view(version(TWO)));
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));

    await user.click(within(pane()).getByRole("button", { name: "Accept" }));

    expect(acceptAssumption).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      assumptionId: TWO[1].id,
      rowVersion: 1,
    });
    expect(await within(pane()).findByText("Accepted by [NAME] · 5 Oct 2026")).toBeTruthy();
    expect(within(register()).getByText("All accepted")).toBeTruthy();
  });

  it("is read-only on a superseded version: no Accept, Accept all, Edit or Edit Risk", async () => {
    const user = userEvent.setup();
    renderSection(
      view(version(TWO, [risk(1, "high", "high")], { status: "superseded" })),
    );

    expect(within(register()).queryByRole("button", { name: /Accept/ })).toBeNull();
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));
    expect(within(pane()).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(pane()).queryByRole("form", { name: "Edit Assumption" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /\[RISK 1\]/ }));
    expect(within(pane()).getByText("Risk · R1")).toBeTruthy();
    expect(within(pane()).queryByRole("form", { name: "Edit Risk" })).toBeNull();
  });

  it("is read-only for sales representatives", async () => {
    const user = userEvent.setup();
    renderSection(view(version(TWO, [risk(1, "low", "low")]), false));
    await user.click(within(row(2)).getByRole("button", { name: "[WORDING 2]" }));
    expect(within(pane()).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(pane()).queryByRole("form", { name: "Edit Assumption" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /\[RISK 1\]/ }));
    expect(within(pane()).queryByRole("form", { name: "Edit Risk" })).toBeNull();
  });
});

describe("the Risks card", () => {
  it("a Risk edit answered 412 shows who changed it, with Reload", async () => {
    const user = userEvent.setup();
    editRisk.mockResolvedValue({ kind: "stale", message: "Changed by [OTHER] since you opened it." });
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(version(TWO, [risk(1, "low", "low")])) });
    renderSection(view(version(TWO, [risk(1, "low", "low")])));
    await user.click(screen.getByRole("button", { name: /\[RISK 1\]/ }));
    const form = within(pane()).getByRole("form", { name: "Edit Risk" });
    await user.selectOptions(within(form).getByLabelText("Impact"), "high");
    await user.type(within(form).getByLabelText("Reason for the change"), "Spike");
    await user.click(within(form).getByRole("button", { name: "Save change" }));

    const alert = await within(pane()).findByRole("alert");
    expect(alert.textContent).toContain("Changed by [OTHER] since you opened it.");
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    expect(loadEstimate).toHaveBeenCalledWith(OPP_ID, null);
  });

  it("lists R{n}, likelihood, impact and the Risk with its origin, in the API's order", async () => {
    const { container } = renderSection(
      view(version(TWO, [risk(2, "high", "high"), risk(1, "low", "medium")])),
    );

    const card = screen.getByTestId("risks-card");
    expect(within(card).getByRole("heading", { name: "Risks · 2" })).toBeTruthy();
    const rows = within(card).getAllByRole("row");
    expect(rows.map((r) => r.querySelector("[data-risk-row] span")?.textContent)).toEqual([
      "R2",
      "R1",
    ]);
    const high = rows[0].querySelector('[data-level-kind="impact"]') as HTMLElement;
    expect(high.textContent).toBe("High");
    expect(high.getAttribute("data-tone")).toBe("blocker");
    expect(high.querySelector("svg")).toBeTruthy();
    expect(within(rows[1]).getByText("from Gap: [RISK GAP 1]")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when there are none", () => {
    renderSection(view(version(TWO)));
    expect(
      within(screen.getByTestId("risks-card")).getByText(
        "No Risks yet. Convert a Gap to a Risk from the Gaps tab.",
      ),
    ).toBeTruthy();
  });

  it("opens a Risk in the inspector and edits its impact with a reason", async () => {
    const user = userEvent.setup();
    const edited = { ...risk(1, "low", "high"), row_version: 2 };
    editRisk.mockResolvedValue({ kind: "ok", estimate: view(version(TWO, [edited])) });
    const { container } = renderSection(view(version(TWO, [risk(1, "low", "medium")])));

    await user.click(screen.getByRole("button", { name: /\[RISK 1\]/ }));
    const p = pane();
    expect(within(p).getByText("Risk · R1")).toBeTruthy();
    expect(within(p.querySelector("[data-origin-card]") as HTMLElement).getByText("[RISK GAP 1]")).toBeTruthy();
    const form = within(p).getByRole("form", { name: "Edit Risk" });
    expect(await axeViolations(container)).toEqual([]);
    await user.selectOptions(within(form).getByLabelText("Impact"), "high");
    await user.type(within(form).getByLabelText("Reason for the change"), "Sale-day spike");
    await user.click(within(form).getByRole("button", { name: "Save change" }));

    expect(editRisk).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      riskId: edited.id,
      rowVersion: 1,
      description: "[RISK 1]",
      likelihood: "low",
      impact: "high",
      reason: "Sale-day spike",
    });
    await waitFor(() =>
      expect(
        screen
          .getByTestId("risks-card")
          .querySelector('[data-level-kind="impact"]')
          ?.textContent,
      ).toBe("High"),
    );
  });
});
