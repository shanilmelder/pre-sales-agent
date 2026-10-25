import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NO_DENIALS, THRESHOLD_EXCEEDED, type ToolDenial } from "@/lib/admin";
import { axeViolations } from "@/test/axe";

import { ToolDenialsTable } from "./tool-denials-table";

const OPP = "01a16ea4-dd68-7f04-8c34-a82544b2e521";
const RUN = "01a16ea4-e196-73c1-8898-7251e747c73b";

function denial(n: number, over: Partial<ToolDenial> = {}): ToolDenial {
  return {
    id: `01a16eb0-0000-7000-8000-00000000000${n}`,
    created_at: `2026-10-24T16:0${n}:00Z`,
    agent_id: "engineering_agent",
    semver: "0.1.0",
    config_version_id: "10000000-0000-7000-8000-000000000001",
    tool: "intake.requirement.list",
    reason: "tool_not_permitted",
    opportunity_id: OPP,
    run_id: RUN,
    task_id: `01a16eb1-0000-7000-8000-00000000000${n}`,
    threshold_exceeded: false,
    ...over,
  };
}

const rowOf = (id: string) => document.querySelector(`[data-denial-id="${id}"]`) as HTMLElement;

describe("ToolDenialsTable", () => {
  it("shows time, agent@version, tool, reason and the Opportunity and run links", async () => {
    const rows = [
      denial(3, { threshold_exceeded: true }),
      denial(2, {
        agent_id: "pm_agent",
        semver: null,
        reason: "unknown_tool",
        tool: "gaps.question.send",
      }),
      denial(1, { run_id: null }),
    ];
    const { container } = render(<ToolDenialsTable denials={rows} empty={NO_DENIALS} />);
    const table = screen.getByRole("table", { name: "Denied tool calls" });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Time",
      "Agent",
      "Tool action",
      "Reason",
      "Opportunity",
      "Run",
    ]);
    expect(within(table).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "engineering_agent@0.1.0",
      "pm_agent",
      "engineering_agent@0.1.0",
    ]);

    const newest = rowOf(rows[0].id);
    expect(within(newest).getByText("24 Oct 2026, 16:03 UTC")).toBeTruthy();
    expect(within(newest).getByText("intake.requirement.list")).toBeTruthy();
    const reason = within(newest).getByText("Not permitted");
    expect(reason.closest('[data-slot="pill"]')?.querySelector("svg")).toBeTruthy();
    const threshold = within(newest).getByText(THRESHOLD_EXCEEDED);
    expect(threshold.closest('[data-slot="pill"]')?.querySelector("svg")).toBeTruthy();
    expect(
      within(newest).getByRole("link", { name: "Opportunity 01a16ea4" }).getAttribute("href"),
    ).toBe(`/opportunities/${OPP}/overview`);
    expect(within(newest).getByRole("link", { name: "Run 01a16ea4" }).getAttribute("href")).toBe(
      `/opportunities/${OPP}/assessments`,
    );

    const unknown = rowOf(rows[1].id);
    expect(within(unknown).getByText("Unknown tool")).toBeTruthy();
    expect(within(unknown).queryByText(THRESHOLD_EXCEEDED)).toBeNull();
    const outside = rowOf(rows[2].id);
    expect(within(outside).queryByRole("link", { name: /^Run/ })).toBeNull();
    expect(within(outside).getByText("No run")).toBeTruthy();

    expect(screen.getByText(/never retried/)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the empty state and no table when there are no denials", async () => {
    const { container } = render(<ToolDenialsTable denials={[]} empty={NO_DENIALS} />);
    expect(screen.getByText("No denied tool calls.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});
