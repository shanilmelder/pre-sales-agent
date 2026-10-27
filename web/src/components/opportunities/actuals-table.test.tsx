import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CloseDeliveryResult,
  LoadActualsResult,
  SaveActualsResult,
} from "@/app/opportunities/actions";
import type { CatalogueOptions } from "@/app/opportunities/data";
import type { ActualsLine, ActualsView, ActualView, VarianceView } from "@/lib/actuals";
import { axeViolations } from "@/test/axe";

const loadActuals = vi.hoisted(() => vi.fn<(id: unknown) => Promise<LoadActualsResult>>());
const saveActuals = vi.hoisted(() => vi.fn<(input: unknown) => Promise<SaveActualsResult>>());
const correctActual = vi.hoisted(() => vi.fn<(input: unknown) => Promise<SaveActualsResult>>());
const closeDelivery = vi.hoisted(() => vi.fn<(input: unknown) => Promise<CloseDeliveryResult>>());
vi.mock("@/app/opportunities/actions", () => ({
  loadActuals,
  saveActuals,
  correctActual,
  closeDelivery,
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { ActualsSection } from "./actuals-table";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const L1 = "00000000-0000-7000-8000-0000000000b1";
const L2 = "00000000-0000-7000-8000-0000000000b2";
const CATALOGUE: CatalogueOptions = { integrationTypes: [], workPackages: [] };
const CAUSES: ActualsView["causes"] = [
  { value: "unknown_requirement", label: "Unknown requirement", unplanned: true },
  { value: "integration_complexity", label: "Integration complexity", unplanned: false },
  { value: "customer_delay", label: "Customer delay", unplanned: false },
  { value: "scope_change", label: "Scope change", unplanned: true },
  { value: "estimation_error", label: "Estimation error", unplanned: false },
  { value: "other", label: "Other", unplanned: true },
];

const OVER: VarianceView = {
  hours: 5,
  percent: 13.9,
  direction: "over",
  label: "+5.0 h (13.9%)",
  direction_label: "Over estimate",
};
const UNDER: VarianceView = {
  hours: -2,
  percent: -10,
  direction: "under",
  label: "−2.0 h (−10.0%)",
  direction_label: "Under estimate",
};

function actual(lineId: string, effort: number, variance: VarianceView): ActualView {
  return {
    id: `${lineId.slice(0, -2)}c1`,
    group_id: `${lineId.slice(0, -2)}d1`,
    version: 1,
    kind: "final",
    milestone_label: null,
    effort_hours: effort,
    duration_days: null,
    cost_minor: null,
    currency: null,
    variance_cause: "estimation_error",
    note: null,
    failed_assumptions: [],
    correction_reason: null,
    recorded_by_name: "Dana Delivery",
    recorded_at: "2026-10-27T10:00:00Z",
    line_id: lineId,
    estimate_version_id: "00000000-0000-7000-8000-0000000000e3",
    estimate_version: 3,
    integration_types: [],
    work_package: null,
    variance,
    cost_variance: null,
    history: [],
  };
}

function line(id: string, label: string, title: string, estimate: number, recorded: ActualView | null): ActualsLine {
  return {
    line_id: id,
    label,
    title,
    section: "integration",
    estimate_hours: estimate,
    integration_types: [],
    actual: recorded,
    variance: recorded?.variance ?? null,
    cost_variance: null,
  };
}

function view(overrides: Partial<ActualsView> = {}): ActualsView {
  return {
    baseline: { version_id: "00000000-0000-7000-8000-0000000000e3", version: 3, set_at: "2026-10-26T10:00:00Z" },
    lines: [
      line(L1, "L1", "WMS to SAP EWM interface", 122, null),
      line(L2, "L2", "CRM data migration", 36, actual(L2, 41, OVER)),
    ],
    unplanned: [],
    totals: {
      estimate_hours: 36,
      actual_hours: 41,
      variance: OVER,
      recorded_line_count: 1,
      line_count: 2,
      unplanned_count: 0,
    },
    assumptions: [],
    causes: CAUSES,
    open_line_count: 1,
    close_blocked_reason: "1 line has no final Actual",
    can_record: true,
    can_close: false,
    delivery: null,
    version_mismatch: null,
    row_version: 4,
    ...overrides,
  };
}

function renderSection(initial: ActualsView, catalogue = CATALOGUE) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <ActualsSection opportunityId={OPP_ID} initial={initial} catalogue={catalogue} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (id: string) => document.querySelector<HTMLElement>(`[data-line-id="${id}"]`)!;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ActualsSection", () => {
  it("draws the mockup: header, five columns, signed amber variance, Not recorded, footnote", async () => {
    const { container } = renderSection(view());
    expect(screen.getByRole("heading", { level: 2, name: "Actuals" })).toBeTruthy();
    expect(
      screen.getByText(
        "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line.",
      ),
    ).toBeTruthy();
    const table = screen.getByRole("table", { name: "Actuals per Estimate line" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Line",
      "Estimate h",
      "Actual h",
      "Variance, sort by variance",
      "Variance cause",
    ]);
    const over = within(row(L2)).getByText("+5.0 h (13.9%)");
    expect(over.className).toContain("text-gap"); // amber, never red
    expect(over.textContent).toContain("Over estimate");
    expect(within(row(L1)).getByRole("combobox", { name: /Variance cause, L1/ })).toBeTruthy();
    expect(within(row(L1)).getByText("Not recorded")).toBeTruthy();
    expect(
      screen.getByText("Empty lines are not counted in variance. Each change is added to the Trace."),
    ).toBeTruthy();
    const importButton = screen.getByRole("button", { name: /Import from file/ });
    expect(importButton.getAttribute("aria-disabled")).toBe("true");
    expect(importButton.textContent).toContain("Import arrives in a later release");
    const close = screen.getByRole("button", { name: "Close delivery" });
    expect(close.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("1 line has no final Actual")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("green when under, with the minus sign", () => {
    renderSection(
      view({ lines: [line(L2, "L2", "CRM data migration", 20, actual(L2, 18, UNDER))] }),
    );
    const under = within(row(L2)).getByText("−2.0 h (−10.0%)");
    expect(under.className).toContain("text-resolved");
    expect(under.textContent).toContain("Under estimate");
  });

  it("is read only for other roles: no editable cells and no actions", async () => {
    const { container } = renderSection(view({ can_record: false }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save Actuals" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Import from file/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close delivery" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add Unplanned work" })).toBeNull();
    expect(within(row(L1)).getByText("Not recorded")).toBeTruthy();
    expect(within(row(L2)).getByText("Estimation error")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("no Baseline yet", () => {
    renderSection(view({ baseline: null, lines: [], can_record: false }));
    expect(
      screen.getByText("No Baseline yet. Actuals are recorded against the Baseline."),
    ).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("no Actuals: the empty-tab card, and Record Actuals opens the table", async () => {
    const user = userEvent.setup();
    const empty = view({
      lines: [line(L1, "L1", "WMS to SAP EWM interface", 122, null)],
      totals: { ...view().totals, variance: null },
    });
    const { container } = renderSection(empty);
    const card = screen.getByTestId("empty-tab-card");
    expect(within(card).getByText("No Actuals recorded")).toBeTruthy();
    expect(
      within(card).getByText(
        "Record hours per Estimate line with a variance cause once delivery starts.",
      ),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(card).getByRole("button", { name: "Record Actuals" }));
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("the version mismatch note", () => {
    renderSection(
      view({
        version_mismatch: {
          recorded_versions: [3],
          baseline_version: 5,
          actual_count: 2,
          message: "Actuals recorded against v3; the current Baseline is v5",
        },
      }),
    );
    expect(screen.getByText("Actuals recorded against v3; the current Baseline is v5")).toBeTruthy();
  });

  it("Save Actuals asks for a reason once when a line is corrected, then saves both", async () => {
    const user = userEvent.setup();
    const saved = view({ row_version: 6 });
    saveActuals.mockResolvedValue({ kind: "ok", saved: { recorded: 1, corrected: 1, view: saved } });
    renderSection(view());

    await user.type(within(row(L1)).getByRole("textbox", { name: /Actual hours, L1/ }), "120");
    const l2Hours = within(row(L2)).getByRole("textbox", { name: /Actual hours, L2/ });
    await user.clear(l2Hours);
    await user.type(l2Hours, "40");
    await user.click(screen.getAllByRole("button", { name: "Save Actuals" })[0]!);
    expect(saveActuals).not.toHaveBeenCalled();
    const reason = screen.getByRole("textbox", { name: "Reason for the correction" });
    await user.type(reason, "Timesheets closed");
    await user.click(screen.getAllByRole("button", { name: "Save Actuals" })[1]!);

    await waitFor(() => expect(saveActuals).toHaveBeenCalledTimes(1));
    expect(saveActuals.mock.calls[0]![0]).toMatchObject({
      opportunityId: OPP_ID,
      rowVersion: 4,
      reason: "Timesheets closed",
      items: [
        { line_id: L1, kind: "final", effort_hours: 120, variance_cause: null },
        { line_id: L2, kind: "final", effort_hours: 40, variance_cause: "estimation_error" },
      ],
    });
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Reason for the correction" })).toBeNull(),
    );
  });

  it("a 422 marks the cause; a 412 offers Reload", async () => {
    const user = userEvent.setup();
    saveActuals.mockResolvedValueOnce({
      kind: "invalid",
      errors: [
        {
          item: 0,
          field: "variance_cause",
          message: "A final Actual that differs from the estimate needs a variance cause.",
        },
      ],
    });
    const { container } = renderSection(view());
    await user.type(within(row(L1)).getByRole("textbox", { name: /Actual hours, L1/ }), "130");
    await user.click(screen.getByRole("button", { name: "Save Actuals" }));
    const cause = await within(row(L1)).findByRole("combobox", { name: /Variance cause, L1/ });
    await waitFor(() => expect(cause.getAttribute("aria-invalid")).toBe("true"));
    expect(
      within(row(L1)).getByText("A final Actual that differs from the estimate needs a variance cause."),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    saveActuals.mockResolvedValueOnce({ kind: "stale" });
    loadActuals.mockResolvedValue({ kind: "ok", actuals: view({ row_version: 9 }) });
    await user.selectOptions(cause, "estimation_error");
    await user.click(screen.getByRole("button", { name: "Save Actuals" }));
    const alert = await screen.findByText("Actuals changed since you opened them.");
    await user.click(within(alert.closest("[role=alert]") as HTMLElement).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(loadActuals).toHaveBeenCalledWith(OPP_ID));
  });

  it("Close delivery once every line has a final Actual", async () => {
    const user = userEvent.setup();
    const ready = view({
      lines: [line(L2, "L2", "CRM data migration", 36, actual(L2, 41, OVER))],
      open_line_count: 0,
      close_blocked_reason: null,
      can_close: true,
    });
    closeDelivery.mockResolvedValue({
      kind: "ok",
      actuals: {
        ...ready,
        can_record: false,
        can_close: false,
        close_blocked_reason: "Delivery is closed.",
        delivery: { closed_at: "2026-10-27T12:00:00Z", closed_by_name: "Dana Delivery", estimate_version: 3 },
      },
    });
    renderSection(ready);
    const close = screen.getByRole("button", { name: "Close delivery" });
    expect(close.getAttribute("aria-disabled")).toBeNull();
    await user.click(close);
    // Irreversible: a confirm dialog first, and nothing is posted until it is confirmed.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Actuals are locked/)).toBeTruthy();
    expect(closeDelivery).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Close delivery" }));
    await waitFor(() => expect(closeDelivery).toHaveBeenCalledWith({ opportunityId: OPP_ID, rowVersion: 4 }));
    expect(await screen.findByText("Delivery closed on 27 Oct 2026 by Dana Delivery.")).toBeTruthy();
  });

  it("selecting a line opens the Inspector with the full form and history", async () => {
    const user = userEvent.setup();
    renderSection(view());
    await user.click(within(row(L2)).getByRole("button", { name: "L2 CRM data migration" }));
    const pane = screen.getByRole("complementary", { name: "Details" });
    expect(within(pane).getByRole("heading", { name: "L2 CRM data migration" })).toBeTruthy();
    expect(within(pane).getByRole("combobox", { name: "Kind" })).toBeTruthy();
    expect(within(pane).getByRole("textbox", { name: "Reason for the correction" })).toBeTruthy();
    expect(within(pane).getByText("v1 · 41.0 h · Final")).toBeTruthy();
    expect(await axeViolations(pane)).toEqual([]);
  });
});


describe("ActualInspector saves", () => {
  beforeEach(() => vi.clearAllMocks());

  it("a correction needs a reason, then sends correctActual with the Actual's version", async () => {
    const user = userEvent.setup();
    correctActual.mockResolvedValue({
      kind: "ok",
      saved: { recorded: 0, corrected: 1, view: view() },
    });
    renderSection(view());
    await user.click(within(row(L2)).getByRole("button", { name: "L2 CRM data migration" }));
    const pane = screen.getByRole("complementary", { name: "Details" });
    const effort = within(pane).getByRole("textbox", { name: "Actual hours" });
    await user.clear(effort);
    await user.type(effort, "40");
    await user.click(within(pane).getByRole("button", { name: "Save correction" }));
    expect(correctActual).not.toHaveBeenCalled();
    expect(within(pane).getByText("A reason is required to correct a recorded Actual.")).toBeTruthy();

    await user.type(within(pane).getByRole("textbox", { name: "Reason for the correction" }), "Late invoice");
    await user.click(within(pane).getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(correctActual).toHaveBeenCalledTimes(1));
    const input = correctActual.mock.calls[0]![0] as {
      actualId: string;
      version: number;
      fields: { reason: string; effort_hours: number };
    };
    expect(input).toMatchObject({ opportunityId: OPP_ID, actualId: actual(L2, 41, OVER).id, version: 1 });
    expect(input.fields).toMatchObject({ reason: "Late invoice", effort_hours: 40 });
  });

  it("new Unplanned work sends saveActuals with no line and the chosen Integration Type", async () => {
    const user = userEvent.setup();
    const IT = "00000000-0000-7000-8000-0000000000f1";
    saveActuals.mockResolvedValue({ kind: "ok", saved: { recorded: 1, corrected: 0, view: view() } });
    renderSection(view(), { integrationTypes: [{ id: IT, name: "ERP" }], workPackages: [] });
    await user.click(screen.getByRole("button", { name: "Add Unplanned work" }));
    const pane = screen.getByRole("complementary", { name: "Details" });
    await user.type(within(pane).getByRole("textbox", { name: "Actual hours" }), "8");
    await user.selectOptions(within(pane).getByRole("combobox", { name: "Integration Type" }), IT);
    await user.selectOptions(
      within(pane).getByRole("combobox", { name: "Variance cause" }),
      "scope_change",
    );
    await user.click(within(pane).getByRole("button", { name: "Record Actual" }));
    await waitFor(() => expect(saveActuals).toHaveBeenCalledTimes(1));
    const input = saveActuals.mock.calls[0]![0] as { rowVersion: number; items: Record<string, unknown>[] };
    expect(input.rowVersion).toBe(4);
    expect(input.items).toHaveLength(1);
    expect(input.items[0]).not.toHaveProperty("line_id");
    expect(input.items[0]).toMatchObject({
      integration_type_id: IT,
      effort_hours: 8,
      variance_cause: "scope_change",
    });
  });

  it("a cause with no hours marks the hours cell", async () => {
    const user = userEvent.setup();
    renderSection(view());
    await user.selectOptions(
      within(row(L1)).getByRole("combobox", { name: /Variance cause, L1/ }),
      "scope_change",
    );
    const hoursCell = within(row(L1)).getByRole("textbox", { name: /Actual hours, L1/ });
    expect(hoursCell.getAttribute("aria-invalid")).toBe("true");
    expect(within(row(L1)).getByText("Enter hours to record this line")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save Actuals" }));
    expect(saveActuals).not.toHaveBeenCalled();
  });
});

class FakeSource {
  static last: FakeSource | null = null;
  readonly listeners = new Map<string, (() => void)[]>();
  readyState = 1;
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {}
  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

describe("live re-read", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("EventSource", FakeSource);
    loadActuals.mockResolvedValue({ kind: "ok", actuals: view({ row_version: 5 }) });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("re-reads on an actuals frame when clean, not after typing into a cell", async () => {
    const user = userEvent.setup();
    renderSection(view());
    const source = FakeSource.last!;
    await act(async () => source.emit("open"));
    loadActuals.mockClear();

    await act(async () => source.emit("actuals.actual.recorded"));
    await waitFor(() => expect(loadActuals).toHaveBeenCalledWith(OPP_ID));

    loadActuals.mockClear();
    await user.type(within(row(L1)).getByRole("textbox", { name: /Actual hours, L1/ }), "5");
    await act(async () => source.emit("actuals.actual.recorded"));
    expect(loadActuals).not.toHaveBeenCalled();
  });
});
