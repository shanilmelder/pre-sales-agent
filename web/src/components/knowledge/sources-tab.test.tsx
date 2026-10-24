import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";
import { source } from "@/test/knowledge-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { SourcesTab } from "./sources-tab";

vi.mock("@/app/knowledge/actions", () => ({
  addVersion: vi.fn(),
  editSource: vi.fn(),
  loadSource: vi.fn(),
  loadSources: vi.fn(),
  loadText: vi.fn(),
  markReviewed: vi.fn(),
  registerSource: vi.fn(),
  retireSource: vi.fn(),
  retryEmbed: vi.fn(),
  retryParse: vi.fn(),
  searchOwners: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => ({ loadOpportunity: vi.fn(), updateOpportunity: vi.fn() }));

const SAP = "00000000-0000-7000-8000-000000000001";
const REST = "00000000-0000-7000-8000-000000000002";
const TYPES = [
  { id: SAP, name: "SAP IDoc" },
  { id: REST, name: "REST API" },
];
const REST_TAG = { id: REST, code: "REST", name: "REST API", retired: false };
const SOURCES = [
  source(1, { title: "AutoStore SAP guide" }),
  source(2, { title: "AutoStore REST guide", integration_types: [REST_TAG] }),
  source(3, { title: "HubSpot REST guide", product: "HubSpot", integration_types: [REST_TAG] }),
];

function renderTab(initialFilters?: { product?: string; integrationTypeId?: string }) {
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <SourcesTab
        initialSources={SOURCES}
        integrationTypes={TYPES}
        me={{ id: "00000000-0000-7000-8000-000000000201", roles: ["platform_administrator"] }}
        initialFilters={initialFilters}
      />
    </ShellProviders>,
  );
  return { user: userEvent.setup(), ...utils };
}

const shown = () =>
  Array.from(document.querySelectorAll("button[data-source-row]")).map((b) => b.textContent);
const valueOf = (label: string) => (screen.getByLabelText(label) as HTMLSelectElement).value;

describe("SourcesTab filters", () => {
  it("starts from the filters a Coverage link carries", async () => {
    const { container } = renderTab({ product: "autostore", integrationTypeId: REST });
    expect(valueOf("Product")).toBe("AutoStore");
    expect(valueOf("Integration Type")).toBe(REST);
    expect(shown()).toEqual(["AutoStore REST guide"]);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("keeps a seeded product no Source has yet, matching nothing", () => {
    renderTab({ product: "Zebra WMS", integrationTypeId: SAP });
    expect(valueOf("Product")).toBe("Zebra WMS");
    expect(shown()).toEqual([]);
    expect(screen.getByText("No Knowledge Sources match these filters.")).toBeTruthy();
  });

  it("ignores an Integration Type that isn't active", () => {
    renderTab({ integrationTypeId: "00000000-0000-7000-8000-0000000000ff" });
    expect(valueOf("Integration Type")).toBe("");
    expect(shown()).toHaveLength(3);
  });

  it("shows everything with no filters, and Clear filters drops seeded ones", async () => {
    const { user } = renderTab({ product: "HubSpot" });
    expect(shown()).toEqual(["HubSpot REST guide"]);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(shown()).toHaveLength(3);
  });
});
