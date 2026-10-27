import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NO_FILTERS } from "@/lib/knowledge-sources";
import { axeViolations } from "@/test/axe";
import { source } from "@/test/knowledge-fixtures";

vi.mock("@/app/knowledge/actions", () => ({
  loadSources: vi.fn(),
  loadSource: vi.fn(async () => ({ kind: "error" })),
  loadText: vi.fn(async () => ({ kind: "unavailable" })),
  registerSource: vi.fn(),
  searchOwners: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => ({}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/knowledge",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { SourcesTab } from "./sources-tab";

const EDI = { id: "00000000-0000-7000-8000-0000000000e1", name: "EDI" };
const SAP = { id: "00000000-0000-7000-8000-000000000001", name: "SAP IDoc" };
const ME = { id: "00000000-0000-7000-8000-000000000999", roles: ["presales_engineer" as const] };
const SOURCES = [
  source(1, { title: "AutoStore guide" }),
  source(2, {
    title: "Pick station EDI guide",
    product: "Pick station",
    integration_types: [{ ...EDI, code: "EDI", retired: false }],
  }),
];

function renderTab(initialFilters = NO_FILTERS, initialSelectedId?: string) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <SourcesTab
        initialSources={SOURCES}
        integrationTypes={[SAP, EDI]}
        initialFilters={initialFilters}
        initialSelectedId={initialSelectedId}
        me={ME}
      />
      <RightPane />
    </ShellProviders>,
  );
}

const select = (name: string) =>
  screen.getByRole("combobox", { name }) as HTMLSelectElement;

describe("SourcesTab initial filters (Story 4.1)", () => {
  it("opens filtered by the linked Integration Type", () => {
    renderTab({ ...NO_FILTERS, integrationTypeId: EDI.id });
    expect(select("Integration Type").value).toBe(EDI.id);
    expect(screen.queryByText("AutoStore guide")).toBeNull();
    expect(screen.getByText("Pick station EDI guide")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });

  it("matches a linked product ignoring case, using the Sources' spelling", () => {
    renderTab({ ...NO_FILTERS, product: "pick STATION" });
    expect(select("Product").value).toBe("Pick station");
    expect(screen.queryByText("AutoStore guide")).toBeNull();
  });

  it("keeps a linked product with no Source choosable, showing no rows", () => {
    renderTab({ ...NO_FILTERS, product: "Conveyor" });
    expect(select("Product").value).toBe("Conveyor");
    expect(screen.queryByText("AutoStore guide")).toBeNull();
    expect(screen.queryByText("Pick station EDI guide")).toBeNull();
  });

  it("drops a linked Integration Type the picker doesn't offer", () => {
    renderTab({ ...NO_FILTERS, integrationTypeId: "00000000-0000-7000-8000-0000000000ff" });
    expect(select("Integration Type").value).toBe("");
    expect(screen.getByText("AutoStore guide")).toBeTruthy();
    expect(screen.getByText("Pick station EDI guide")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("opens unfiltered without a link", () => {
    renderTab();
    expect(select("Product").value).toBe("");
    expect(screen.getByText("AutoStore guide")).toBeTruthy();
    expect(screen.getByText("Pick station EDI guide")).toBeTruthy();
  });

  it("drops linked filters with Clear filters, with no axe violations", async () => {
    const { container } = renderTab({
      ...NO_FILTERS,
      product: "Pick station",
      integrationTypeId: EDI.id,
    });
    expect(await axeViolations(container)).toEqual([]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("AutoStore guide")).toBeTruthy();
    expect(screen.getByText("Pick station EDI guide")).toBeTruthy();
  });
});

describe("SourcesTab linked Source (Story 3.6)", () => {
  it("opens the Source the Graph's Open source links to", async () => {
    renderTab(NO_FILTERS, SOURCES[1].id);
    expect(await screen.findByRole("heading", { name: "Pick station EDI guide" })).toBeTruthy();
  });
});
