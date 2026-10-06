import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_STATE } from "@/lib/catalogue";
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
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders } from "../shell/shell-context";
import { CatalogueAdmin } from "./catalogue-admin";

const ENTRIES = [
  entry(1, { name: "SAP IDoc" }),
  entry(2, { name: "Mapping", kind: "work_package" }),
];

function ui(entries = ENTRIES, singleKeyShortcuts = true) {
  return (
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <LiveRegionProvider>
        <button type="button" id={RIGHT_PANE_TOGGLE_ID}>
          Toggle
        </button>
        <CatalogueAdmin initialEntries={entries} />
        <RightPane />
      </LiveRegionProvider>
    </ShellProviders>
  );
}

const pane = () => screen.queryByRole("complementary", { name: "Details" });

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.loadEntry.mockResolvedValue({ kind: "ok", entry: ENTRIES[0], versions: [] });
});

describe("CatalogueAdmin", () => {
  it("Enter opens the inspector and focuses it; closing returns focus to the row", async () => {
    const u = userEvent.setup();
    render(ui());
    await u.tab(); // Toggle
    await u.tab(); // "New entry"
    await u.tab(); // first row
    await u.keyboard("{Enter}");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(pane()!).getByRole("heading", { name: "SAP IDoc" }),
      ),
    );
    await u.click(within(pane()!).getByRole("button", { name: "Close right pane" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "SAP IDoc" })),
    );
  });

  it("c opens the create form; creating adds the entry and opens it", async () => {
    const created = entry(3, { name: "Fresh", code: "FRESH" });
    actions.createEntry.mockResolvedValue({ kind: "ok", entry: created });
    const u = userEvent.setup();
    render(ui());
    await u.keyboard("c");
    const form = await screen.findByRole("form", { name: "New catalogue entry" });
    expect(document.activeElement).toBe(within(form).getByRole("combobox", { name: "Kind" }));
    await u.type(within(form).getByRole("textbox", { name: "Code" }), "FRESH");
    await u.type(within(form).getByRole("textbox", { name: "Name" }), "Fresh");
    await u.type(within(form).getByRole("textbox", { name: "Definition" }), "A new one.");
    await u.click(within(form).getByRole("button", { name: "Create" }));
    expect(actions.createEntry).toHaveBeenCalledWith({
      kind: "integration_type",
      code: "FRESH",
      name: "Fresh",
      definition: "A new one.",
    });
    expect(await screen.findByRole("button", { name: "Fresh" })).toBeTruthy();
    await waitFor(() =>
      expect(within(pane()!).getByRole("heading", { name: "Fresh", level: 3 })).toBeTruthy(),
    );
  });

  it("a duplicate on create shows the sentence and adds nothing", async () => {
    actions.createEntry.mockResolvedValue({
      kind: "duplicate",
      detail: "An active Work Package with this name already exists",
    });
    const u = userEvent.setup();
    render(ui());
    await u.keyboard("c");
    const form = await screen.findByRole("form", { name: "New catalogue entry" });
    await u.selectOptions(within(form).getByRole("combobox", { name: "Kind" }), "work_package");
    await u.type(within(form).getByRole("textbox", { name: "Code" }), "X");
    await u.type(within(form).getByRole("textbox", { name: "Name" }), "Mapping");
    await u.type(within(form).getByRole("textbox", { name: "Definition" }), "d");
    await u.click(within(form).getByRole("button", { name: "Create" }));
    expect(
      await screen.findByText("An active Work Package with this name already exists"),
    ).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Mapping" })).toHaveLength(1);
  });

  it("Esc cancels the create form", async () => {
    const u = userEvent.setup();
    render(ui());
    await u.keyboard("c");
    await screen.findByRole("form", { name: "New catalogue entry" });
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("form")).toBeNull());
  });

  it("c does nothing when single-key shortcuts are off", async () => {
    const u = userEvent.setup();
    render(ui(ENTRIES, false));
    await u.keyboard("c");
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("the empty state names the c shortcut", () => {
    render(ui([]));
    expect(screen.getByText(EMPTY_STATE)).toBeTruthy();
  });

  it("passes axe with the create form open", async () => {
    const u = userEvent.setup();
    const { container } = render(ui());
    await u.keyboard("c");
    await screen.findByRole("form", { name: "New catalogue entry" });
    expect(await axeViolations(container)).toEqual([]);
  });
});
