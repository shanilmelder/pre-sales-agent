import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CoverageCell, KnowledgeCoverage } from "@/lib/coverage";
import { SKELETON_MIN_MS } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

import { CoverageMatrix, NO_PRODUCTS, NO_TYPES } from "./coverage-matrix";

const REST = "00000000-0000-7000-8000-000000000011";
const BATCH = "00000000-0000-7000-8000-000000000012";
const SSO = "00000000-0000-7000-8000-000000000013";

function cell(
  integration_type_id: string,
  status: CoverageCell["status"],
  sources = 0,
  stale = 0,
  checklists = 0,
): CoverageCell {
  return { integration_type_id, status, sources, stale, checklists };
}

const COVERAGE: KnowledgeCoverage = {
  integration_types: [
    { id: REST, code: "REST", name: "REST API" },
    { id: BATCH, code: "BATCH", name: "File batch" },
    { id: SSO, code: "SSO", name: "Single sign-on" },
  ],
  rows: [
    {
      product: "Dynamics 365 F&O",
      cells: [
        cell(REST, "ready", 2, 0, 1),
        cell(BATCH, "partial", 2, 2, 1),
        cell(SSO, "missing"),
      ],
    },
    {
      product: "HubSpot",
      cells: [cell(REST, "partial", 1, 0, 0), cell(BATCH, "partial", 0, 0, 3), cell(SSO, "missing")],
    },
  ],
  industries: [],
  stale_months: 12,
};

function renderMatrix(coverage: KnowledgeCoverage = COVERAGE) {
  return render(<CoverageMatrix coverage={coverage} />);
}

/** Past the skeleton's minimum time. */
async function rendered(coverage: KnowledgeCoverage = COVERAGE) {
  const utils = renderMatrix(coverage);
  await act(async () => {
    vi.advanceTimersByTime(SKELETON_MIN_MS);
  });
  return utils;
}

const cellNamed = (name: RegExp) => screen.getByRole("gridcell", { name });

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  push.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CoverageMatrix", () => {
  it("shows skeleton cells for at least 150 ms on first load", async () => {
    renderMatrix();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(document.querySelectorAll("[data-skeleton-row]")).toHaveLength(2);
    expect(document.querySelectorAll("[data-skeleton-cell]")).toHaveLength(6);
    await act(async () => {
      vi.advanceTimersByTime(SKELETON_MIN_MS - 10);
    });
    expect(screen.queryByRole("grid")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByRole("grid")).toBeTruthy();
    expect(document.querySelector("[data-skeleton-row]")).toBeNull();
  });

  it("has the Product column, a column per Integration Type and a row per product", async () => {
    await rendered();
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Product", "REST API", "File batch", "Single sign-on"]);
    expect(screen.getAllByRole("rowheader").map((h) => h.textContent)).toEqual([
      "Dynamics 365 F&O",
      "HubSpot",
    ]);
    expect(screen.getAllByRole("gridcell")).toHaveLength(6);
  });

  it("labels every cell and its counts, with None and Stale in words", async () => {
    await rendered();
    const ready = cellNamed(/^Dynamics 365 F&O REST API Ready/);
    expect(within(ready).getByText("Ready").closest("[data-tone]")?.getAttribute("data-tone")).toBe(
      "resolved",
    );
    expect(ready.querySelector("svg")).toBeTruthy();
    expect(ready.textContent).toContain("Sources: 2");
    expect(ready.textContent).toContain("Checklists: 1");

    const stale = cellNamed(/^Dynamics 365 F&O File batch Partial/);
    expect(stale.textContent).toContain("Sources: Stale (2)");
    expect(within(stale).getByText("Partial").closest("[data-tone]")?.getAttribute("data-tone")).toBe(
      "gap",
    );

    const missing = cellNamed(/^HubSpot Single sign-on Missing/);
    expect(missing.textContent).toContain("Sources: None");
    expect(missing.textContent).toContain("Checklists: None");
    expect(
      within(missing).getByText("Missing").closest("[data-tone]")?.getAttribute("data-tone"),
    ).toBe("blocker");

    expect(cellNamed(/^HubSpot REST API Partial/).textContent).toContain("Checklists: None");
  });

  it("names each cell by its row and column headers", async () => {
    await rendered();
    expect(
      cellNamed(/^HubSpot File batch Partial Sources: None Checklists: 3$/),
    ).toBeTruthy();
  });

  it("is one Tab stop, and the arrow keys, Home and End move between cells", async () => {
    await rendered();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const cells = screen.getAllByRole("gridcell");
    expect(cells.filter((c) => c.tabIndex === 0)).toHaveLength(1);

    await user.tab();
    expect(document.activeElement).toBe(cellNamed(/^Dynamics 365 F&O REST API/));
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(cellNamed(/^Dynamics 365 F&O File batch/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot File batch/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot File batch/));
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot Single sign-on/));
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot Single sign-on/));
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot REST API/));
    await user.keyboard("{ArrowUp}{ArrowLeft}");
    expect(document.activeElement).toBe(cellNamed(/^Dynamics 365 F&O REST API/));
    await user.keyboard("{Control>}{End}{/Control}");
    expect(document.activeElement).toBe(cellNamed(/^HubSpot Single sign-on/));

    // The tab stop follows the focus.
    expect(cellNamed(/^HubSpot Single sign-on/).tabIndex).toBe(0);
    expect(cellNamed(/^Dynamics 365 F&O REST API/).tabIndex).toBe(-1);
  });

  it("Enter opens Sources filtered to the cell's product and Integration Type", async () => {
    await rendered();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.tab();
    await user.keyboard("{ArrowRight}{Enter}");
    expect(push).toHaveBeenCalledWith(`/knowledge?product=Dynamics+365+F%26O&type=${BATCH}`);
  });

  it("a click on a cell opens Sources too", async () => {
    await rendered();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(within(cellNamed(/^HubSpot REST API/)).getByText("Partial"));
    expect(push).toHaveBeenCalledWith(`/knowledge?product=HubSpot&type=${REST}`);
  });

  it("a modifier or middle click opens Sources in a new tab", async () => {
    await rendered();
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const target = within(cellNamed(/^HubSpot REST API/)).getByText("Partial");
    const href = `/knowledge?product=HubSpot&type=${REST}`;
    for (const modifier of ["Control", "Meta", "Shift"]) {
      await user.keyboard(`{${modifier}>}`);
      await user.click(target);
      await user.keyboard(`{/${modifier}}`);
    }
    await user.pointer({ keys: "[MouseMiddle]", target });
    expect(opened.mock.calls).toEqual(Array(4).fill([href, "_blank", "noopener"]));
    expect(push).not.toHaveBeenCalled();
    opened.mockRestore();
  });

  it("the Checklists count is its own link, reached with Tab from the cell", async () => {
    await rendered();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.tab();
    await user.tab();
    const link = document.activeElement as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.textContent).toBe("Checklists: 1");
    expect(link.getAttribute("href")).toBe(
      `/knowledge/checklists?product=Dynamics+365+F%26O&type=${REST}`,
    );
    // Only the current cell's link is in the Tab order.
    const links = document.querySelectorAll<HTMLAnchorElement>("[data-checklists-link]");
    expect([...links].filter((l) => l.tabIndex === 0)).toEqual([link]);
    // Enter on the link is the link's, not the cell's.
    await user.keyboard("{Enter}");
    expect(push).not.toHaveBeenCalled();
  });

  it("says when there are no Integration Types or no products", async () => {
    const { unmount } = await rendered({ ...COVERAGE, integration_types: [], rows: [] });
    expect(screen.getByText(NO_TYPES)).toBeTruthy();
    unmount();
    await rendered({ ...COVERAGE, rows: [] });
    expect(screen.getByText(NO_PRODUCTS)).toBeTruthy();
  });

  it("has no axe violations, loading or loaded", async () => {
    vi.useRealTimers();
    const { container } = renderMatrix();
    expect(await axeViolations(container)).toEqual([]);
    await screen.findByRole("grid");
    expect(await axeViolations(container)).toEqual([]);
  });
});
