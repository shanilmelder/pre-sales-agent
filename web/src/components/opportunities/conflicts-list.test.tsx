import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConflictDecisionResult,
  ResolveConflictInput,
} from "@/app/opportunities/actions";
import type { Conflict, ConflictPosition, ConflictsView } from "@/lib/conflicts";
import { axeViolations } from "@/test/axe";

const resolveConflict = vi.hoisted(() =>
  vi.fn<(input: ResolveConflictInput) => Promise<ConflictDecisionResult>>(),
);
const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({
  resolveConflict,
  escalateConflict: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh,
  }),
  usePathname: () => "/opportunities/x/conflicts",
}));

import { ShellProviders } from "../shell/shell-context";
import { ConflictsList, ConflictsSection } from "./conflicts-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const R1 = { id: "00000000-0000-7000-8000-0000000000b1", version: 1, label: "R1", excerpt: "[R1]" };
const R4 = { id: "00000000-0000-7000-8000-0000000000b4", version: 1, label: "R4", excerpt: "[R4]" };

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
    finding: null,
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
    row_version: 1,
    resolved_by_name: null,
    chosen_position: null,
    entered_position: null,
    applied_hours: null,
    not_applied: null,
    previous_decision: null,
    escalated_to: null,
    escalated_by: null,
    escalation_reason: null,
    escalated_at: null,
    can_resolve: false,
    can_escalate: false,
    ...overrides,
  };
}

// The mockup: 2 open (effort on R1, security with no Requirement), 5 resolved.
const EFFORT = conflict(1, {
  type: "effort",
  severity: "high",
  summary: "[EFFORT ON R1]",
  requirement: R1,
  positions: [
    agentPosition(1, "engineering_agent", "96 h", 96, R1),
    agentPosition(2, "pm_agent", "40 h", 40, R1),
  ],
});
const SECURITY = conflict(2, {
  type: "security",
  summary: "[SECURITY]",
  requirement: null,
  positions: [
    agentPosition(1, "engineering_agent", "Proceed", null, null),
    agentPosition(2, "security_agent", "Do not proceed", null, null),
  ],
});
const DECIDED = conflict(3, {
  status: "resolved",
  summary: "[DECIDED]",
  resolved_by_name: "Alex Owner",
  chosen_position: 1,
  resolution_reason: "Matches the interface list.",
  resolved_at: "2026-10-07T10:00:00Z",
});
const GONE = conflict(4, {
  status: "resolved",
  summary: "[GONE]",
  resolution_reason: "No longer present in PM Assessment v2",
  resolved_at: "2026-10-07T10:00:00Z",
});
const RESOLVED = [
  DECIDED,
  GONE,
  ...[5, 6, 7].map((n) => conflict(n, { status: "resolved" })),
];
const VIEW: ConflictsView = {
  conflicts: [EFFORT, SECURITY, ...RESOLVED],
  open_count: 2,
  reviewers: [],
};

function renderSection(initial: ConflictsView = VIEW, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <ConflictsSection initial={initial} opportunityId={OPP_ID} />
    </ShellProviders>,
  );
}

const row = (text: RegExp) => screen.getByRole("button", { name: text });
const decisionCard = () => screen.getByTestId("conflict-decision-card");
const selectedOf = (button: HTMLElement) =>
  button.closest("[role=row]")?.getAttribute("aria-selected");

beforeEach(() => {
  resolveConflict.mockReset();
  refresh.mockReset();
});

describe("ConflictsSection", () => {
  it("mockup data: header counts, the open card, the first Conflict's decision card, Resolved 5", async () => {
    const { container } = renderSection();

    expect(screen.getByRole("heading", { level: 2, name: "Conflicts" })).toBeTruthy();
    expect(screen.getByText("2 open · 5 resolved")).toBeTruthy();

    const open = screen.getByRole("grid", { name: "Open Conflicts" });
    const rows = within(open).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "[EFFORT ON R1]Effort · R1Open",
      "[SECURITY]SecurityOpen",
    ]);
    // A 3px red bar on each open row; the first one is selected (primary tint).
    for (const r of rows) expect(r.className).toContain("shadow-[inset_3px_0_0_var(--blocker)]");
    expect(rows[0]!.getAttribute("aria-selected")).toBe("true");
    expect(rows[0]!.className).toContain("bg-primary-tint");
    expect(rows[1]!.getAttribute("aria-selected")).toBe("false");

    // The decision card shows the selected Conflict with two position cards.
    const card = decisionCard();
    expect(within(card).getByRole("heading", { level: 3, name: "[EFFORT ON R1]" })).toBeTruthy();
    expect(within(card).getByText("Effort Conflict · High severity")).toBeTruthy();
    expect(within(card).getAllByRole("listitem").map((c) => c.textContent)).toEqual([
      "Engineering AgentAssessment v296 hR1",
      "PM AgentAssessment v240 hR1",
    ]);
    expect((within(card).getAllByRole("listitem")[0]!.parentElement as HTMLElement).className)
      .toContain("md:grid-cols-2");

    expect(screen.getByRole("heading", { level: 3, name: "Resolved 5" })).toBeTruthy();
    const resolved = within(screen.getByRole("grid", { name: "Resolved Conflicts" })).getAllByRole(
      "row",
    );
    expect(resolved).toHaveLength(5);
    expect(resolved[0]!.textContent).toBe(
      "[DECIDED]Engineering's position, 24 hResolved by Alex Owner",
    );
    expect(resolved[1]!.textContent).toBe(
      "[GONE]No longer present in PM Assessment v2No longer present",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("names the reviewer on an escalated row and tags a Conflict detected from text", () => {
    renderSection({
      conflicts: [
        conflict(1, {
          status: "escalated",
          escalated_to: { id: "s", name: "Sam" },
          escalated_by: { id: "a", name: "Alex" },
          escalation_reason: "[WHY]",
          escalated_at: "2026-10-07T10:00:00Z",
        }),
        conflict(2, { detected_by: "semantic", type: "architecture" }),
      ],
      open_count: 2,
      reviewers: [],
    });
    const rows = within(screen.getByRole("grid", { name: "Open Conflicts" })).getAllByRole("row");
    expect(rows[0]!.textContent).toBe("[SUMMARY 1]Scope · R4Escalated to Sam");
    expect(rows[0]!.querySelector(".text-gap svg")).toBeTruthy();
    expect(rows[1]!.textContent).toBe("[SUMMARY 2]Architecture · R4 · Detected from textOpen");
  });

  it("shows the empty-tab card without Conflicts", async () => {
    const { container } = renderSection({ conflicts: [], open_count: 0, reviewers: [] });
    expect(screen.getByRole("heading", { level: 2, name: "Conflicts" })).toBeTruthy();
    expect(screen.getByTestId("empty-tab-card")).toBeTruthy();
    expect(screen.getByText("No Conflicts detected")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Assessments" }).getAttribute("href"),
    ).toMatch(/\/assessments$/);
    expect(screen.queryByRole("grid")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("all resolved: no open Conflicts and no decision card until a resolved row is picked", async () => {
    const user = userEvent.setup();
    const { container } = renderSection({
      conflicts: [DECIDED, GONE, conflict(5, { status: "resolved" })],
      open_count: 0,
      reviewers: [],
    });
    expect(screen.getByText("0 open · 3 resolved")).toBeTruthy();
    expect(screen.getByText("No open Conflicts.")).toBeTruthy();
    expect(screen.queryByTestId("conflict-decision-card")).toBeNull();

    await user.click(row(/\[GONE\]/));
    expect(selectedOf(row(/\[GONE\]/))).toBe("true");
    expect(within(decisionCard()).getByRole("heading", { name: "[GONE]" })).toBeTruthy();
    expect(within(decisionCard()).getByText("No longer present in PM Assessment v2")).toBeTruthy();
    // A pointer open leaves focus on the row.
    expect(document.activeElement).toBe(row(/\[GONE\]/));

    await user.click(row(/\[DECIDED\]/));
    const card = decisionCard();
    expect(within(card).getByTestId("conflict-decision").textContent).toContain(
      "Resolved by Alex Owner: Engineering's position, 24 h",
    );
    expect(within(card).getByText("Chosen")).toBeTruthy();
    expect(within(card).queryByRole("form")).toBeNull();
    expect(within(card).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Enter on a row shows that Conflict and moves focus to its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection();

    await user.tab();
    expect(document.activeElement).toBe(row(/\[EFFORT ON R1\]/));
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const heading = within(decisionCard()).getByRole("heading", { level: 3, name: "[SECURITY]" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(selectedOf(row(/\[SECURITY\]/))).toBe("true");
    expect(selectedOf(row(/\[EFFORT ON R1\]/))).toBe("false");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("viewer: static cards, no form and no buttons in the decision card", () => {
    renderSection();
    const card = decisionCard();
    expect(within(card).queryByRole("form")).toBeNull();
    expect(within(card).queryByRole("radio")).toBeNull();
    expect(within(card).queryByRole("button")).toBeNull();
    expect(within(card).queryByRole("textbox")).toBeNull();
    expect(within(card).getAllByRole("listitem")).toHaveLength(2);
  });

  it("after resolving the first open Conflict the next one is shown and its title focused", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValue({ kind: "ok", conflict: EFFORT });
    renderSection({
      conflicts: [{ ...EFFORT, can_resolve: true }, SECURITY],
      open_count: 2,
      reviewers: [],
    });
    expect(within(decisionCard()).getByRole("heading", { name: "[EFFORT ON R1]" })).toBeTruthy();

    await user.click(within(decisionCard()).getAllByRole("radio")[0]!);
    await user.type(within(decisionCard()).getByLabelText("Reason (required)"), "Interfaces.");
    await user.click(within(decisionCard()).getByRole("button", { name: "Resolve" }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const heading = within(decisionCard()).getByRole("heading", { name: "[SECURITY]" });
    expect(selectedOf(row(/\[SECURITY\]/))).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });
});

describe("ConflictsList", () => {
  it("j/k and the arrows move between rows; j/k off with shortcuts off", async () => {
    const user = userEvent.setup();
    const items = [EFFORT, SECURITY];
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <ConflictsList label="Open Conflicts" items={items} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(/\[EFFORT/));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/\[SECURITY/));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(/\[EFFORT/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/\[SECURITY/));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ConflictsList label="Open Conflicts" items={items} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/\[EFFORT/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/\[SECURITY/));
  });
});
