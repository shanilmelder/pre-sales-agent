import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EstimateLineEditInput,
  EstimateLineEditResult,
} from "@/app/opportunities/actions";
import type { EstimateResult } from "@/app/opportunities/data";
import type {
  EstimateDraft,
  EstimateLine,
  EstimateVersion,
  EstimateView,
  SectionName,
} from "@/lib/estimates";
import { axeViolations } from "@/test/axe";

const loadEstimate = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<EstimateResult>>(),
);
const editEstimateLine = vi.hoisted(() =>
  vi.fn<(input: EstimateLineEditInput) => Promise<EstimateLineEditResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  loadEstimate,
  editEstimateLine,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/estimate",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { EstimateGrid, EstimateHeader, EstimateSection } from "./estimate-grid";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function line(
  n: number,
  section: SectionName,
  effort: number,
  roleHours: [number, number, number],
  mix: [number, number, number] = [60, 20, 20],
): EstimateLine {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    position: n,
    section,
    title: `[LINE ${n}]`,
    basis: `[BASIS ${n}]`,
    role_mix: { engineer: mix[0], project_manager: mix[1], qa: mix[2] },
    effort_hours: effort,
    contingency_hours: 0,
    total_hours: effort,
    role_hours: { engineer: roleHours[0], project_manager: roleHours[1], qa: roleHours[2] },
    requirements: [
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0aa`,
        version: 1,
        label: "R2",
        excerpt: `[EXCERPT ${n}]`,
      },
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0bb`,
        version: 1,
        label: "R3",
        excerpt: `[EXCERPT ${n}b]`,
      },
    ],
    row_version: 1,
    edited: false,
    edited_by_name: null,
    edited_at: null,
    edit_reason: null,
    edit_carried_from_version: null,
    conflicts: [],
  };
}

function version(n = 2, uncovered = 1): EstimateVersion {
  return {
    id: `00000000-0000-7000-8000-00000000${String(n).padStart(4, "0")}`,
    version: n,
    status: "draft",
    template_version: "demo-1",
    roles: ["engineer", "project_manager", "qa"],
    uncovered_count: uncovered,
    dropped_count: 0,
    row_version: 1,
    created_at: "2026-10-05T09:00:00Z",
    sections: [
      {
        section: "functional",
        lines: [line(1, "functional", 24.5, [14.7, 4.9, 4.9])],
        subtotal: {
          effort_hours: 24.5,
          contingency_hours: 0,
          total_hours: 24.5,
          role_hours: { engineer: 14.7, project_manager: 4.9, qa: 4.9 },
        },
      },
      {
        section: "integration",
        lines: [
          line(2, "integration", 10, [3.3, 3.3, 3.4], [33, 33, 34]),
          line(3, "integration", 6.5, [6.5, 0, 0], [100, 0, 0]),
        ],
        subtotal: {
          effort_hours: 16.5,
          contingency_hours: 0,
          total_hours: 16.5,
          role_hours: { engineer: 9.8, project_manager: 3.3, qa: 3.4 },
        },
      },
    ],
    totals: {
      effort_hours: 41,
      contingency_hours: 0,
      total_hours: 41,
      role_hours: { engineer: 24.5, project_manager: 8.2, qa: 8.3 },
    },
    proposal_status: "succeeded",
    assumptions: { conditions: [], contingencies: [], contingency_hours: 0 },
    counts: { total: 0, accepted: 0, not_accepted: 0 },
    unconverted_gaps: [],
    unallocated_contingency_hours: 0,
    uncarried_edit_count: 0,
    uncarried_edits_from_version: null,
    source: "model",
    source_run: null,
  };
}

const succeeded: EstimateDraft = { status: "succeeded", error_code: null };
const failed: EstimateDraft = { status: "failed", error_code: "model_unavailable" };

/** A version built from the Assessments of run `run` (Story 8.3). */
function fromAssessments(n = 2, run = 1): EstimateVersion {
  return { ...version(n), source: "assessments", source_run: run };
}

function view(
  v: EstimateVersion | null,
  draft: EstimateDraft | null,
  canStart = true,
  assessmentRunning = false,
) {
  return {
    version: v,
    draft,
    can_start_draft: canStart,
    can_accept_assumptions: canStart,
    can_export: false,
    can_edit_lines: false,
    assessment_running: assessmentRunning,
  } satisfies EstimateView;
}

/** The Estimate while an assessment run is queued or running. */
function building(v: EstimateVersion | null = null) {
  return view(v, null, true, true);
}

function renderSection(initial: EstimateView, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <EstimateSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const lineButton = (n: number) => screen.getByRole("button", { name: `[LINE ${n}]` });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  loadEstimate.mockReset();
  editEstimateLine.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("EstimateGrid", () => {
  it("groups lines by section with subtotals, sticky header and totals, and the role totals", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <EstimateGrid version={version()} />
      </ShellProviders>,
    );
    const table = screen.getByRole("table", { name: "Estimate Draft v2" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Line",
      "Covers",
      "Role mix (%)",
      "Effort (h)",
      "Contingency (h)",
      "Total (h)",
    ]);
    expect(table.querySelector("thead")?.className).toContain("sticky");
    expect(table.querySelector("tfoot")?.className).toContain("sticky");
    const contingencyHeader = within(table).getByRole("columnheader", { name: "Contingency (h)" });
    expect(contingencyHeader.className).toContain("border-l");
    expect(contingencyHeader.className).toContain("text-right");

    const groups = table.querySelectorAll("tbody");
    expect(Array.from(groups).map((g) => g.getAttribute("data-section"))).toEqual([
      "functional",
      "integration",
    ]);
    const integration = within(groups[1] as HTMLElement).getAllByRole("row");
    expect(integration.map((r) => r.textContent)).toEqual([
      "Integration",
      "[LINE 2]2 RequirementsE 33 · PM 33 · QA 3410.00.010.0",
      "[LINE 3]2 RequirementsE 100 · PM 0 · QA 06.50.06.5",
      "Integration subtotal16.50.016.5",
    ]);
    const effortCell = within(integration[1]).getAllByRole("cell")[2];
    expect(effortCell.className).toContain("text-right");
    expect(effortCell.className).toContain("text-numeric");
    expect(within(integration[1]).getByRole("rowheader").textContent).toBe("[LINE 2]");

    const footer = table.querySelector("tfoot") as HTMLElement;
    expect(within(footer).getAllByRole("row").map((r) => r.textContent)).toEqual([
      "Total41.00.041.0",
      "Effort by roleEngineer 24.5 h · Project manager 8.2 h · QA 8.3 h",
    ]);
    const tabStops = screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([lineButton(1)]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrows move between lines across sections; j/k off with shortcuts off", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <EstimateGrid version={version()} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(lineButton(1));
    await user.keyboard("j");
    expect(document.activeElement).toBe(lineButton(2));
    await user.keyboard("j");
    await user.keyboard("j");
    expect(document.activeElement).toBe(lineButton(3));
    await user.keyboard("k");
    expect(document.activeElement).toBe(lineButton(2));
    await user.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(lineButton(1));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <EstimateGrid version={version()} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(lineButton(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(lineButton(2));
  });
});

describe("the inspector", () => {
  it("Enter opens the line in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(version(), succeeded));

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", { level: 3, name: "[LINE 2]" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(lineButton(2).closest("tr")?.getAttribute("aria-selected")).toBe("true");
    expect(within(inspector).getByText("Integration")).toBeTruthy();
    expect(within(inspector).getByText("[BASIS 2]")).toBeTruthy();
    const mix = within(inspector).getByRole("table", { name: "Role mix in hours" });
    expect(
      within(mix)
        .getAllByRole("row")
        .map((r) => r.textContent),
    ).toEqual(["RoleShare (%)Effort (h)", "Engineer333.3", "Project manager333.3", "QA343.4"]);
    expect(within(inspector).getByText("R2")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 2]")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 2b]")).toBeTruthy();
    const section = within(inspector).getByRole("region", { name: "[LINE 2]" });
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a click opens the line without moving focus into the pane", async () => {
    const user = userEvent.setup();
    renderSection(view(version(), succeeded));

    await user.click(lineButton(3));

    expect(within(pane()).getByRole("heading", { level: 3, name: "[LINE 3]" })).toBeTruthy();
    expect(document.activeElement).toBe(lineButton(3));
  });
});

describe("EstimateHeader", () => {
  it("shows the version pill and the uncovered Requirements, with no Retry", () => {
    render(<EstimateHeader version={version(2, 1)} />);
    expect(screen.getByText("Draft v2")).toBeTruthy();
    expect(screen.getByText("1 Requirement not covered")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names the assessment run a version from the Assessments was built for", () => {
    render(<EstimateHeader version={fromAssessments(4, 3)} />);
    expect(screen.getByText("Estimate v4 · from Assessments (run 3)")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("says a shown version is rebuilt when the run in progress finishes", async () => {
    const { container } = render(
      <EstimateHeader version={fromAssessments(4, 3)} assessmentRunning />,
    );
    const note = screen.getByText("Rebuilding from the Assessments when the run finishes.");
    expect(note.className).toContain("text-muted-foreground");
    expect(screen.getByTestId("running-dot")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("leaves out the uncovered count when every Requirement is covered", () => {
    render(<EstimateHeader version={version(1, 0)} />);
    expect(screen.queryByText(/not covered/)).toBeNull();
  });

  it("says the Estimate is built when the agents finish, with a running dot", () => {
    render(<EstimateHeader version={null} assessmentRunning />);
    expect(
      screen.getByText(
        "The Estimate is built when the Engineering, PM and Security Agents finish.",
      ),
    ).toBeTruthy();
    expect(screen.getByTestId("running-dot").className).toContain("motion-reduce:animate-none");
  });

  it("shows nothing before a version when no run is in progress", () => {
    const { container } = render(<EstimateHeader version={null} />);
    expect(container.textContent).toBe("");
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<EstimateHeader version={null} assessmentRunning stalled />);
    expect(screen.getByText("Still waiting for the agents — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });
});

describe("Open Conflict markers (Story 8.3)", () => {
  function withConflict(): EstimateVersion {
    const v = fromAssessments(2, 1);
    const integration = v.sections[1];
    v.sections = [
      v.sections[0],
      {
        ...integration,
        lines: [
          {
            ...integration.lines[0],
            edited: true,
            edited_by_name: "[OWNER]",
            edited_at: "2026-10-05T10:00:00Z",
            edit_reason: "[REASON]",
            conflicts: [
              { id: "00000000-0000-7000-8000-0000000000c1", type: "effort" },
              { id: "00000000-0000-7000-8000-0000000000c2", type: "scope" },
            ],
          },
          integration.lines[1],
        ],
      },
    ];
    return v;
  }

  it("marks the line next to Edited, linking to the Conflicts tab", async () => {
    const { container } = renderSection(view(withConflict(), null));

    const row = lineButton(2).closest("tr") as HTMLElement;
    const marker = within(row).getByRole("link", { name: /^Open Conflict/ });
    expect(marker.textContent).toBe("Open Conflict");
    expect(marker.getAttribute("href")).toBe(`/opportunities/${OPP_ID}/conflicts`);
    expect(marker.className).toContain("text-blocker");
    expect(marker.querySelector("svg")).toBeTruthy(); // an icon plus the label
    expect(marker.previousElementSibling?.textContent).toBe("Edited");
    const other = lineButton(3).closest("tr") as HTMLElement;
    expect(within(other).queryByText("Open Conflict")).toBeNull();
    // The marker is not a Tab stop: the lines stay one.
    expect(screen.getAllByRole("button").filter((b) => b.tabIndex === 0)).toEqual([
      lineButton(1),
    ]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the inspector names each Conflict's type and links to the Conflicts tab", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(withConflict(), null));

    await user.click(lineButton(2));

    const conflicts = pane().querySelector("[data-line-conflicts]") as HTMLElement;
    expect(within(conflicts).getByRole("heading", { level: 4 }).textContent).toBe(
      "Open Conflict",
    );
    expect(
      within(conflicts)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Effort Conflict", "Scope Conflict"]);
    const link = within(conflicts).getByRole("link", { name: "View on the Conflicts tab" });
    expect(link.getAttribute("href")).toBe(`/opportunities/${OPP_ID}/conflicts`);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(lineButton(3));
    expect(pane().querySelector("[data-line-conflicts]")).toBeNull();
  });
});

describe("EstimateSection", () => {
  it("shows Export when the caller may export the version", () => {
    renderSection({ ...view(version(2), succeeded), can_export: true });
    expect(screen.getByRole("button", { name: /^Export/ })).toBeTruthy();
  });

  it("hides Export from a caller who may not export the version", () => {
    renderSection(view(version(2), succeeded));
    expect(screen.getByText("Draft v2")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Export/ })).toBeNull();
  });

  it("shows the empty sentence when there is no version and no run", () => {
    renderSection(view(null, null));
    expect(
      screen.getByText("No Estimate yet. Run assessment on the Assessments tab to build it."),
    ).toBeTruthy();
  });

  it("offers no draft Retry, even after a model draft failed", async () => {
    const { container } = renderSection(view(null, failed));
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByText(/Estimate draft failed/)).toBeNull();
    expect(
      screen.getByText("No Estimate yet. Run assessment on the Assessments tab to build it."),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the waiting state passes axe", async () => {
    const { container } = renderSection(building());
    expect(
      screen.getByText(
        "The Estimate is built when the Engineering, PM and Security Agents finish.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/No Estimate yet/)).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("polls every 2 s while an assessment run is in progress, then shows the new version", async () => {
    vi.useFakeTimers();
    loadEstimate
      .mockResolvedValueOnce({ kind: "ok", estimate: building() })
      .mockResolvedValue({ kind: "ok", estimate: view(fromAssessments(1, 1), null) });
    renderSection(building());
    expect(screen.getByTestId("running-dot")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadEstimate).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadEstimate).toHaveBeenCalledWith(OPP_ID);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("[LINE 1]")).toBeTruthy();
    expect(screen.getByText("Estimate v1 · from Assessments (run 1)")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("Estimate v1 · from Assessments (run 1)");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadEstimate).toHaveBeenCalledTimes(2);
  });

  it("polls while the Assumption proposals run after the version was stored", async () => {
    vi.useFakeTimers();
    const proposed: EstimateVersion = {
      ...version(1),
      proposal_status: "succeeded",
      assumptions: {
        conditions: [
          {
            id: "00000000-0000-7000-8000-0000000000a1",
            kind: "condition",
            wording: "[WORDING 1]",
            amount_hours: null,
            line: null,
            origin_kind: "gap",
            origin: {
              id: "00000000-0000-7000-8000-0000000000e1",
              title: "[GAP 1]",
              category: "integration_details",
              impact: "high",
              why_it_matters: "[WHY 1]",
              status: "open",
            },
            accepted_by: null,
            accepted_at: null,
            row_version: 1,
            carried_from_version: null,
          },
        ],
        contingencies: [],
        contingency_hours: 0,
      },
      counts: { total: 1, accepted: 0, not_accepted: 1 },
    };
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(proposed, succeeded) });
    renderSection(view({ ...version(1), proposal_status: "queued" }, succeeded));
    expect(screen.getByText("Proposing Assumptions")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadEstimate).toHaveBeenCalledWith(OPP_ID);
    expect(screen.queryByText("Proposing Assumptions")).toBeNull();
    expect(screen.getByText("[WORDING 1]")).toBeTruthy();
    expect(screen.getByText("Not accepted")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe(
      "Assumptions Register: 1 · 0 accepted · 1 not accepted",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadEstimate).toHaveBeenCalledTimes(1);
  });

  it("keeps showing the current version while a new run is in progress", async () => {
    const { container } = renderSection(building(fromAssessments(1, 1)));
    expect(screen.getByText("Estimate v1 · from Assessments (run 1)")).toBeTruthy();
    expect(screen.getByText("[LINE 1]")).toBeTruthy();
    expect(screen.getByText("Rebuilding from the Assessments when the run finishes.")).toBeTruthy();
    expect(screen.getByTestId("running-dot")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("does not poll when nothing is running", async () => {
    vi.useFakeTimers();
    renderSection(view(version(), succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadEstimate).not.toHaveBeenCalled();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: building() });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(building());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadEstimate).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadEstimate).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: building() });
    renderSection(building());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadEstimate).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadEstimate.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadEstimate).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
    expect(screen.getByText("Still waiting for the agents — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("says to reload when shown again after being hidden past the 15-minute limit", async () => {
    vi.useFakeTimers();
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: building() });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(building());
      vi.setSystemTime(Date.now() + 16 * 60 * 1000);
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadEstimate).not.toHaveBeenCalled();
      expect(screen.getByText("Still waiting for the agents — reload to check.")).toBeTruthy();
      expect(screen.queryByTestId("running-dot")).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });

  it("a sales representative sees the same Estimate, read-only", async () => {
    const user = userEvent.setup();
    renderSection(view(version(), succeeded, false));
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await user.click(lineButton(1));

    expect(within(pane()).getByText("[BASIS 1]")).toBeTruthy();
    expect(within(pane()).queryByRole("textbox")).toBeNull();
  });

  it("clears the inspector when a new version replaces the selected line", async () => {
    vi.useFakeTimers();
    const next = fromAssessments(3, 2);
    next.uncovered_count = 0;
    next.sections = [
      { ...next.sections[0], lines: [line(9, "functional", 24.5, [14.7, 4.9, 4.9])] },
    ];
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(next, null) });
    renderSection(building(version()));
    act(() => {
      lineButton(1).click();
    });
    expect(within(pane()).getByRole("heading", { level: 3, name: "[LINE 1]" })).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByText("[LINE 9]")).toBeTruthy();
    expect(within(pane()).queryByText("[LINE 1]")).toBeNull();
    expect(within(pane()).getByText("Nothing selected.")).toBeTruthy();
  });
});

describe("editing a line (Story 8.2)", () => {
  const editable = (v = version()) => ({
    ...view(v, succeeded),
    can_edit_lines: true,
  });
  const effortButton = (n: number) =>
    screen.getByRole("button", {
      name: (name) => name.startsWith(`Edit effort of [LINE ${n}]`),
    });
  const mixButton = (n: number) =>
    screen.getByRole("button", {
      name: (name) => name.startsWith(`Edit role mix of [LINE ${n}]`),
    });
  const reasonBox = () => screen.getByRole("textbox", { name: "Reason for the change" });

  /** The Estimate after line 2's effort became `effort` with `reason`. */
  function afterEdit(effort: number, reason: string) {
    const next = version();
    const integration = next.sections[1];
    const edited: EstimateLine = {
      ...integration.lines[0],
      effort_hours: effort,
      total_hours: effort,
      row_version: 2,
      edited: true,
      edited_by_name: "[OWNER]",
      edited_at: "2026-10-05T10:00:00Z",
      edit_reason: reason,
    };
    next.sections = [next.sections[0], { ...integration, lines: [edited, integration.lines[1]] }];
    next.totals = { ...next.totals, effort_hours: 39, total_hours: 39 };
    return editable(next);
  }

  async function editEffortTo(user: ReturnType<typeof userEvent.setup>, n: number, text: string) {
    await user.click(effortButton(n));
    const input = screen.getByRole("textbox", {
      name: `Effort (h) of [LINE ${n}]`,
    });
    await user.clear(input);
    await user.type(input, `${text}{Enter}`);
  }

  it("Effort: Enter, a reason, Save; the grid re-renders from the server", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({
      kind: "ok",
      estimate: afterEdit(8, "[REASON]"),
    });
    const { container } = renderSection(editable());

    await user.click(effortButton(2));
    const input = screen.getByRole("textbox", {
      name: "Effort (h) of [LINE 2]",
    });
    expect((input as HTMLInputElement).value).toBe("10.0");
    await user.clear(input);
    await user.type(input, "8{Enter}");
    const prompt = screen.getByRole("form", { name: "Reason for the change" });
    expect(within(prompt).getByText("Effort 10.0 h → 8.0 h")).toBeTruthy();
    const save = within(prompt).getByRole("button", { name: "Save" });
    expect((save as HTMLButtonElement).disabled).toBe(true); // no reason yet
    expect(await axeViolations(container)).toEqual([]);
    await user.type(reasonBox(), "Reuse connector");
    await user.click(save);

    expect(editEstimateLine).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      lineId: line(2, "integration", 10, [0, 0, 0]).id,
      rowVersion: 1,
      effortHours: 8,
      reason: "Reuse connector",
    });
    await waitFor(() => expect(effortButton(2).textContent).toBe("8.0"));
    expect(screen.queryByRole("form", { name: "Reason for the change" })).toBeNull();
    const row = lineButton(2).closest("tr") as HTMLElement;
    expect(within(row).getByText("Edited")).toBeTruthy();
    const totals = container.querySelector("tr[data-totals]") as HTMLElement;
    expect(totals.textContent).toContain("39.0");
    await waitFor(() => expect(document.activeElement).toBe(effortButton(2)));

    // The inspector shows who, when and why.
    await user.click(lineButton(2));
    const history = pane().querySelector("[data-edit-history]") as HTMLElement;
    expect(history.textContent).toBe("Edited[OWNER], 5 Oct 2026: [REASON]");

    // The next reason prompt in this version starts from the last reason.
    await editEffortTo(user, 3, "2");
    expect((reasonBox() as HTMLInputElement).value).toBe("Reuse connector");
  });

  it("e on a focused line starts editing its effort; Esc cancels back to the cell", async () => {
    const user = userEvent.setup();
    renderSection(editable());

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("e");
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Effort (h) of [LINE 2]" }),
    );
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("textbox")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(effortButton(2)));
    expect(editEstimateLine).not.toHaveBeenCalled();
  });

  it("Esc in the reason prompt drops the change", async () => {
    const user = userEvent.setup();
    renderSection(editable());

    await editEffortTo(user, 2, "8");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("form", { name: "Reason for the change" })).toBeNull();
    expect(effortButton(2).textContent).toBe("10.0");
    expect(editEstimateLine).not.toHaveBeenCalled();
  });

  it("an unchanged effort asks for nothing; a non-number says why without calling", async () => {
    const user = userEvent.setup();
    renderSection(editable());

    await user.click(effortButton(2));
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("form", { name: "Reason for the change" })).toBeNull();

    await editEffortTo(user, 2, "lots");
    expect(screen.getByText("Effort must be a number of hours from 0 to 2,000.")).toBeTruthy();
    expect(editEstimateLine).not.toHaveBeenCalled();
  });

  it("Role mix: Save stays disabled until the shares add up to 100", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({ kind: "ok", estimate: editable() });
    const { container } = renderSection(editable());

    await user.click(mixButton(2));
    const editor = screen.getByRole("form", { name: "Role mix of [LINE 2]" });
    const engineer = within(editor).getByRole("textbox", {
      name: "Engineer (%)",
    });
    expect(document.activeElement).toBe(engineer);
    expect(within(editor).getByText("= 100%")).toBeTruthy();
    await user.clear(engineer);
    await user.type(engineer, "20");
    expect(within(editor).getByText("= 87%")).toBeTruthy();
    const save = within(editor).getByRole("button", { name: "Save" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    expect(await axeViolations(container)).toEqual([]);
    await user.clear(engineer);
    await user.type(engineer, "33.5");
    expect((save as HTMLButtonElement).disabled).toBe(true); // a fraction
    await user.clear(engineer);
    await user.type(engineer, "34");
    const pm = within(editor).getByRole("textbox", {
      name: "Project manager (%)",
    });
    await user.clear(pm);
    await user.type(pm, "32");
    expect(within(editor).getByText("= 100%")).toBeTruthy();
    await user.click(save);

    const prompt = screen.getByRole("form", { name: "Reason for the change" });
    expect(
      within(prompt).getByText("Role mix E 33 · PM 33 · QA 34 → E 34 · PM 32 · QA 34"),
    ).toBeTruthy();
    await user.type(reasonBox(), "Less PM{Enter}");

    expect(editEstimateLine).toHaveBeenCalledWith(
      expect.objectContaining({
        roleMix: { engineer: 34, project_manager: 32, qa: 34 },
        reason: "Less PM",
      }),
    );
    expect(editEstimateLine.mock.calls[0][0]).not.toHaveProperty("effortHours");
  });

  it("a refused change rolls back and shows the server's sentence under the line", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({
      kind: "invalid",
      detail: "Role mix must name every role and add up to 100%.",
    });
    renderSection(editable());

    await editEffortTo(user, 2, "8");
    await user.type(reasonBox(), "x{Enter}");

    expect(
      await screen.findByText("Role mix must name every role and add up to 100%."),
    ).toBeTruthy();
    expect(effortButton(2).textContent).toBe("10.0");
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
  });

  it("a stale save names who changed it and offers Reload", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    loadEstimate.mockResolvedValue({
      kind: "ok",
      estimate: afterEdit(4, "[THEIRS]"),
    });
    renderSection(editable());

    await editEffortTo(user, 2, "8");
    await user.type(reasonBox(), "x{Enter}");

    expect(await screen.findByText("Changed by [OTHER] since you opened it.")).toBeTruthy();
    expect(effortButton(2).textContent).toBe("10.0");
    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(effortButton(2).textContent).toBe("4.0"));
    expect(screen.queryByText(/Changed by/, { selector: "p" })).toBeNull();
  });

  it("a replaced version says so and offers Reload", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({ kind: "not-draft" });
    renderSection(editable());

    await editEffortTo(user, 2, "8");
    await user.type(reasonBox(), "x{Enter}");

    expect(
      await screen.findByText(
        "This Estimate Version was replaced by a newer draft. Reload to see it.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("saves with the row version seen when editing started, even after a refresh", async () => {
    const user = userEvent.setup();
    editEstimateLine.mockResolvedValue({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    const { rerender } = renderSection(editable());
    await editEffortTo(user, 2, "8");

    // A refresh brings the colleague's save (row version 2) while the prompt is open.
    const refreshed = afterEdit(4, "[THEIRS]");
    rerender(
      <ShellProviders singleKeyShortcuts>
        <EstimateSection opportunityId={OPP_ID} initial={refreshed} />
        <RightPane />
      </ShellProviders>,
    );
    const prompt = screen.getByRole("form", { name: "Reason for the change" });
    expect(within(prompt).getByText("Effort 10.0 h → 8.0 h")).toBeTruthy();
    await user.type(reasonBox(), "x{Enter}");

    expect(editEstimateLine).toHaveBeenCalledWith(
      expect.objectContaining({ rowVersion: 1, effortHours: 8 }),
    );
    expect(await screen.findByText("Changed by [OTHER] since you opened it.")).toBeTruthy();
  });

  it("a new Estimate version drops an open edit and says so", async () => {
    const user = userEvent.setup();
    const { rerender } = renderSection(editable());
    await editEffortTo(user, 2, "8");

    rerender(
      <ShellProviders singleKeyShortcuts>
        <EstimateSection opportunityId={OPP_ID} initial={editable(version(3))} />
        <RightPane />
      </ShellProviders>,
    );

    expect(screen.queryByRole("form", { name: "Reason for the change" })).toBeNull();
    expect(
      screen.getByText("A new Estimate version arrived; your change was not saved."),
    ).toBeTruthy();
    expect(editEstimateLine).not.toHaveBeenCalled();
    await user.click(effortButton(1));
    expect(
      screen.queryByText("A new Estimate version arrived; your change was not saved."),
    ).toBeNull();
  });

  it("shows the effort as the server will round it (half up)", async () => {
    const user = userEvent.setup();
    renderSection(editable());

    await editEffortTo(user, 2, "0.35");

    expect(screen.getByText("Effort 10.0 h → 0.4 h")).toBeTruthy();
  });

  it("while a save is in flight the cells are disabled and show the pending value", async () => {
    const user = userEvent.setup();
    let finish: (result: EstimateLineEditResult) => void = () => {};
    editEstimateLine.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderSection(editable());

    await editEffortTo(user, 2, "8.25");
    await user.type(reasonBox(), "x{Enter}");

    expect(effortButton(2).textContent).toBe("8.3");
    for (const cell of [effortButton(2), effortButton(3), mixButton(2), mixButton(3)]) {
      expect((cell as HTMLButtonElement).disabled).toBe(true);
    }
    await user.click(mixButton(3));
    expect(screen.queryByRole("form", { name: "Role mix of [LINE 3]" })).toBeNull();

    await act(async () => {
      finish({ kind: "ok", estimate: afterEdit(8.3, "x") });
    });

    await waitFor(() => expect((effortButton(2) as HTMLButtonElement).disabled).toBe(false));
    expect(effortButton(2).textContent).toBe("8.3");
    expect((mixButton(3) as HTMLButtonElement).disabled).toBe(false);
  });

  it("explains a disabled Save: the reason counter and invalid role shares", async () => {
    const user = userEvent.setup();
    renderSection(editable());

    await editEffortTo(user, 2, "8");
    expect(screen.getByText("0/300")).toBeTruthy();
    await user.click(reasonBox());
    await user.paste("y".repeat(301));
    expect(screen.getByText("301/300: shorten the reason to save")).toBeTruthy();
    const prompt = screen.getByRole("form", { name: "Reason for the change" });
    expect(
      (
        within(prompt).getByRole("button", {
          name: "Save",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await user.keyboard("{Escape}");

    await user.click(mixButton(2));
    const editor = screen.getByRole("form", { name: "Role mix of [LINE 2]" });
    const qa = within(editor).getByRole("textbox", { name: "QA (%)" });
    expect(qa.getAttribute("aria-invalid")).toBeNull();
    await user.clear(qa);
    await user.type(qa, "3.5");
    expect(qa.getAttribute("aria-invalid")).toBe("true");
    expect(within(editor).getByText("Whole numbers 0–100")).toBeTruthy();
  });

  it("without the right to edit the cells are plain text, and e does nothing", async () => {
    const user = userEvent.setup();
    renderSection(view(version(), succeeded, false));

    expect(screen.queryByRole("button", { name: /^Edit effort/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Edit role mix/ })).toBeNull();
    await user.tab();
    await user.keyboard("e");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows a carried edit's marker and the note for edits a re-draft couldn't carry", async () => {
    const v = version(3);
    v.uncarried_edit_count = 1;
    v.uncarried_edits_from_version = 2;
    v.sections[0].lines[0] = {
      ...v.sections[0].lines[0],
      edited: true,
      edited_by_name: "[OWNER]",
      edited_at: "2026-10-05T10:00:00Z",
      edit_reason: "[REASON]",
      edit_carried_from_version: 2,
    };
    const { container } = renderSection(editable(v));

    expect(
      screen.getByText("1 edited line from v2 had no matching line; it stays in v2 and the Trace."),
    ).toBeTruthy();
    expect(screen.getByText("Edited, carried from v2")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
