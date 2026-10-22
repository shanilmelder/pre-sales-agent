import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";
import { checklist, VERSION_1 } from "@/test/checklist-fixtures";
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
