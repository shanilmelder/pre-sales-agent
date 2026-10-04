import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StartEstimateDraftResult } from "@/app/opportunities/actions";
import type { EstimateResult } from "@/app/opportunities/data";
import type {
  EstimateDraft,
  EstimateLine,
  EstimateVersion,
  EstimateView,
  SectionName,
} from "@/lib/estimates";
import { axeViolations } from "@/test/axe";

const startEstimateDraft = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartEstimateDraftResult>>(),
);
const loadEstimate = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<EstimateResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({ startEstimateDraft, loadEstimate }));
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
  };
}

const queued: EstimateDraft = { status: "queued", error_code: null };
const running: EstimateDraft = { status: "running", error_code: null };
const succeeded: EstimateDraft = { status: "succeeded", error_code: null };
const failed: EstimateDraft = { status: "failed", error_code: "model_unavailable" };

function view(v: EstimateVersion | null, draft: EstimateDraft | null, canStart = true) {
  return {
    version: v,
    draft,
    can_start_draft: canStart,
    can_accept_assumptions: canStart,
  } satisfies EstimateView;
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
  startEstimateDraft.mockReset();
  loadEstimate.mockReset();
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
  it("shows the version pill and the uncovered Requirements", () => {
    render(<EstimateHeader version={version(2, 1)} draft={succeeded} canStart />);
    expect(screen.getByText("Draft v2")).toBeTruthy();
    expect(screen.getByText("1 Requirement not covered")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("leaves out the uncovered count when every Requirement is covered", () => {
    render(<EstimateHeader version={version(1, 0)} draft={succeeded} />);
    expect(screen.queryByText(/not covered/)).toBeNull();
  });

  it.each([queued, running])("shows Drafting Estimate with a running dot while $status", (d) => {
    render(<EstimateHeader version={null} draft={d} canStart />);
    expect(screen.getByText("Drafting Estimate")).toBeTruthy();
    expect(screen.getByTestId("running-dot").className).toContain("motion-reduce:animate-none");
  });

  it("shows the failure reason and Retry for those who may start a draft", () => {
    render(<EstimateHeader version={null} draft={failed} canStart />);
    expect(
      screen.getByText("Estimate draft failed: the model service couldn't be reached"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("hides Retry from those who may not start one", () => {
    render(<EstimateHeader version={null} draft={failed} canStart={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<EstimateHeader version={null} draft={running} stalled />);
    expect(screen.getByText("Still drafting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });
});

describe("EstimateSection", () => {
  it("shows the empty sentence before any draft", () => {
    renderSection(view(null, null));
    expect(screen.getByText("The Estimate is drafted after Gaps are detected.")).toBeTruthy();
  });

  it("polls every 2 s while drafting, then shows the new version", async () => {
    vi.useFakeTimers();
    loadEstimate
      .mockResolvedValueOnce({ kind: "ok", estimate: view(null, running) })
      .mockResolvedValue({ kind: "ok", estimate: view(version(1), succeeded) });
    renderSection(view(null, queued));
    expect(screen.getByText("Drafting Estimate")).toBeTruthy();
    expect(screen.queryByText("The Estimate is drafted after Gaps are detected.")).toBeNull();

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
    expect(screen.getByText("Draft v1")).toBeTruthy();
    expect(screen.queryByText("Drafting Estimate")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("Draft v1");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadEstimate).toHaveBeenCalledTimes(2);
  });

  it("polls while the Assumption proposals run after the draft succeeded", async () => {
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

  it("keeps showing the current version while a re-draft runs", () => {
    renderSection(view(version(1), running));
    expect(screen.getByText("Draft v1")).toBeTruthy();
    expect(screen.getByText("Drafting Estimate")).toBeTruthy();
    expect(screen.getByText("[LINE 1]")).toBeTruthy();
  });

  it("does not poll when no draft is running", async () => {
    vi.useFakeTimers();
    renderSection(view(version(), succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadEstimate).not.toHaveBeenCalled();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(null, running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(view(null, running));
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
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(null, running) });
    renderSection(view(null, running));
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
    expect(screen.getByText("Still drafting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("says to reload when shown again after being hidden past the 15-minute limit", async () => {
    vi.useFakeTimers();
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(null, running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(view(null, running));
      vi.setSystemTime(Date.now() + 16 * 60 * 1000);
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadEstimate).not.toHaveBeenCalled();
      expect(screen.getByText("Still drafting — reload to check.")).toBeTruthy();
      expect(screen.queryByTestId("running-dot")).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });

  it("Retry starts a new draft, which then polls to done", async () => {
    const user = userEvent.setup();
    startEstimateDraft.mockResolvedValue({ kind: "ok", draft: queued });
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(version(1), succeeded) });
    const { container } = renderSection(view(null, failed));
    expect(
      screen.getByText("Estimate draft failed: the model service couldn't be reached"),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(startEstimateDraft).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Drafting Estimate")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await waitFor(() => expect(screen.getByText("[LINE 1]")).toBeTruthy(), { timeout: 4000 });
  });

  it("a Retry answered 409 re-reads the tab", async () => {
    const user = userEvent.setup();
    startEstimateDraft.mockResolvedValue({ kind: "conflict" });
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(null, running) });
    renderSection(view(null, failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Drafting Estimate")).toBeTruthy());
  });

  it.each([
    [{ kind: "error" } as const, "The retry failed. Try again."],
    [
      { kind: "forbidden" } as const,
      "Only the owner and collaborators, except sales representatives, can draft the Estimate.",
    ],
  ])("a failed Retry says so and keeps the button (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startEstimateDraft.mockResolvedValue(result);
    renderSection(view(null, failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a sales representative sees the same Estimate, read-only, and no Retry", async () => {
    const user = userEvent.setup();
    renderSection(view(version(), failed, false));
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await user.click(lineButton(1));

    expect(within(pane()).getByText("[BASIS 1]")).toBeTruthy();
    expect(within(pane()).queryByRole("textbox")).toBeNull();
  });

  it("clears the inspector when a new version replaces the selected line", async () => {
    vi.useFakeTimers();
    const next = version(3, 0);
    next.sections = [{ ...next.sections[0], lines: [line(9, "functional", 24.5, [14.7, 4.9, 4.9])] }];
    loadEstimate.mockResolvedValue({ kind: "ok", estimate: view(next, succeeded) });
    renderSection(view(version(), running));
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

  it("says so when a finished draft had nothing to estimate", () => {
    renderSection(view(null, succeeded));
    expect(screen.getByText("There were no active Requirements to estimate.")).toBeTruthy();
  });
});
