import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DenialFilters } from "@/lib/admin";
import { axeViolations } from "@/test/axe";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn(), back: vi.fn() }),
}));

import { DENIAL_RANGE_ERROR, SELECTED_AGENT, ToolDenialsFilters } from "./tool-denials-filters";

const AGENTS = [
  { agent_id: "engineering_agent", name: "Engineering Agent" },
  { agent_id: "pm_agent", name: "PM Agent" },
];

function renderFilters(filters: DenialFilters = {}) {
  return render(<ToolDenialsFilters filters={filters} agents={AGENTS} />);
}

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
function lastHref() {
  expect(replace.mock.lastCall?.[1]).toEqual({ scroll: false });
  return replace.mock.lastCall?.[0];
}

beforeEach(() => replace.mockReset());

describe("ToolDenialsFilters", () => {
  it("filters by Agent through the URL, on page 1", async () => {
    const u = userEvent.setup();
    const { container } = renderFilters({ from: "2026-10-01" });
    const agent = screen.getByLabelText("Agent") as HTMLSelectElement;
    expect(within(agent).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any agent",
      "engineering_agent",
      "pm_agent",
    ]);
    await u.selectOptions(agent, "pm_agent");
    expect(lastHref()).toBe("/admin/agents/denials?agent_id=pm_agent&from=2026-10-01");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("filters by date; a reversed range is not applied and says why", async () => {
    const { container } = renderFilters({ agent_id: "pm_agent" });
    fireEvent.change(input("From (UTC)"), { target: { value: "2026-10-20" } });
    expect(lastHref()).toBe("/admin/agents/denials?agent_id=pm_agent&from=2026-10-20");
    replace.mockReset();
    fireEvent.change(input("To (UTC)"), { target: { value: "2026-10-10" } });
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(DENIAL_RANGE_ERROR);
    expect(input("To (UTC)").getAttribute("aria-invalid")).toBe("true");
    expect(await axeViolations(container)).toEqual([]);
    fireEvent.change(input("To (UTC)"), { target: { value: "2026-10-24" } });
    expect(lastHref()).toBe(
      "/admin/agents/denials?agent_id=pm_agent&from=2026-10-20&to=2026-10-24",
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps an unknown agent from the URL and clears every filter", async () => {
    const u = userEvent.setup();
    renderFilters({ agent_id: "old_agent", to: "2026-10-24" });
    const agent = screen.getByLabelText("Agent") as HTMLSelectElement;
    expect(agent.value).toBe("old_agent");
    const unknown = `old_agent (${SELECTED_AGENT})`;
    expect(within(agent).getByRole("option", { name: unknown })).toBeTruthy();
    await u.click(screen.getByRole("link", { name: "Clear filters" }));
    expect(lastHref()).toBe("/admin/agents/denials");
    expect(input("To (UTC)").value).toBe("");
  });

  it("offers no Clear filters link without filters", () => {
    renderFilters();
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
  });
});
