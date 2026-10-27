import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CITATIONS_PENDING, GRAPH_EMPTY, type KnowledgeGraph } from "@/lib/knowledge-graph";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";
import { GRAPH_IDS, GRAPH_OWNER, graphFixture } from "@/test/knowledge-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { GraphCanvas } from "./graph-canvas";

const actions = vi.hoisted(() => ({ markReviewed: vi.fn() }));
const graphActions = vi.hoisted(() => ({ loadGraph: vi.fn() }));
vi.mock("@/app/knowledge/actions", () => actions);
vi.mock("@/app/knowledge/graph/actions", () => graphActions);
vi.mock("@/app/opportunities/actions", () => ({ loadOpportunity: vi.fn(), updateOpportunity: vi.fn() }));

const OWNER = { id: GRAPH_OWNER.id, roles: ["engineering_reviewer"] as Role[] };
const STRANGER = { id: "00000000-0000-7000-8000-000000000999", roles: ["pm_reviewer"] as Role[] };
const ADMIN = { id: "00000000-0000-7000-8000-000000000998", roles: ["platform_administrator"] as Role[] };

function renderCanvas(me = OWNER, graph: KnowledgeGraph = graphFixture()) {
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <GraphCanvas initialGraph={graph} me={me} />
    </ShellProviders>,
  );
  return { user: userEvent.setup(), ...utils };
}

async function node(name: string | RegExp) {
  return screen.findByRole("button", { name });
}

function drawer() {
  return screen.getByRole("complementary", { name: "Node details" });
}

beforeEach(() => {
  actions.markReviewed.mockReset();
  graphActions.loadGraph.mockReset();
});

describe("GraphCanvas", () => {
  it("shows a skeleton for at least 150 ms, then the nodes", async () => {
    vi.useFakeTimers();
    try {
      const { container } = render(
        <ShellProviders singleKeyShortcuts>
          <GraphCanvas initialGraph={graphFixture()} me={OWNER} />
        </ShellProviders>,
      );
      expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
      expect(screen.queryByRole("button", { name: /SAP EWM, Product/ })).toBeNull();
      act(() => vi.advanceTimersByTime(149));
      expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
      act(() => vi.advanceTimersByTime(1));
      expect(screen.getByRole("button", { name: "SAP EWM, Product, Ready" })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("names every node by label, type and status, as a focusable button", async () => {
    const { container } = renderCanvas();
    await node("SAP EWM, Product, Ready");
    const names = screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("data-node-id"))
      .map((b) => b.getAttribute("aria-label"));
    expect(names).toEqual([
      "SAP EWM, Product, Ready",
      "HubSpot, Product, Partial coverage",
      "REST API, Integration Type, Partial coverage",
      "SAP EWM guide, Knowledge Source, Ready",
      "HubSpot playbook, Knowledge Source, Stale",
      "ERP checklist, Checklist, Ready",
    ]);
    for (const g of container.querySelectorAll("[data-node-id]")) {
      expect(g.getAttribute("tabindex")).toBe("0");
    }
    // Status text under the label, empty when Ready; a dashed ring only for stale/failed/missing.
    const playbook = container.querySelector(`[data-node-id="${GRAPH_IDS.playbook}"]`)!;
    expect(playbook.querySelector("[data-status-text]")?.textContent).toBe("Stale");
    expect(playbook.querySelector("[data-status-ring]")?.getAttribute("opacity")).toBe("1");
    const sap = container.querySelector(`[data-node-id="${GRAPH_IDS.sap}"]`)!;
    expect(sap.querySelector("[data-status-text]")?.textContent).toBe("");
    expect(sap.querySelector("[data-status-ring]")?.getAttribute("opacity")).toBe("0");
    // One dashed amber edge, for the gap.
    const gaps = container.querySelectorAll('line[data-edge-kind="gap"]');
    expect(gaps).toHaveLength(1);
    expect(gaps[0].getAttribute("stroke-dasharray")).toBe("5 4");
    expect((gaps[0] as SVGElement).style.stroke).toBe("var(--graph-edge-gap)");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("draws the same positions on every render of the same data", async () => {
    const first = renderCanvas();
    await node("SAP EWM, Product, Ready");
    const where = (root: HTMLElement) =>
      Array.from(root.querySelectorAll("[data-node-id]")).map((g) => g.getAttribute("transform"));
    const before = where(first.container);
    first.unmount();
    const second = renderCanvas();
    await node("SAP EWM, Product, Ready");
    expect(where(second.container)).toEqual(before);
  });

  it("selects a node with Enter or Space and closes the drawer with Esc", async () => {
    const { user } = renderCanvas();
    const sap = await node("SAP EWM, Product, Ready");
    sap.focus();
    await user.keyboard("{Enter}");
    expect(within(drawer()).getByRole("heading", { name: "SAP EWM" })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Node details" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(sap));

    const erp = await node("ERP checklist, Checklist, Ready");
    erp.focus();
    await user.keyboard(" ");
    expect(within(drawer()).getByRole("heading", { name: "ERP checklist" })).toBeTruthy();
    await user.click(within(drawer()).getByRole("button", { name: "Close details" }));
    expect(screen.queryByRole("complementary", { name: "Node details" })).toBeNull();
  });

  it("dims what the search doesn't match, and all but the selection and its neighbours", async () => {
    const { user, container } = renderCanvas();
    await node("SAP EWM, Product, Ready");
    const opacity = (id: string) =>
      container.querySelector(`[data-node-id="${id}"]`)?.getAttribute("opacity");
    await user.type(screen.getByRole("searchbox", { name: "Search the graph" }), "sap");
    expect(opacity(GRAPH_IDS.sap)).toBe("1");
    expect(opacity(GRAPH_IDS.guide)).toBe("1");
    expect(opacity(GRAPH_IDS.hub)).toBe("0.28");
    expect(opacity(GRAPH_IDS.erp)).toBe("0.28");
    await user.clear(screen.getByRole("searchbox", { name: "Search the graph" }));

    await user.click(await node("HubSpot, Product, Partial coverage"));
    expect(opacity(GRAPH_IDS.hub)).toBe("1");
    expect(opacity(GRAPH_IDS.playbook)).toBe("1");
    expect(opacity(GRAPH_IDS.rest)).toBe("1");
    expect(opacity(GRAPH_IDS.sap)).toBe("0.28");
  });

  it("shows each type's count on its chip, and a chip turned off removes its nodes and edges", async () => {
    const { user, container } = renderCanvas();
    await node("SAP EWM, Product, Ready");
    const chips = screen.getAllByRole("button", { pressed: true });
    expect(chips.map((c) => c.textContent)).toEqual([
      "Products2",
      "Integration Types1",
      "Knowledge Sources2",
      "Checklists1",
    ]);
    expect(container.querySelectorAll("line[data-edge-kind]")).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: /Knowledge Sources/ }));
    expect(screen.getByRole("button", { name: /Knowledge Sources/ }).getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelectorAll('[data-node-type="source"]')).toHaveLength(0);
    expect(container.querySelectorAll("line[data-edge-kind]")).toHaveLength(4);
    expect(screen.getByRole("button", { name: /Knowledge Sources/ }).textContent).toBe("Knowledge Sources2");
    await user.click(screen.getByRole("button", { name: /Knowledge Sources/ }));
    expect(container.querySelectorAll('[data-node-type="source"]')).toHaveLength(2);
  });

  it("fills the drawer: header, score, tabs, connections and citations, with no retrieval stats", async () => {
    const { user, container } = renderCanvas(STRANGER);
    await user.click(await node("HubSpot playbook, Knowledge Source, Stale"));
    const aside = drawer();
    expect(aside.textContent).toContain("Knowledge Source");
    expect(aside.textContent).toContain("Owner [OWNER 2] · Reviewed 8 Jan 2025");
    const score = within(aside).getByTestId("graph-score");
    expect(score.textContent).toContain("Coverage score");
    expect(score.textContent).toContain("25/100");
    expect(within(score).getByText("Stale").closest("[data-slot=pill]")?.getAttribute("data-tone")).toBe("gap");
    expect(within(aside).getByTestId("graph-score-bar").style.width).toBe("25%");

    // Overview: Connections and Stale in only.
    const stats = Array.from(aside.querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(stats).toEqual(["Connections", "Stale in"]);
    expect(aside.querySelector("dl")?.textContent).toBe("Connections2Stale inNow");
    for (const word of ["Used by agents", "Last retrieved", "Cited by"]) {
      expect(container.textContent).not.toContain(word);
    }

    const tabs = within(aside).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Connections", "Citations"]);
    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(within(aside).getByRole("tab", { name: "Connections" }).getAttribute("aria-selected")).toBe("true");
    const rows = within(within(aside).getByRole("tabpanel")).getAllByRole("button");
    expect(rows.map((r) => r.textContent)).toEqual(["HubSpotProduct", "REST APIIntegration Type"]);

    // Selecting a connection moves the drawer to it; a gap reads Missing coverage, in amber.
    await user.click(rows[0]);
    expect(within(drawer()).getByRole("heading", { name: "HubSpot" })).toBeTruthy();
    expect(drawer().textContent).toContain("Owner — · Reviewed —");
    const gap = within(within(drawer()).getByRole("tabpanel")).getByRole("button", { name: /REST API/ });
    expect(within(gap).getByText("Missing coverage").className).toContain("text-gap");

    await user.click(within(drawer()).getByRole("tab", { name: "Citations" }));
    expect(within(drawer()).getByRole("tabpanel").textContent).toBe(CITATIONS_PENDING);
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["SAP EWM guide, Knowledge Source, Ready", "Open source", "/knowledge?source=00000000-0000-7000-8000-000000000101"],
    ["ERP checklist, Checklist, Ready", "Edit checklist", "/knowledge/checklists?checklist=00000000-0000-7000-8000-000000000301"],
    ["SAP EWM, Product, Ready", "View coverage", "/knowledge/coverage?product=SAP+EWM"],
    [
      "REST API, Integration Type, Partial coverage",
      "View coverage",
      "/knowledge/coverage?integration_type=00000000-0000-7000-8000-000000000011",
    ],
  ])("%s: the primary action is %s", async (name, label, href) => {
    const { user } = renderCanvas(STRANGER);
    await user.click(await node(name));
    expect(within(drawer()).getByRole("link", { name: label }).getAttribute("href")).toBe(href);
  });

  it("offers Mark reviewed only on a Source its owner or an admin may change", async () => {
    const owner = renderCanvas(OWNER);
    await owner.user.click(await node("SAP EWM guide, Knowledge Source, Ready"));
    expect(within(drawer()).getByRole("button", { name: "Mark reviewed" })).toBeTruthy();
    await owner.user.click(await node("HubSpot playbook, Knowledge Source, Stale"));
    expect(within(drawer()).queryByRole("button", { name: "Mark reviewed" })).toBeNull();
    await owner.user.click(await node("ERP checklist, Checklist, Ready"));
    expect(within(drawer()).queryByRole("button", { name: "Mark reviewed" })).toBeNull();
    owner.unmount();

    const admin = renderCanvas(ADMIN);
    await admin.user.click(await node("HubSpot playbook, Knowledge Source, Stale"));
    expect(within(drawer()).getByRole("button", { name: "Mark reviewed" })).toBeTruthy();
    admin.unmount();

    // The API's word wins: no Mark reviewed when it says the caller can't review.
    const graph = graphFixture();
    graph.nodes = graph.nodes.map((n) => (n.id === GRAPH_IDS.guide ? { ...n, can_review: false } : n));
    const refused = renderCanvas(OWNER, graph);
    await refused.user.click(await node("SAP EWM guide, Knowledge Source, Ready"));
    expect(within(drawer()).queryByRole("button", { name: "Mark reviewed" })).toBeNull();
  });

  it("marks a Source reviewed with its row version, announces it and reloads the graph", async () => {
    const reviewed = graphFixture();
    reviewed.nodes = reviewed.nodes.map((n) =>
      n.id === GRAPH_IDS.playbook ? { ...n, status: "ready", stale_in_days: 365, row_version: 2 } : n,
    );
    actions.markReviewed.mockResolvedValue({ kind: "ok", source: {} });
    graphActions.loadGraph.mockResolvedValue({ kind: "ok", graph: reviewed });
    const { user } = renderCanvas(ADMIN);
    await user.click(await node("HubSpot playbook, Knowledge Source, Stale"));
    await user.click(within(drawer()).getByRole("button", { name: "Mark reviewed" }));

    expect(actions.markReviewed).toHaveBeenCalledWith({
      sourceId: "00000000-0000-7000-8000-000000000102",
      rowVersion: 1,
    });
    expect(await node("HubSpot playbook, Knowledge Source, Ready")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Marked HubSpot playbook reviewed"),
    );
    expect(drawer().querySelector("dl")?.textContent).toContain("365 days");
  });

  it("shows the stale notice on a 412 and reloads on request", async () => {
    actions.markReviewed.mockResolvedValue({ kind: "stale" });
    graphActions.loadGraph.mockResolvedValue({ kind: "ok", graph: graphFixture() });
    const { user } = renderCanvas(OWNER);
    await user.click(await node("SAP EWM guide, Knowledge Source, Ready"));
    await user.click(within(drawer()).getByRole("button", { name: "Mark reviewed" }));
    const alert = await within(drawer()).findByRole("alert");
    expect(alert.textContent).toContain(
      "Changed by someone else since you opened it. Reload to see their change.",
    );
    expect(graphActions.loadGraph).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(graphActions.loadGraph).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(drawer()).queryByRole("alert")).toBeNull());
  });

  it("shows an empty card linking to Sources when there is nothing to draw", async () => {
    const { container } = renderCanvas(OWNER, graphFixture({ nodes: [], edges: [] }));
    expect(await screen.findByText(GRAPH_EMPTY)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to Sources" }).getAttribute("href")).toBe("/knowledge");
    expect(await axeViolations(container)).toEqual([]);
  });
});
