import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";
import { checklist, TYPE_ID, VERSION_1 } from "@/test/checklist-fixtures";
import { permissionsFor } from "@/test/permissions";

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { ChecklistsTab } from "./checklists-tab";

const actions = vi.hoisted(() => ({
  createChecklist: vi.fn(),
  loadChecklist: vi.fn(),
  loadChecklistVersion: vi.fn(),
  loadChecklists: vi.fn(),
  openDraft: vi.fn(),
  publishChecklist: vi.fn(),
  retireChecklist: vi.fn(),
  saveDraft: vi.fn(),
}));
vi.mock("@/app/knowledge/checklists/actions", () => actions);
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
  loadSources: vi.fn(),
  retryParse: vi.fn(),
}));

function renderTab(roles: Parameters<typeof permissionsFor>[0]) {
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <ChecklistsTab
        initialChecklists={[checklist(1, { name: "Security baseline" })]}
        catalogue={[]}
        permissions={permissionsFor(roles)}
      />
      <RightPane />
    </ShellProviders>,
  );
  return { user: userEvent.setup(), ...utils };
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.loadChecklist.mockResolvedValue({
    kind: "ok",
    checklist: checklist(1),
    versions: [VERSION_1],
  });
});

describe("ChecklistsTab", () => {
  it("lets an author press c, name a Checklist and create it", async () => {
    const created = checklist(2, { name: "Delivery risks", current_version: null });
    actions.createChecklist.mockResolvedValue({ kind: "ok", checklist: created });
    const { user } = renderTab(["security_reviewer"]);
    await user.keyboard("c");
    const name = await screen.findByLabelText("Name");
    await waitFor(() => expect(document.activeElement).toBe(name));
    await user.type(name, "Delivery risks");
    await user.selectOptions(screen.getByLabelText("Domain"), "delivery");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(actions.createChecklist).toHaveBeenCalledWith({
        name: "Delivery risks",
        domain: "delivery",
      }),
    );
    expect(await screen.findByRole("button", { name: "Delivery risks" })).toBeTruthy();
  });

  it("offers no create control to other roles, and c does nothing", async () => {
    const { user, container } = renderTab(["sales_representative"]);
    expect(screen.queryByRole("button", { name: "New Checklist" })).toBeNull();
    await user.keyboard("c");
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("ChecklistsTab filters", () => {
  const OTHER_TYPE = "00000000-0000-7000-8000-000000000009";
  const CHECKLISTS = [
    checklist(1, { name: "AutoStore SAP" }),
    checklist(2, { name: "HubSpot only", products: ["HubSpot"], integration_types: [] }),
    checklist(3, { name: "Retail", products: [], integration_types: [], industry: "Retail" }),
    checklist(4, { name: "Old SAP", status: "retired", retired: true, retired_reason: "Old" }),
  ];
  const CATALOGUE = [
    { id: TYPE_ID, kind: "integration_type" as const, name: "SAP IDoc" },
    { id: OTHER_TYPE, kind: "integration_type" as const, name: "REST API" },
    { id: "00000000-0000-7000-8000-000000000002", kind: "work_package" as const, name: "Testing" },
  ];

  function renderFiltered(initialFilters?: { product?: string; integrationTypeId?: string }) {
    const utils = render(
      <ShellProviders singleKeyShortcuts>
        <ChecklistsTab
          initialChecklists={CHECKLISTS}
          catalogue={CATALOGUE}
          permissions={permissionsFor(["pm_reviewer"])}
          initialFilters={initialFilters}
        />
      </ShellProviders>,
    );
    return { user: userEvent.setup(), ...utils };
  }

  const shown = () =>
    Array.from(document.querySelectorAll("button[data-checklist-row]")).map((b) => b.textContent);

  it("starts from the filters a Coverage link carries", async () => {
    const { container } = renderFiltered({ product: "hubspot", integrationTypeId: OTHER_TYPE });
    expect((screen.getByLabelText("Product") as HTMLSelectElement).value).toBe("HubSpot");
    expect((screen.getByLabelText("Integration Type") as HTMLSelectElement).value).toBe(OTHER_TYPE);
    expect(shown()).toEqual(["HubSpot only"]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("offers only Integration Types, and a seeded product no Checklist names", () => {
    renderFiltered({ product: "Zebra WMS" });
    const types = Array.from((screen.getByLabelText("Integration Type") as HTMLSelectElement).options);
    expect(types.map((o) => o.textContent)).toEqual(["All", "SAP IDoc", "REST API"]);
    expect((screen.getByLabelText("Product") as HTMLSelectElement).value).toBe("Zebra WMS");
    expect(screen.getByText("No Checklists match these filters.")).toBeTruthy();
  });

  it("ignores an Integration Type that isn't in the catalogue", () => {
    renderFiltered({ integrationTypeId: "00000000-0000-7000-8000-0000000000ff" });
    expect((screen.getByLabelText("Integration Type") as HTMLSelectElement).value).toBe("");
    expect(shown()).toHaveLength(4);
  });

  it("filters as the selects change, and Clear filters shows every Checklist", async () => {
    const { user } = renderFiltered();
    expect(shown()).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    await user.selectOptions(screen.getByLabelText("Integration Type"), TYPE_ID);
    expect(shown()).toEqual(["AutoStore SAP", "HubSpot only"]);
    await user.selectOptions(screen.getByLabelText("Product"), "AutoStore");
    expect(shown()).toEqual(["AutoStore SAP"]);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    // With no filter the retired Checklist shows again.
    expect(shown()).toHaveLength(4);
    expect(shown()).toContain("Old SAP");
  });
});
