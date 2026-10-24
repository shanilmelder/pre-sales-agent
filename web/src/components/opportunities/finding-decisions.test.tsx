import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EvidenceOptionsResult,
  FindingDecisionInput,
  FindingDecisionResult,
} from "@/app/opportunities/actions";
import type { RedTeamFinding } from "@/lib/red-team";
import { axeViolations } from "@/test/axe";
import { OPEN_STATE } from "@/test/finding-fixtures";

const decideFinding = vi.hoisted(() =>
  vi.fn<(input: FindingDecisionInput) => Promise<FindingDecisionResult>>(),
);
const loadEvidenceOptions = vi.hoisted(() =>
  vi.fn<(id: string) => Promise<EvidenceOptionsResult>>(),
);
const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({ decideFinding, loadEvidenceOptions }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh,
  }),
  usePathname: () => "/opportunities/x/assessments",
}));

import { LiveRegionProvider } from "../shell/live-region";
import { FindingStatusPill } from "./finding-decisions";
import { RedTeamInspector } from "./red-team-inspector";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const FINDING_ID = "00000000-0000-7000-8000-0000000000c1";
const RAVI = { id: "00000000-0000-7000-8000-0000000000e1", name: "Ravi Kumar" };
const REASON = "Customer confirmed the seasonal profile";
const R1 = {
  kind: "requirement",
  id: "00000000-0000-7000-8000-0000000000b1",
  version: 2,
  label: "R1",
  excerpt: "[EXCERPT R1]",
};
const S1 = {
  kind: "source_document",
  id: "00000000-0000-7000-8000-0000000000a1",
  version: 1,
  label: "S1 · notes.txt",
  excerpt: "",
};

function finding(overrides: Partial<RedTeamFinding> = {}): RedTeamFinding {
  return {
    ...OPEN_STATE,
    can_resolve: true,
    can_override: true,
    id: FINDING_ID,
    position: 1,
    category: "requirement_incomplete",
    severity: "critical",
    title: "[FINDING]",
    argument: "[ARGUMENT]",
    requirements: [],
    lines: [],
    ...overrides,
  };
}

const OVERRIDE = {
  id: "00000000-0000-7000-8000-0000000000f1",
  reason: "[PREVIOUS REASON]",
  by: RAVI,
  at: "2026-10-24T09:00:00Z",
  review_version: 1,
  policy_basis: "owner" as const,
};

function renderInspector(f: RedTeamFinding) {
  return render(
    <LiveRegionProvider>
      <RedTeamInspector finding={f} opportunityId={OPP_ID} />
    </LiveRegionProvider>,
  );
}

const actions = () => screen.queryByRole("group", { name: "Finding actions" });
const submitButton = () =>
  screen.getAllByRole("button").find((b) => b.getAttribute("type") === "submit")!;

beforeEach(() => {
  decideFinding.mockReset();
  loadEvidenceOptions.mockReset();
  refresh.mockReset();
});

describe("FindingStatusPill", () => {
  it("pairs every status with an icon and a label; open critical is blocker-coloured", () => {
    const { container } = render(
      <>
        <FindingStatusPill status="open" severity="critical" />
        <FindingStatusPill status="open" severity="high" />
        <FindingStatusPill status="resolved" severity="critical" />
        <FindingStatusPill status="overridden" severity="critical" />
      </>,
    );
    const pills = Array.from(container.querySelectorAll("[data-finding-status]"));
    expect(pills.map((p) => [p.textContent, p.getAttribute("data-tone")])).toEqual([
      ["Open", "blocker"],
      ["Open", "neutral"],
      ["Resolved", "resolved"],
      ["Overridden", "neutral"],
    ]);
    for (const pill of pills) expect(pill.querySelector("svg")).not.toBeNull();
  });
});

describe("the Finding's actions in the inspector (Story 6.6)", () => {
  it("overrides with a reason after a confirm dialog, then announces and re-reads", async () => {
    const user = userEvent.setup();
    decideFinding.mockResolvedValue({
      kind: "ok",
      finding: { ...finding(), status: "overridden", override: OVERRIDE },
    });
    const { container } = renderInspector(finding());
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(actions()!).getByRole("button", { name: "Override" }));
    await user.click(submitButton());
    expect(screen.getByText("Give a reason of 1 to 1,000 characters.")).toBeTruthy();
    expect(decideFinding).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Reason (required)"), REASON);
    await user.click(submitButton());
    const dialog = await screen.findByRole("dialog", { name: "Override this Finding?" });
    expect(decideFinding).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Override" }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(decideFinding).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      findingId: FINDING_ID,
      rowVersion: 1,
      action: "override",
      reason: REASON,
    });
    expect(await screen.findByText("The Finding is overridden.")).toBeTruthy();
  });

  it("re-applies an earlier override with its reason filled in", async () => {
    const user = userEvent.setup();
    renderInspector(finding({ previous_override: OVERRIDE }));

    expect(
      screen.getByText("Previously overridden by Ravi Kumar: [PREVIOUS REASON]"),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Re-apply override" }));

    expect((screen.getByLabelText("Reason (required)") as HTMLTextAreaElement).value).toBe(
      "[PREVIOUS REASON]",
    );
  });

  it("supplies Evidence chosen in the combobox with a note", async () => {
    const user = userEvent.setup();
    loadEvidenceOptions.mockResolvedValue({ kind: "ok", items: [R1, S1] });
    decideFinding.mockResolvedValue({ kind: "ok", finding: finding({ status: "resolved" }) });
    const { container } = renderInspector(finding());

    await user.click(screen.getByRole("button", { name: "Supply Evidence" }));
    await user.type(screen.getByLabelText("Note (required)"), REASON);
    // The form's submit (the second "Supply Evidence") needs Evidence first.
    const submit = container.querySelector<HTMLButtonElement>("form button[type=submit]")!;
    await user.click(submit);
    expect(screen.getByText("Choose at least one Requirement or Source.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Evidence" }));
    await user.click(await screen.findByRole("option", { name: /R1/ }));
    await user.click(screen.getByRole("option", { name: /S1 · notes.txt/ }));
    expect(screen.getByRole("option", { name: /R1/ }).getAttribute("aria-checked")).toBe("true");
    await user.keyboard("{Escape}");
    const chosen = screen.getByRole("list", { name: "Chosen Evidence" });
    expect(within(chosen).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "R1",
      "S1 · notes.txt",
    ]);
    expect(await axeViolations(container)).toEqual([]);
    await user.click(submit);

    await waitFor(() => expect(decideFinding).toHaveBeenCalled());
    expect(decideFinding).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      findingId: FINDING_ID,
      rowVersion: 1,
      action: "evidence",
      reason: REASON,
      refs: [
        { kind: "requirement", id: R1.id, version: 2 },
        { kind: "source_document", id: S1.id, version: 1 },
      ],
    });
  });

  it("marks resolved with a reason; a 412 offers Reload and is announced", async () => {
    const user = userEvent.setup();
    decideFinding.mockResolvedValue({
      kind: "stale",
      message: "Changed by Sam Reviewer since you opened it.",
    });
    renderInspector(finding());

    await user.click(screen.getByRole("button", { name: "Mark resolved" }));
    await user.type(screen.getByLabelText("Reason (required)"), REASON);
    await user.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Changed by Sam Reviewer since you opened it.");
    expect(decideFinding.mock.calls[0]![0].action).toBe("resolve");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("maps the API's errors like the Conflict decisions", async () => {
    const user = userEvent.setup();
    decideFinding.mockResolvedValue({ kind: "forbidden" });
    renderInspector(finding());

    await user.click(screen.getByRole("button", { name: "Mark resolved" }));
    await user.type(screen.getByLabelText("Reason (required)"), REASON);
    await user.click(submitButton());

    expect(await screen.findAllByText("You are not allowed to do this.")).not.toHaveLength(0);
  });

  it("hides the actions the API doesn't allow (a sales representative)", () => {
    renderInspector(finding({ can_resolve: false, can_override: false }));
    expect(actions()).toBeNull();
    expect(screen.getByText("Open")).toBeTruthy();
  });

  it("never offers Override on a Finding tied to a mandatory security item", () => {
    renderInspector(finding({ overridable: false, can_override: false }));
    expect(screen.queryByRole("button", { name: "Override" })).toBeNull();
    expect(screen.getByRole("button", { name: "Mark resolved" })).toBeTruthy();
    expect(screen.getByText(/can't be overridden/)).toBeTruthy();
  });

  it("shows who overrode it and why, with no actions", async () => {
    const { container } = renderInspector(
      finding({
        status: "overridden",
        override: OVERRIDE,
        can_resolve: false,
        can_override: false,
      }),
    );
    const record = screen.getByTestId("finding-override");
    expect(record.textContent).toContain("Overridden by Ravi Kumar");
    expect(record.textContent).toContain("[PREVIOUS REASON]");
    expect(screen.getByText("Overridden")).toBeTruthy();
    expect(actions()).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the supplied Evidence of a resolved Finding", () => {
    renderInspector(
      finding({
        status: "resolved",
        can_resolve: false,
        can_override: false,
        resolution: {
          kind: "evidence_supplied",
          reason: REASON,
          by: RAVI,
          at: "2026-10-24T09:00:00Z",
          evidence: [{ kind: "requirement", id: R1.id, version: 2, label: "R1" }],
        },
      }),
    );
    const record = screen.getByTestId("finding-resolution");
    expect(record.textContent).toContain("Evidence supplied by Ravi Kumar");
    expect(within(record).getByRole("list", { name: "Supplied Evidence" }).textContent).toBe(
      "R1",
    );
  });
});

describe("the Evidence combobox's limit", () => {
  it("stops at 20 and says so", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 21 }, (_, n) => ({
      ...R1,
      id: `00000000-0000-7000-8000-0000000001${String(n).padStart(2, "0")}`,
      label: `R${n + 1}`,
      excerpt: "",
    }));
    loadEvidenceOptions.mockResolvedValue({ kind: "ok", items: many });
    renderInspector(finding());
    await user.click(screen.getByRole("button", { name: "Supply Evidence" }));
    await user.click(screen.getByRole("button", { name: "Evidence" }));
    for (let n = 1; n <= 20; n += 1) {
      await user.click(await screen.findByRole("option", { name: `R${n}` }));
    }

    expect(screen.getByText("Up to 20 Requirements or Sources can be cited.")).toBeTruthy();
    const last = screen.getByRole("option", { name: "R21" });
    expect(last.getAttribute("aria-disabled")).toBe("true");
    expect(last.getAttribute("aria-checked")).toBe("false");
  });
});
