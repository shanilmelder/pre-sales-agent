import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EMPTY_STATE, type CatalogueEntry } from "@/lib/catalogue";
import { entry } from "@/test/catalogue-fixtures";
import { axeViolations } from "@/test/axe";

import { ShellProviders } from "../shell/shell-context";
import { CatalogueTable } from "./catalogue-table";

const ENTRIES: CatalogueEntry[] = [
  entry(1, { name: "SAP IDoc", current_version: 3 }),
  entry(2, { name: "REST API" }),
  entry(3, {
    kind: "work_package",
    name: "Mapping",
    status: "retired",
    retired: true,
    retired_reason: "Old",
  }),
];

function renderTable(entries: CatalogueEntry[] = ENTRIES, singleKeyShortcuts = true) {
  const onOpen = vi.fn();
  const utils = render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <CatalogueTable entries={entries} selectedId={null} onOpen={onOpen} />
    </ShellProviders>,
  );
  return { onOpen, user: userEvent.setup(), ...utils };
}

const row = (name: string) => screen.getByRole("button", { name });

describe("CatalogueTable", () => {
  it("shows two groups with code, name, version and status", () => {
    renderTable();
    expect(screen.getByRole("heading", { name: "Integration Types" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Work Packages" })).toBeTruthy();
    expect(screen.getByText("CODE-1")).toBeTruthy();
    expect(screen.getByText("v3")).toBeTruthy();
    expect(screen.getAllByText("Active")).toHaveLength(2);
    expect(screen.getByText("Retired")).toBeTruthy();
  });

  it("shows the empty state", () => {
    renderTable([]);
    expect(screen.getByText(EMPTY_STATE)).toBeTruthy();
  });

  it("j/k move across both groups and Enter opens the inspector via the keyboard", async () => {
    const { user, onOpen } = renderTable();
    await user.tab();
    expect(document.activeElement).toBe(row("SAP IDoc"));
    await user.keyboard("jj");
    expect(document.activeElement).toBe(row("Mapping"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("REST API"));
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(ENTRIES[1], true);
  });

  it("ignores j/k when single-key shortcuts are off, but arrows still work", async () => {
    const { user } = renderTable(ENTRIES, false);
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("SAP IDoc"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("REST API"));
  });

  it("a click opens without the keyboard flag", async () => {
    const { user, onOpen } = renderTable();
    await user.click(row("Mapping"));
    expect(onOpen).toHaveBeenCalledWith(ENTRIES[2], false);
  });

  it("passes axe", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
  });
});
