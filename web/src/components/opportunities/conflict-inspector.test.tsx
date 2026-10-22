import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConflictDecisionResult,
  EscalateConflictInput,
  ResolveConflictInput,
} from "@/app/opportunities/actions";
import type {
  Conflict,
  ConflictPosition,
  ConflictsView,
} from "@/lib/conflicts";
import { axeViolations } from "@/test/axe";

const resolveConflict = vi.hoisted(() =>
  vi.fn<(input: ResolveConflictInput) => Promise<ConflictDecisionResult>>(),
);
const escalateConflict = vi.hoisted(() =>
  vi.fn<(input: EscalateConflictInput) => Promise<ConflictDecisionResult>>(),
);
const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({
  resolveConflict,
  escalateConflict,
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

import { LiveRegionProvider } from "../shell/live-region";
import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { ConflictInspector } from "./conflict-inspector";
import { ConflictsSection } from "./conflicts-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const SAM = {
  id: "00000000-0000-7000-8000-0000000000e1",
  name: "Sam Reviewer",
};
const R2 = {
  id: "00000000-0000-7000-8000-0000000000b2",
  version: 1,
  label: "R2",
  excerpt: "[EXCERPT R2]",
};

function agent(n: number, name: string, hours: number): ConflictPosition {
  return {
    position: n,
    source: "assessment",
    agent: name,
    assessment_id: `00000000-0000-7000-8000-00000000a00${n}`,
    assessment_version: 2,
    estimate_version_id: null,
    estimate_version: null,
    summary: `${hours} h`,
    value: hours,
    requirement: R2,
    finding: null,
  };
}

const ESTIMATE: ConflictPosition = {
  position: 3,
  source: "estimate",
  agent: null,
  assessment_id: null,
  assessment_version: null,
  estimate_version_id: "00000000-0000-7000-8000-0000000000c3",
  estimate_version: 3,
  summary: "131 h",
  value: 131,
  requirement: R2,
  finding: null,
};

function effortConflict(overrides: Partial<Conflict> = {}): Conflict {
  return {
    id: "00000000-0000-7000-8000-000000000011",
    type: "effort",
    severity: "medium",
    status: "open",
    detected_by: "rule",
    summary: "[SUMMARY]",
    run_id: "00000000-0000-7000-8000-0000000000f1",
    previous_conflict_id: null,
    resolution_reason: null,
    resolved_at: null,
    created_at: "2026-10-07T09:00:00Z",
    requirement: R2,
    positions: [
      agent(1, "engineering_agent", 60),
      agent(2, "pm_agent", 40),
      ESTIMATE,
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
    can_resolve: true,
    can_escalate: true,
    ...overrides,
  };
}

function renderInspector(conflict: Conflict, reviewers = [SAM]) {
  return render(
    <LiveRegionProvider>
      <ConflictInspector
        conflict={conflict}
        opportunityId={OPP_ID}
        reviewers={reviewers}
      />
    </LiveRegionProvider>,
  );
}

const resolveForm = () =>
  screen.getByRole("form", { name: "Resolve the Conflict" });

beforeEach(() => {
  resolveConflict.mockReset();
  escalateConflict.mockReset();
  refresh.mockReset();
});

describe("resolving a Conflict", () => {
  it("blocks a missing choice and reason inline, then resolves with the chosen position", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValue({
      kind: "ok",
      conflict: effortConflict({ status: "resolved", row_version: 2 }),
    });
    const { container } = renderInspector(effortConflict());

    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    expect(
      screen.getByText("Choose a position, or enter a different one."),
    ).toBeTruthy();
    expect(screen.getByText("Give a reason for the decision.")).toBeTruthy();
    expect(screen.getByLabelText("Reason").getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(resolveConflict).not.toHaveBeenCalled();

    // The positions are radio cards on the equal-width cards.
    const radios = within(resolveForm()).getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("aria-label") ?? "")).toEqual([
      "Engineering's position, 60 h",
      "PM's position, 40 h",
      "Estimate v3's position, 131 h",
      "",
    ]);
    await user.click(radios[0]!);
    await user.type(
      screen.getByLabelText("Reason"),
      "  Matches the interface list.  ",
    );
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(resolveConflict).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      conflictId: effortConflict().id,
      rowVersion: 1,
      choice: { position: 1 },
      reason: "Matches the interface list.",
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says what choosing an agent's position does to the Estimate line", async () => {
    const user = userEvent.setup();
    renderInspector(effortConflict());
    const effect =
      "Choosing an agent's position sets the Estimate line to the agents' total, 100 h.";
    expect(screen.queryByText(effect)).toBeNull();

    const radios = within(resolveForm()).getAllByRole("radio");
    await user.click(radios[0]!);
    expect(screen.getByText(effect)).toBeTruthy();
    await user.click(radios[1]!);
    expect(screen.getByText(effect)).toBeTruthy();
    await user.click(radios[2]!); // the Estimate's own position: nothing extra
    expect(screen.queryByText(effect)).toBeNull();
  });

  it("asks for hours when entering a different effort position", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValue({
      kind: "ok",
      conflict: effortConflict(),
    });
    renderInspector(effortConflict());

    await user.click(
      screen.getByRole("radio", { name: "A different position" }),
    );
    await user.type(screen.getByLabelText("Hours"), "about two days");
    await user.type(screen.getByLabelText("Reason"), "Our own figure.");
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    expect(
      screen.getByText(
        "Enter hours from 0 to 2,000, to 0.1 h (for example 48).",
      ),
    ).toBeTruthy();
    expect(resolveConflict).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Hours"));
    await user.type(screen.getByLabelText("Hours"), "48");
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    await waitFor(() => expect(resolveConflict).toHaveBeenCalled());
    expect(resolveConflict.mock.calls[0]![0].choice).toEqual({ entered: "48" });
  });

  it("enters words for a scope Conflict", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValue({
      kind: "ok",
      conflict: effortConflict(),
    });
    renderInspector(effortConflict({ type: "scope" }));

    await user.click(
      screen.getByRole("radio", { name: "A different position" }),
    );
    await user.type(
      screen.getByLabelText("The position"),
      "In scope: PM to size in v2",
    );
    await user.type(screen.getByLabelText("Reason"), "PM agrees.");
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    await waitFor(() => expect(resolveConflict).toHaveBeenCalled());
    expect(resolveConflict.mock.calls[0]![0].choice).toEqual({
      entered: "In scope: PM to size in v2",
    });
  });

  it("shows the 412 message with Reload, and 422 and 403 inline", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValueOnce({
      kind: "stale",
      message: "Changed by Alex Owner since you opened it.",
    });
    renderInspector(effortConflict());

    await user.click(within(resolveForm()).getAllByRole("radio")[2]!);
    await user.type(screen.getByLabelText("Reason"), "Keep it.");
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    expect(
      await screen.findByText("Changed by Alex Owner since you opened it."),
    ).toBeTruthy();
    expect(screen.getByRole("alert").getAttribute("data-slot")).toBe("inline-alert");
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(refresh).toHaveBeenCalledTimes(1);

    resolveConflict.mockResolvedValueOnce({
      kind: "invalid",
      detail: "[RULE]",
    });
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    expect(await screen.findByText("[RULE]")).toBeTruthy();

    resolveConflict.mockResolvedValueOnce({ kind: "forbidden" });
    await user.click(
      within(resolveForm()).getByRole("button", { name: "Resolve" }),
    );
    expect(
      await screen.findByText(/Only the owner and collaborators/),
    ).toBeTruthy();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("hides the actions from those who may not decide", () => {
    renderInspector(
      effortConflict({ can_resolve: false, can_escalate: false }),
    );
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByText("Escalate to a reviewer")).toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("escalating a Conflict", () => {
  it("escalates to a chosen reviewer with a reason", async () => {
    const user = userEvent.setup();
    escalateConflict.mockResolvedValue({
      kind: "ok",
      conflict: effortConflict(),
    });
    const { container } = renderInspector(effortConflict());

    await user.click(screen.getByText("Escalate to a reviewer"));
    const form = screen.getByRole("form", { name: "Escalate the Conflict" });
    await user.click(within(form).getByRole("button", { name: "Escalate" }));
    expect(screen.getByText("Choose a reviewer.")).toBeTruthy();
    expect(escalateConflict).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Reviewer"), SAM.id);
    await user.type(
      screen.getByLabelText("Reason for escalating"),
      "Needs the lead's call.",
    );
    await user.click(within(form).getByRole("button", { name: "Escalate" }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(escalateConflict).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      conflictId: effortConflict().id,
      rowVersion: 1,
      reviewerId: SAM.id,
      reason: "Needs the lead's call.",
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows an escalated Conflict's reviewer and offers only Resolve", () => {
    renderInspector(
      effortConflict({
        status: "escalated",
        can_escalate: false,
        escalated_to: SAM,
        escalated_by: { id: "x", name: "Alex Owner" },
        escalation_reason: "Needs the lead's call.",
        escalated_at: "2026-10-07T10:00:00Z",
      }),
    );
    expect(screen.getByText("Escalated to Sam Reviewer")).toBeTruthy();
    expect(screen.getByText(/Needs the lead's call\./)).toBeTruthy();
    expect(resolveForm()).toBeTruthy();
    expect(screen.queryByText("Escalate to a reviewer")).toBeNull();
  });
});

describe("a resolved Conflict", () => {
  it("shows the decision, its reason, the Estimate effect and every position", async () => {
    const { container } = renderInspector(
      effortConflict({
        status: "resolved",
        can_resolve: false,
        can_escalate: false,
        resolved_by_name: "Alex Owner",
        chosen_position: 1,
        applied_hours: 100,
        resolution_reason: "Matches the interface list.",
        resolved_at: "2026-10-07T10:00:00Z",
      }),
    );
    expect(
      within(screen.getByTestId("conflict-decision")).getByText(
        "Resolved by Alex Owner: Engineering's position, 60 h",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Matches the interface list.")).toBeTruthy();
    expect(screen.getByText("Estimate line set to 100 h.")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Chosen")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when an effort decision was not applied, and shows an entered position", () => {
    renderInspector(
      effortConflict({
        status: "resolved",
        can_resolve: false,
        resolved_by_name: "Alex Owner",
        entered_position: "48",
        not_applied: "shared_line",
        resolution_reason: "[REASON]",
        resolved_at: "2026-10-07T10:00:00Z",
      }),
    );
    expect(screen.getByText("Resolved by Alex Owner: 48")).toBeTruthy();
    expect(
      screen.getByText(
        "Not applied: the Estimate line covers several Requirements.",
      ),
    ).toBeTruthy();
  });

  it("notes an earlier decision on a Conflict raised again", () => {
    renderInspector(
      effortConflict({
        previous_decision: {
          name: "Alex Owner",
          resolved_at: "2026-10-07T10:00:00Z",
        },
      }),
    );
    expect(
      screen.getByText(
        "Resolved earlier by Alex Owner; positions have changed.",
      ),
    ).toBeTruthy();
  });
});

describe("the Conflicts list", () => {
  it("names the reviewer on an escalated row", async () => {
    const view: ConflictsView = {
      conflicts: [effortConflict({ status: "escalated", escalated_to: SAM })],
      open_count: 1,
      reviewers: [SAM],
    };
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <ConflictsSection initial={view} opportunityId={OPP_ID} />
        <RightPane />
      </ShellProviders>,
    );
    const row = screen.getByRole("button", {
      name: /Escalated to Sam Reviewer/,
    });
    expect(row).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});

// --- Story 6.2: Conflicts detected from the Findings' text ----------------------------------

function findingPosition(
  n: number,
  name: string,
  stance: string,
  finding: { title: string; kind: string },
): ConflictPosition {
  return {
    ...agent(n, name, 0),
    summary: stance,
    value: null,
    finding: { id: `00000000-0000-7000-8000-00000000f00${n}`, ...finding },
  };
}

function textConflict(overrides: Partial<Conflict> = {}): Conflict {
  return effortConflict({
    id: "00000000-0000-7000-8000-000000000062",
    type: "architecture",
    severity: "high",
    detected_by: "semantic",
    summary: "[SEMANTIC SUMMARY]",
    positions: [
      findingPosition(1, "engineering_agent", "[ENGINEERING STANCE]", {
        title: "[SSO FINDING]",
        kind: "risk",
      }),
      findingPosition(2, "security_agent", "[SECURITY STANCE]", {
        title: "[IDP FINDING]",
        kind: "constraint",
      }),
    ],
    ...overrides,
  });
}

describe("a Conflict detected from text", () => {
  it("is tagged in the header and shows each cited Finding's kind and title above its stance", async () => {
    const { container } = renderInspector(textConflict());
    expect(screen.getByTestId("detected-from-text").textContent).toBe("Detected from text");
    expect(screen.getByRole("heading", { name: "Architecture Conflict" })).toBeTruthy();
    const findings = screen.getAllByTestId("position-finding");
    expect(findings.map((f) => f.textContent)).toEqual([
      "Risk[SSO FINDING]",
      "Constraint[IDP FINDING]",
    ]);
    // The Finding comes before the stance on its card.
    const card = findings[0]!.parentElement!;
    expect(card.textContent).toMatch(/\[SSO FINDING\].*\[ENGINEERING STANCE\]/);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is resolved as in 6.3, by choosing a position", async () => {
    const user = userEvent.setup();
    resolveConflict.mockResolvedValue({
      kind: "ok",
      conflict: textConflict({ status: "resolved", row_version: 2 }),
    });
    renderInspector(textConflict());
    const radios = within(resolveForm()).getAllByRole("radio");
    await user.click(radios[1]!);
    await user.type(screen.getByLabelText("Reason"), "Security policy wins.");
    await user.click(within(resolveForm()).getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(resolveConflict).toHaveBeenCalledWith(
      expect.objectContaining({ choice: { position: 2 }, reason: "Security policy wins." }),
    );
  });

  it("is tagged on its row; a rule Conflict is not", async () => {
    const view: ConflictsView = {
      conflicts: [textConflict(), effortConflict()],
      open_count: 2,
      reviewers: [],
    };
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <ConflictsSection initial={view} opportunityId={OPP_ID} />
        <RightPane />
      </ShellProviders>,
    );
    const rows = within(screen.getByRole("grid", { name: "Open Conflicts" })).getAllByRole("row");
    expect(within(rows[0]!).getByTestId("detected-from-text")).toBeTruthy();
    expect(within(rows[1]!).queryByTestId("detected-from-text")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});
