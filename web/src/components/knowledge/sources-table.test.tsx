import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EMPTY_STATE, NO_MATCHES, type KnowledgeSource } from "@/lib/knowledge-sources";
import { axeViolations } from "@/test/axe";
import { source } from "@/test/knowledge-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { SourcesTable } from "./sources-table";

vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));

const SOURCES: KnowledgeSource[] = [
  source(1, { title: "Old guide", stale: true, last_reviewed_on: "2025-01-01" }),
  source(2, { title: "Retired guide", retired: true, status: "retired", retired_reason: "Old" }),
  source(3, { title: "Broken guide", parse: { status: "failed", error_code: "no_text" } }),
];

function renderTable(sources: KnowledgeSource[] = SOURCES, total = sources.length) {
  const onOpen = vi.fn();
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <SourcesTable sources={sources} total={total} selectedId={null} onOpen={onOpen} />
    </ShellProviders>,
  );
  return { onOpen, user: userEvent.setup(), ...utils };
}

const rowOf = (title: string) => screen.getByRole("button", { name: title }).closest("tr")!;

describe("SourcesTable", () => {
  it("shows the empty state when there are no Sources at all", () => {
    renderTable([], 0);
    expect(screen.getByText(EMPTY_STATE)).toBeTruthy();
  });

  it("says when the filters hide every Source", () => {
    renderTable([], 3);
    expect(screen.getByText(NO_MATCHES)).toBeTruthy();
  });

  it("labels stale and retired Sources with an icon and text, not colour alone", () => {
    renderTable();
    const stale = within(rowOf("Old guide")).getByText("Stale");
    expect(stale.closest("[data-label=stale]")?.querySelector("svg")).toBeTruthy();
    const retired = within(rowOf("Retired guide")).getByText("Retired");
    expect(retired.closest("[data-label=retired]")?.querySelector("svg")).toBeTruthy();
    expect(within(rowOf("Broken guide")).queryByText("Stale")).toBeNull();
    expect(within(rowOf("Broken guide")).queryByText("Retired")).toBeNull();
  });

  it("shows the parse pill and the reason for a failed parse", () => {
    renderTable();
    const row = rowOf("Broken guide");
    expect(within(row).getByText("Parse failed")).toBeTruthy();
    expect(within(row).getByText("No text found — scanned PDF?")).toBeTruthy();
  });

  it("j/k move between rows and Enter opens via the keyboard", async () => {
    const { user, onOpen } = renderTable();
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Old guide" }));
    await user.keyboard("j");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Retired guide" }));
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(SOURCES[1], true);
  });

  it("has no axe violations", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
  });
});
