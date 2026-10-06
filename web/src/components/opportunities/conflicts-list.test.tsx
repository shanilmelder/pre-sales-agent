import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Conflict, ConflictPosition, ConflictsView } from "@/lib/conflicts";
import { axeViolations } from "@/test/axe";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/conflicts",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { ConflictsList, ConflictsSection } from "./conflicts-list";

const R4 = {
  id: "00000000-0000-7000-8000-0000000000b4",
  version: 1,
  label: "R4",
  excerpt: "[EXCERPT R4]",
};

function agentPosition(
  n: number,
  agent: string,
  summary: string,
  value: number | null,
  requirement: ConflictPosition["requirement"] = R4,
): ConflictPosition {
  return {
    position: n,
    source: "assessment",
    agent,
    assessment_id: `00000000-0000-7000-8000-00000000a${String(n).padStart(3, "0")}`,
    assessment_version: 2,
    estimate_version_id: null,
    estimate_version: null,
    summary,
    value,
    requirement,
  };
}

function conflict(n: number, overrides: Partial<Conflict>): Conflict {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    type: "scope",
    severity: "medium",
    status: "open",
    detected_by: "rule",
    summary: `[SUMMARY ${n}]`,
    run_id: "00000000-0000-7000-8000-0000000000f1",
    previous_conflict_id: null,
    resolution_reason: null,
    resolved_at: null,
    created_at: "2026-10-07T09:00:00Z",
    requirement: R4,
    positions: [
      agentPosition(1, "engineering_agent", "24 h", 24),
      agentPosition(2, "pm_agent", "Not sized", null),
    ],
    ...overrides,
  };
}

const CLASH = conflict(1, {
  type: "assumption",
  severity: "high",
  requirement: null,
  positions: [
    agentPosition(1, "engineering_agent", "Proceed", null, null),
    agentPosition(2, "security_agent", "Do not proceed", null, null),
  ],
});
const SCOPE = conflict(2, {});
const GONE = conflict(3, {
  status: "resolved",
  resolution_reason: "No longer present in PM Assessment v2",
  resolved_at: "2026-10-07T10:00:00Z",
});
const VIEW: ConflictsView = { conflicts: [CLASH, SCOPE, GONE], open_count: 2 };

function renderSection(initial: ConflictsView = VIEW, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <ConflictsSection initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (text: RegExp) => screen.getByRole("button", { name: text });
const pane = () => screen.getByRole("complementary", { name: "Details" });

describe("ConflictsSection", () => {
  it("lists Open and Resolved sections of rows with type, severity, status and positions", async () => {
    const { container } = renderSection();

    const open = screen.getByRole("grid", { name: "Open Conflicts" });
    expect(within(open).getAllByRole("row").map((r) => r.textContent)).toEqual([
      "AssumptionHighOpenEngineering: proceed · Security: do not proceed",
      "ScopeMediumOpenR4Engineering: 24 h · PM: not sized",
    ]);
    const resolved = screen.getByRole("grid", { name: "Resolved Conflicts" });
    expect(within(resolved).getAllByRole("row").map((r) => r.textContent)).toEqual([
      "ScopeMediumResolvedR4Engineering: 24 h · PM: not sized",
    ]);
    expect(screen.getByRole("heading", { level: 3, name: "Open 2" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "Resolved 1" })).toBeTruthy();
    // Status pills pair an icon with a label; blocker red only on Open.
    const statuses = Array.from(container.querySelectorAll("[data-status]"));
    expect(statuses.map((s) => s.getAttribute("data-status"))).toEqual([
      "open",
      "open",
      "resolved",
    ]);
    for (const pill of statuses) expect(pill.querySelector("svg")).toBeTruthy();
    expect(statuses[0]!.querySelector("svg")?.getAttribute("class")).toContain("text-blocker");
    expect(statuses[2]!.querySelector("svg")?.getAttribute("class")).toContain("text-resolved");
    expect(row(/Scope.*Open/).className).toContain("min-h-row");
    // Read-only: no text fields; the rows are the only buttons.
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the empty sentence without Conflicts", async () => {
    const { container } = renderSection({ conflicts: [], open_count: 0 });
    expect(screen.getByText("No Conflicts between the specialist Assessments.")).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Enter opens the Conflict in the right pane with equal-width position cards", async () => {
    const user = userEvent.setup();
    const { container } = renderSection();

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", { level: 3, name: "Scope Conflict" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(row(/Scope.*Open/).closest("[role=row]")?.getAttribute("aria-selected")).toBe("true");
    expect(within(inspector).getByText("[SUMMARY 2]")).toBeTruthy();
    const cards = within(inspector).getAllByRole("listitem");
    expect(cards.map((c) => c.textContent)).toEqual([
      "Engineering24 hR4[EXCERPT R4]Engineering Assessment v2",
      "PMNot sizedR4[EXCERPT R4]PM Assessment v2",
    ]);
    expect((cards[0]!.parentElement as HTMLElement).style.gridTemplateColumns).toBe(
      "repeat(2, minmax(0, 1fr))",
    );
    const section = within(inspector).getByRole("region", { name: "Scope Conflict" });
    expect(within(section).queryByRole("button")).toBeNull();
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("closing the pane after a keyboard open returns focus to the row; not after a click", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(pane()).getByRole("heading", { level: 3, name: "Scope Conflict" }),
      ),
    );
    await user.click(within(pane()).getByRole("button", { name: "Close right pane" }));
    await waitFor(() => expect(document.activeElement).toBe(row(/Scope.*Open/)));

    // A mouse open: closing leaves focus where the click put it, not on the row.
    await user.click(row(/Assumption/));
    await waitFor(() => expect(pane()).toBeTruthy());
    const close = within(pane()).getByRole("button", { name: "Close right pane" });
    await user.click(close);
    await waitFor(() =>
      expect(screen.queryByRole("heading", { level: 3, name: "Assumption Conflict" })).toBeNull(),
    );
    expect(document.activeElement).not.toBe(row(/Assumption/));
    expect(document.activeElement).not.toBe(row(/Scope.*Open/));
  });

  it("a resolved Conflict shows its reason", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(row(/Scope.*Resolved/));
    expect(
      within(pane()).getByText("No longer present in PM Assessment v2"),
    ).toBeTruthy();
    expect(document.activeElement).toBe(row(/Scope.*Resolved/));
  });
});

describe("ConflictsList", () => {
  it("j/k and the arrows move between rows; j/k off with shortcuts off", async () => {
    const user = userEvent.setup();
    const items = [CLASH, SCOPE];
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <ConflictsList label="Open Conflicts" items={items} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(/Assumption/));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/Scope/));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(/Assumption/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/Scope/));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ConflictsList label="Open Conflicts" items={items} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/Assumption/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/Scope/));
  });
});
