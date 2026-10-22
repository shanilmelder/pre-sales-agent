import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EMPTY_STATE, EMPTY_STATE_AUTHOR, type Checklist } from "@/lib/checklists";
import { axeViolations } from "@/test/axe";
import { checklist, item, withDraft } from "@/test/checklist-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { ChecklistsTable } from "./checklists-table";

vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));

const CHECKLISTS: Checklist[] = [
  checklist(1, { name: "Security baseline" }),
  checklist(2, {
    name: "Retired list",
    retired: true,
    status: "retired",
    retired_reason: "Old",
  }),
  checklist(3, {
    name: "Brand new",
    current_version: null,
    items: [],
    item_count: 0,
    mandatory_count: 0,
  }),
  withDraft(checklist(4, { name: "Being edited", items: [item(1)] })),
];

function renderTable(checklists: Checklist[] = CHECKLISTS, mayAuthor = true) {
  const onOpen = vi.fn();
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <ChecklistsTable checklists={checklists} selectedId={null} mayAuthor={mayAuthor} onOpen={onOpen} />
    </ShellProviders>,
  );
  return { onOpen, user: userEvent.setup(), ...utils };
}

const rowOf = (name: string) => screen.getByRole("button", { name }).closest("tr")!;

describe("ChecklistsTable", () => {
  it("shows the empty state, inviting authors to press c", () => {
    const { unmount } = renderTable([], true);
    expect(screen.getByText(EMPTY_STATE_AUTHOR)).toBeTruthy();
    unmount();
    renderTable([], false);
    expect(screen.getByText(EMPTY_STATE)).toBeTruthy();
  });

  it("shows the Mandatory count as an icon and a label, never colour alone", () => {
    renderTable();
    const label = within(rowOf("Security baseline")).getByText("1 Mandatory");
    expect(label.closest("[data-label=mandatory]")?.querySelector("svg")).toBeTruthy();
    expect(within(rowOf("Being edited")).queryByText(/Mandatory/)).toBeNull();
  });

  it("shows the status: published version, never published, retired, and a draft in progress", () => {
    renderTable();
    expect(within(rowOf("Security baseline")).getByText("Published v1")).toBeTruthy();
    expect(within(rowOf("Brand new")).getByText("Draft")).toBeTruthy();
    const retired = within(rowOf("Retired list")).getByText("Retired");
    expect(retired.closest("[data-label=retired]")?.querySelector("svg")).toBeTruthy();
    expect(within(rowOf("Being edited")).getByText("Draft").closest("[data-label=draft]")).toBeTruthy();
    expect(within(rowOf("Security baseline")).getByText("AutoStore · SAP IDoc")).toBeTruthy();
  });

  it("moves between rows with j/k and opens with Enter", async () => {
    const { user, onOpen } = renderTable();
    screen.getByRole("button", { name: "Security baseline" }).focus();
    await user.keyboard("j");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Retired list" }));
    await user.keyboard("k");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Security baseline" }));
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(CHECKLISTS[0], true);
  });

  it("has no axe violations", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
  });
});
