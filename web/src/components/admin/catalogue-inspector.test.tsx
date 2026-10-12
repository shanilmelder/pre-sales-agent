import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogueEntry, CatalogueVersion } from "@/lib/catalogue";
import { entry } from "@/test/catalogue-fixtures";
import { axeViolations } from "@/test/axe";

const actions = vi.hoisted(() => ({
  loadEntry: vi.fn(),
  editEntry: vi.fn(),
  retireEntry: vi.fn(),
  reactivateEntry: vi.fn(),
  createEntry: vi.fn(),
}));
vi.mock("@/app/admin/catalogue/actions", () => actions);
// InlineField imports the Opportunity actions, which need the server.
vi.mock("@/app/opportunities/actions", () => ({ loadOpportunity: vi.fn(), updateOpportunity: vi.fn() }));

import { LiveRegionProvider } from "../shell/live-region";
import { CatalogueInspector } from "./catalogue-inspector";

const DUPLICATE = "An active Integration Type with this name already exists";
const ENTRY = entry(1, {
  name: "SAP IDoc",
  definition: "Documents over IDoc.",
  row_version: 2,
  current_version: 2,
});
const VERSIONS: CatalogueVersion[] = [
  {
    version: 2,
    name: "SAP IDoc",
    definition: "Documents over IDoc.",
    changed_by_id: "u1",
    changed_by_name: "[ADMIN]",
    changed_at: "2026-10-06T11:00:00Z",
  },
  {
    version: 1,
    name: "SAP IDoc",
    definition: "Old.",
    changed_by_id: "u1",
    changed_by_name: "[ADMIN]",
    changed_at: "2026-10-06T10:00:00Z",
  },
];

function renderInspector(value: CatalogueEntry = ENTRY) {
  const onChange = vi.fn();
  const utils = render(
    <LiveRegionProvider>
      <CatalogueInspector entry={value} onChange={onChange} />
    </LiveRegionProvider>,
  );
  return { onChange, user: userEvent.setup(), ...utils };
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.loadEntry.mockResolvedValue({ kind: "ok", entry: ENTRY, versions: VERSIONS });
});

describe("CatalogueInspector", () => {
  it("shows the entry and its version history", async () => {
    renderInspector();
    expect(screen.getByRole("heading", { name: "SAP IDoc", level: 3 })).toBeTruthy();
    expect(await screen.findByText("Version 2")).toBeTruthy();
    expect(screen.getByText("Version 1")).toBeTruthy();
    expect(screen.getByText(/\(current\)/)).toBeTruthy();
  });

  it("saves an edited definition on Enter with the row version", async () => {
    const saved = { ...ENTRY, definition: "New text", current_version: 3, row_version: 3 };
    actions.editEntry.mockResolvedValue({ kind: "ok", entry: saved });
    const { user, onChange } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Edit definition" }));
    const input = screen.getByRole("textbox", { name: "Definition" });
    await user.clear(input);
    await user.type(input, "New text{Enter}");
    expect(actions.editEntry).toHaveBeenCalledWith({
      entryId: ENTRY.id,
      rowVersion: 2,
      definition: "New text",
    });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(saved));
  });

  it("Esc reverts without saving", async () => {
    const { user } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "x{Escape}");
    expect(actions.editEntry).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Edit name" })).toBeTruthy();
  });

  it("a duplicate name shows the sentence under the field and changes nothing", async () => {
    actions.editEntry.mockResolvedValue({ kind: "duplicate", detail: DUPLICATE });
    const { user, onChange } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    const input = screen.getByRole("textbox", { name: "Name" });
    await user.clear(input);
    await user.type(input, "REST{Enter}");
    expect(await screen.findByText(DUPLICATE)).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a blank name is refused before any request", async () => {
    const { user } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.keyboard("{Enter}");
    expect(await screen.findByText("The name is required.")).toBeTruthy();
    expect(actions.editEntry).not.toHaveBeenCalled();
  });

  it("a 412 shows who changed it and Reload brings the current entry", async () => {
    actions.editEntry.mockResolvedValue({ kind: "stale", changedBy: "[OTHER ADMIN]" });
    const fresh = { ...ENTRY, name: "Fresh", row_version: 3, current_version: 3 };
    const { user, onChange } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "!{Enter}");
    expect(await screen.findByText("Changed by [OTHER ADMIN] since you opened it.")).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();

    actions.loadEntry.mockResolvedValue({ kind: "ok", entry: fresh, versions: VERSIONS });
    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(fresh));
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
  });

  it("retiring needs a reason and sends it with the row version", async () => {
    const retired = {
      ...ENTRY,
      status: "retired" as const,
      retired: true,
      retired_reason: "Superseded",
      row_version: 3,
    };
    actions.retireEntry.mockResolvedValue({ kind: "ok", entry: retired });
    const { user, onChange } = renderInspector();
    await user.click(screen.getByRole("button", { name: "Retire" }));
    await user.click(screen.getByRole("button", { name: "Confirm retire" }));
    expect(await screen.findByText("The reason is required.")).toBeTruthy();
    expect(actions.retireEntry).not.toHaveBeenCalled();
    await user.type(
      screen.getByRole("textbox", { name: "Reason for retiring" }),
      "Superseded{Enter}",
    );
    expect(actions.retireEntry).toHaveBeenCalledWith({
      entryId: ENTRY.id,
      rowVersion: 2,
      reason: "Superseded",
    });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(retired));
  });

  it("a retired entry shows Retired with its reason and can be reactivated", async () => {
    const retired = {
      ...ENTRY,
      status: "retired" as const,
      retired: true,
      retired_reason: "Superseded",
    };
    const back = { ...ENTRY, row_version: 3 };
    actions.reactivateEntry.mockResolvedValue({ kind: "ok", entry: back });
    const { user, onChange } = renderInspector(retired);
    expect(screen.getAllByText("Retired").length).toBeGreaterThan(0);
    expect(screen.getByText("Retired: Superseded")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retire" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Reactivate" }));
    expect(actions.reactivateEntry).toHaveBeenCalledWith({ entryId: ENTRY.id, rowVersion: 2 });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(back));
  });

  it("a reactivate refused as a duplicate shows the sentence", async () => {
    const retired = { ...ENTRY, status: "retired" as const, retired: true, retired_reason: "Old" };
    actions.reactivateEntry.mockResolvedValue({ kind: "duplicate", detail: DUPLICATE });
    const { user } = renderInspector(retired);
    await user.click(screen.getByRole("button", { name: "Reactivate" }));
    expect(await screen.findByText(DUPLICATE)).toBeTruthy();
  });

  it("passes axe", async () => {
    const { container } = renderInspector();
    await screen.findByText("Version 2");
    expect(await axeViolations(container)).toEqual([]);
  });
});
