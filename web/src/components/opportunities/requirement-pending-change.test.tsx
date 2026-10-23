import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PassageResult,
  RequirementChangeResult,
  RequirementConfirmInput,
  RequirementRejectInput,
} from "@/app/opportunities/actions";
import type { OutdatedAssessmentsResult, RequirementsResult } from "@/app/opportunities/data";
import type {
  OutdatedAssessment,
  PendingChange,
  Requirement,
  RequirementList,
} from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const acceptRequirementChange = vi.hoisted(() =>
  vi.fn<(input: RequirementConfirmInput) => Promise<RequirementChangeResult>>(),
);
const rejectRequirementChange = vi.hoisted(() =>
  vi.fn<(input: RequirementRejectInput) => Promise<RequirementChangeResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
const loadOutdatedAssessments = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<OutdatedAssessmentsResult>>(),
);
const getPassage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, passageId: string) => Promise<PassageResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  acceptRequirementChange,
  rejectRequirementChange,
  loadRequirements,
  loadOutdatedAssessments,
  getPassage,
  editRequirement: vi.fn(),
  confirmRequirement: vi.fn(),
  confirmAllRequirements: vi.fn(),
  startExtraction: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/opportunities/x/requirements",
}));

import { RightPane } from "../shell/right-pane";
import { RightPaneToggle } from "../shell/right-pane-toggle";
import { ShellProviders } from "../shell/shell-context";
import { RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const ME = { id: "00000000-0000-7000-8000-0000000000e1", name: "[OWNER]" };
const OLD_PASSAGE = "00000000-0000-7000-8000-0000000001aa";
const NEW_PASSAGE = "00000000-0000-7000-8000-0000000002aa";

const PENDING: PendingChange = {
  id: "00000000-0000-7000-8000-0000000000c1",
  text: "[PROPOSED TEXT]",
  classification: "integration",
  evidence: [
    {
      passage_id: NEW_PASSAGE,
      source_id: "00000000-0000-7000-8000-0000000000b2",
      source_version: 1,
      filename: "mail.txt",
      label: "S2 · mail.txt",
    },
  ],
  proposed_at: "2026-10-19T09:00:00Z",
};

function requirement(n: number, extra: Partial<Requirement> = {}): Requirement {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    number: n,
    text: `[REQUIREMENT ${n}]`,
    classification: "functional",
    origin: "human",
    locked_by_human: true,
    version: 2,
    row_version: 3,
    created_at: "2026-10-04T13:05:00Z",
    confirmed_at: null,
    confirmed_by: null,
    last_changed_by: ME,
    pending_change: null,
    evidence: [
      {
        passage_id: OLD_PASSAGE,
        source_id: "00000000-0000-7000-8000-0000000000b1",
        source_version: 1,
        filename: "call.txt",
        label: "S1 · call.txt",
      },
    ],
    ...extra,
  };
}

function list(items: Requirement[], canEdit = true): RequirementList {
  return {
    items,
    extraction: { status: "succeeded", error_code: null, source_count: 2 },
    can_start_extraction: canEdit,
    can_edit_requirements: canEdit,
  };
}

function renderSection(initial: RequirementList, outdated: OutdatedAssessment[] = []) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <RequirementsSection opportunityId={OPP_ID} initial={initial} initialOutdated={outdated} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: `[REQUIREMENT ${n}]` });
const pane = () => screen.getByRole("complementary", { name: "Details" });
const section = () => within(pane()).getByTestId("pending-change");

beforeEach(() => {
  acceptRequirementChange.mockReset();
  rejectRequirementChange.mockReset();
  loadRequirements.mockReset();
  loadOutdatedAssessments.mockReset();
  loadOutdatedAssessments.mockResolvedValue({ kind: "ok", items: [] });
  getPassage.mockReset();
  getPassage.mockResolvedValue({ kind: "not-found" });
});

describe("a Requirement with a pending change", () => {
  it("shows the amber marker on its row only", () => {
    renderSection(list([requirement(1, { pending_change: PENDING }), requirement(2)]));

    const marked = row(1).closest('[role="row"]') as HTMLElement;
    const marker = within(marked).getByText("Pending change");
    expect(marker.className).toContain("text-gap");
    expect(marker.querySelector("svg")).toBeTruthy(); // an icon, never colour alone
    const other = row(2).closest('[role="row"]') as HTMLElement;
    expect(within(other).queryByText("Pending change")).toBeNull();
  });

  it("the inspector shows the − and + lines on the diff tint, the classification change and the new Evidence", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1, { pending_change: PENDING })]));

    await user.click(row(1));

    const diff = section();
    const minus = within(diff).getByText("−").closest("p") as HTMLElement;
    const plus = within(diff).getByText("+").closest("p") as HTMLElement;
    expect(minus.textContent).toBe("−Current: [REQUIREMENT 1]");
    expect(plus.textContent).toBe("+Proposed: [PROPOSED TEXT]");
    for (const line of [minus, plus]) {
      expect(line.className).toContain("bg-diff-tint");
      expect(line.className).not.toMatch(/green|red|resolved|blocker|destructive/);
    }
    expect(within(diff).getByText("Classification: Functional → Integration")).toBeTruthy();
    const chip = within(diff).getByRole("button", { name: "S2 · mail.txt" });

    await user.click(chip);
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(getPassage).toHaveBeenLastCalledWith(OPP_ID, NEW_PASSAGE));
  });

  it("Accept applies it with If-Match, the marker goes, and the notice is read again", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, { pending_change: PENDING });
    renderSection(list([r1, requirement(2)]));
    acceptRequirementChange.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        text: PENDING.text,
        classification: PENDING.classification,
        version: 3,
        row_version: 4,
        pending_change: null,
        evidence: [...r1.evidence, ...PENDING.evidence],
      },
    });
    await user.click(row(1));

    await user.click(within(section()).getByRole("button", { name: "Accept" }));

    expect(acceptRequirementChange).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 3,
    });
    const accepted = await screen.findByRole("button", { name: "[PROPOSED TEXT]" });
    const acceptedRow = accepted.closest('[role="row"]') as HTMLElement;
    expect(within(acceptedRow).queryByText("Pending change")).toBeNull();
    expect(within(pane()).queryByTestId("pending-change")).toBeNull();
    await waitFor(() => expect(loadOutdatedAssessments).toHaveBeenCalledWith(OPP_ID));
  });

  it("Reject asks for a reason (the shared ReasonInput) and sends it trimmed", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, { pending_change: PENDING });
    renderSection(list([r1]));
    rejectRequirementChange.mockResolvedValue({
      kind: "ok",
      requirement: { ...r1, row_version: 4, pending_change: null },
    });
    await user.click(row(1));

    await user.click(within(section()).getByRole("button", { name: "Reject" }));
    const reason = within(section()).getByRole("textbox", { name: "Why reject this change?" });
    expect(document.activeElement).toBe(reason);
    await user.click(within(section()).getByRole("button", { name: "Reject change" }));
    expect(within(section()).getByText("Give a reason.")).toBeTruthy();
    expect(rejectRequirementChange).not.toHaveBeenCalled();
    expect(within(section()).getByText("0/500")).toBeTruthy();

    await user.type(reason, "  The customer meant ECC.  ");
    await user.click(within(section()).getByRole("button", { name: "Reject change" }));

    expect(rejectRequirementChange).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 3,
      reason: "The customer meant ECC.",
    });
    await waitFor(() => expect(within(pane()).queryByTestId("pending-change")).toBeNull());
    expect(within(row(1).closest('[role="row"]') as HTMLElement).queryByText("Pending change")).toBeNull();
  });

  it("a 422 from Reject shows the reason under the field", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1, { pending_change: PENDING })]));
    rejectRequirementChange.mockResolvedValue({
      kind: "invalid",
      detail: "The reason can be at most 500 characters.",
    });
    await user.click(row(1));
    await user.click(within(section()).getByRole("button", { name: "Reject" }));
    await user.type(within(section()).getByRole("textbox"), "Too long, says the API.");
    await user.click(within(section()).getByRole("button", { name: "Reject change" }));

    expect(
      await within(section()).findByText("The reason can be at most 500 characters."),
    ).toBeTruthy();
  });

  it("a 412 shows the stale notice with Reload; Reload reads the list again", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, { pending_change: PENDING });
    renderSection(list([r1]));
    acceptRequirementChange.mockResolvedValue({ kind: "stale", changedBy: "[COLLEAGUE]" });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list([{ ...r1, row_version: 4 }]),
    });
    await user.click(row(1));

    await user.click(within(section()).getByRole("button", { name: "Accept" }));

    expect(
      await screen.findByText("Changed by [COLLEAGUE] since you opened it."),
    ).toBeTruthy();
    const reload = screen.getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
    expect(
      (within(section()).getByRole("button", { name: "Accept" }) as HTMLButtonElement).disabled,
    ).toBe(true);

    await user.click(reload);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reload" })).toBeNull());
    expect(loadRequirements).toHaveBeenCalledWith(OPP_ID);
  });

  it("a change someone else decided first reloads the list and says so", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, { pending_change: PENDING });
    renderSection(list([r1]));
    acceptRequirementChange.mockResolvedValue({ kind: "no-change" });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list([{ ...r1, row_version: 4, pending_change: null }]),
    });
    await user.click(row(1));

    await user.click(within(section()).getByRole("button", { name: "Accept" }));

    expect(
      await screen.findByText(
        "This change was already accepted or rejected. The Requirements were reloaded.",
      ),
    ).toBeTruthy();
    await waitFor(() => expect(within(pane()).queryByTestId("pending-change")).toBeNull());
  });

  it("sales representatives see the marker and the diff, but no Accept or Reject", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1, { pending_change: PENDING })], false));

    expect(within(row(1).closest('[role="row"]') as HTMLElement).getByText("Pending change")).toBeTruthy();
    await user.click(row(1));

    expect(within(section()).getByText("[PROPOSED TEXT]")).toBeTruthy();
    expect(within(section()).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(section()).queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("has no axe violations with the diff open and while rejecting", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([requirement(1, { pending_change: PENDING })]));
    await user.click(row(1));
    await act(async () => {});
    expect(await axeViolations(container)).toEqual([]);
    expect(await axeViolations(pane())).toEqual([]);

    await user.click(within(section()).getByRole("button", { name: "Reject" }));
    await user.click(within(section()).getByRole("button", { name: "Reject change" }));
    expect(await axeViolations(pane())).toEqual([]);
  });
});

describe("the outdated Assessments notice", () => {
  const OUTDATED: OutdatedAssessment[] = [
    {
      id: "00000000-0000-7000-8000-0000000000a1",
      agent: "engineering_agent",
      label: "Engineering Agent",
      requirement_labels: ["R1", "R3"],
    },
    {
      id: "00000000-0000-7000-8000-0000000000a2",
      agent: "pm_agent",
      label: "PM Agent",
      requirement_labels: ["Superseded"],
    },
  ];

  it("names the Assessments and links to the Assessments tab", async () => {
    const { container } = renderSection(list([requirement(1)]), OUTDATED);

    const notice = screen.getByTestId("outdated-assessments");
    expect(
      within(notice).getByText(
        "These Assessments used Requirements that have changed since: Engineering Agent (R1, R3), PM Agent (Superseded).",
      ),
    ).toBeTruthy();
    const link = within(notice).getByRole("link", { name: "Open the Assessments tab" });
    expect(link.getAttribute("href")).toBe(`/opportunities/${OPP_ID}/assessments`);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is not shown when no Assessment is outdated", () => {
    renderSection(list([requirement(1)]));
    expect(screen.queryByTestId("outdated-assessments")).toBeNull();
  });
});

describe("the ?requirement= deep link (Story 4.7)", () => {
  it("opens that Requirement's inspector with its diff as the page loads", async () => {
    const r2 = requirement(2, { pending_change: PENDING });
    render(
      <ShellProviders singleKeyShortcuts>
        <RequirementsSection
          opportunityId={OPP_ID}
          initial={list([requirement(1), r2])}
          initialSelectedId={r2.id}
        />
        <RightPane />
      </ShellProviders>,
    );

    expect(await within(pane()).findByTestId("pending-change")).toBeTruthy();
    expect(within(section()).getByText("+").closest("p")?.textContent).toBe(
      "+Proposed: [PROPOSED TEXT]",
    );
  });

  it("an id that is not listed opens nothing", () => {
    render(
      <ShellProviders singleKeyShortcuts>
        <RequirementsSection
          opportunityId={OPP_ID}
          initial={list([requirement(1)])}
          initialSelectedId="00000000-0000-7000-8000-00000000ffff"
        />
        <RightPane />
      </ShellProviders>,
    );
    expect(screen.queryByTestId("pending-change")).toBeNull();
  });
});

describe("the redesigned tab", () => {
  const done = (item: Requirement): Requirement => ({
    ...item,
    confirmed_at: "2026-10-19T10:00:00Z",
    confirmed_by: ME,
  });
  // 3 confirmed, 1 unconfirmed, 1 with a pending change.
  const MIXED = [
    done(requirement(1)),
    done(requirement(2)),
    done(requirement(3, { classification: "security" })),
    requirement(4, { classification: "security" }),
    requirement(5, { classification: "data", pending_change: PENDING }),
  ];
  const rowOf = (n: number) => row(n).closest('[role="row"]') as HTMLElement;
  const pillOf = (n: number) => rowOf(n).querySelector('[data-slot="pill"]')!;
  const banner = () =>
    screen.getByRole("region", { name: "1 pending change from incremental intake" });

  it("mixed list: counts, pills, the amber edge and the banner", async () => {
    const { container } = renderSection(list(MIXED));

    expect(screen.getByText("5 total · 3 confirmed · 2 to review")).toBeTruthy();
    expect([1, 2, 3, 4, 5].map((n) => pillOf(n).getAttribute("data-tone"))).toEqual([
      "resolved",
      "resolved",
      "resolved",
      "neutral",
      "gap",
    ]);
    expect(pillOf(4).textContent).toBe("Unconfirmed");
    expect(pillOf(5).textContent).toBe("Pending change");
    expect(rowOf(5).className).toContain("inset_3px");
    expect(rowOf(4).className).not.toContain("inset_3px");
    expect(within(rowOf(4)).getByRole("button", { name: "Confirm: [REQUIREMENT 4]" })).toBeTruthy();
    expect(within(rowOf(1)).queryByRole("button", { name: /^Confirm/ })).toBeNull();
    expect(screen.getByRole("region", { name: "Functional 2 · 2 confirmed" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Security 2 · 1 confirmed" })).toBeTruthy();

    const lines = within(banner()).getAllByRole("listitem");
    expect(lines).toHaveLength(1);
    expect(lines[0]!.textContent).toContain("Current: R5 [REQUIREMENT 5]");
    expect(lines[0]!.textContent).toContain("Proposed: R5 [PROPOSED TEXT]");
    expect(lines[0]!.textContent).toContain("Classification: Data → Integration");
    // Read-only: no Accept or Reject in the banner.
    expect(within(banner()).queryByRole("button", { name: /Accept|Reject/ })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the banner's Review opens that Requirement in the inspector, with Accept and Reject", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));

    await user.click(within(banner()).getByRole("button", { name: "Review R5" }));

    expect(within(pane()).getByRole("heading", { name: "[REQUIREMENT 5]" })).toBeTruthy();
    expect(within(section()).getByRole("button", { name: "Accept" })).toBeTruthy();
    expect(within(section()).getByRole("button", { name: "Reject" })).toBeTruthy();
    expect(rowOf(5).getAttribute("aria-selected")).toBe("true");
  });

  it("no pending changes: no banner", () => {
    renderSection(list([requirement(1)]));
    expect(screen.queryByTestId("pending-changes")).toBeNull();
  });

  it("State = Confirmed shows only confirmed rows; j/k skip the hidden ones", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));

    await user.selectOptions(screen.getByRole("combobox", { name: "State" }), "confirmed");

    expect(screen.queryByRole("button", { name: "[REQUIREMENT 4]" })).toBeNull();
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 5]" })).toBeNull();
    expect(screen.queryByRole("region", { name: /^Data/ })).toBeNull();
    expect(screen.getByRole("region", { name: "Security 1 · 1 confirmed" })).toBeTruthy();
    // The counts are the whole list's.
    expect(screen.getByText("5 total · 3 confirmed · 2 to review")).toBeTruthy();

    row(1).focus();
    await user.keyboard("jj");
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(2));
  });

  it("a filter that leaves nothing says so, and Clear filters shows every row", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));
    const category = screen.getByRole("combobox", { name: "Category" }) as HTMLSelectElement;
    expect(Array.from(category.options).map((o) => o.textContent)).toEqual([
      "Category",
      "Category: Functional",
      "Category: Data",
      "Category: Security",
    ]);

    await user.selectOptions(category, "security");
    await user.selectOptions(screen.getByRole("combobox", { name: "State" }), "pending");

    expect(screen.getByText("No Requirements match these filters.")).toBeTruthy();
    expect(screen.queryAllByRole("row")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(category.value).toBe("");
  });

  it("a Requirement a person added reads Added by a person, with no chips", () => {
    renderSection(list([requirement(1, { evidence: [] }), requirement(2)]));
    expect(within(rowOf(1)).getByText("· Added by a person")).toBeTruthy();
    expect(rowOf(1).querySelector("[data-passage-id]")).toBeNull();
    expect(within(rowOf(2)).getByText("· Edited by [OWNER]")).toBeTruthy();
    expect(within(rowOf(2)).getByRole("button", { name: "S1 · call.txt" })).toBeTruthy();
  });

  it("the selected row has Edit, Split and Merge", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2)]));
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();

    await user.click(row(1));
    expect(rowOf(1).className).toContain("bg-agent-tint");
    const merge = within(rowOf(1)).getByRole("button", { name: "Merge" });
    expect(merge.getAttribute("aria-pressed")).toBe("false");
    await user.click(merge);
    const selected = within(rowOf(1)).getByRole("button", { name: "Selected for merge" });
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    expect(rowOf(1).hasAttribute("data-checked")).toBe(true);
    // The inspector's Merge is the same toggle.
    await user.click(within(pane()).getByRole("button", { name: "Selected for merge" }));
    expect(rowOf(1).hasAttribute("data-checked")).toBe(false);

    await user.click(within(rowOf(1)).getByRole("button", { name: "Split" }));
    const first = within(pane()).getByRole("textbox", { name: "First Requirement" });
    expect(document.activeElement).toBe(first);

    await user.click(within(rowOf(1)).getByRole("button", { name: "Edit" }));
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    expect(document.activeElement).toBe(input);
  });

  it("the inspector: meta line, state pill, Evidence and Actions", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), done(requirement(2))]));

    await user.click(row(1));
    const inspector = pane();
    const meta = within(inspector).getByText("Edited by [OWNER]").closest("p")!;
    expect(meta.textContent).toBe("Functional·R1·Edited by [OWNER]");
    expect(within(inspector).getByText("Unconfirmed")).toBeTruthy();
    const actions = within(inspector).getByRole("group", { name: "Actions" });
    expect(within(actions).getByRole("button", { name: "Confirm requirement" })).toBeTruthy();
    for (const name of ["Edit", "Split", "Merge", "Delete"]) {
      expect(within(actions).getByRole("button", { name })).toBeTruthy();
    }
    await user.click(within(actions).getByRole("button", { name: "Edit" }));
    expect(document.activeElement).toBe(
      within(inspector).getByRole("textbox", { name: "Requirement text" }),
    );
    await user.keyboard("{Escape}");

    await user.click(row(2));
    expect(within(pane()).getByText("Confirmed")).toBeTruthy();
    expect(within(pane()).queryByRole("button", { name: "Confirm requirement" })).toBeNull();
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("viewers get no Add, Confirm, Confirm all, Edit, Split or Merge", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED, false));
    await user.click(row(4));
    for (const name of [
      "Add requirement",
      "Confirm all (2)",
      "Confirm: [REQUIREMENT 4]",
      "Confirm requirement",
      "Edit",
      "Split",
      "Merge",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(within(pane()).getByRole("heading", { name: "[REQUIREMENT 4]" })).toBeTruthy();
  });

  it("Review on a Requirement the filters hide clears them and selects its row", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));
    const state = screen.getByRole("combobox", { name: "State" }) as HTMLSelectElement;
    await user.selectOptions(state, "confirmed");
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 5]" })).toBeNull();

    await user.click(within(banner()).getByRole("button", { name: "Review R5" }));

    expect(state.value).toBe("");
    expect(rowOf(5).getAttribute("aria-selected")).toBe("true");
    expect(within(pane()).getByRole("heading", { name: "[REQUIREMENT 5]" })).toBeTruthy();
  });

  it("changing a filter clears the merge selection", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));
    for (const n of [1, 4]) {
      row(n).focus();
      await user.keyboard("x");
    }
    expect(screen.getByRole("toolbar", { name: "Selected Requirements" })).toBeTruthy();

    await user.selectOptions(screen.getByRole("combobox", { name: "State" }), "confirmed");

    expect(screen.queryByRole("toolbar", { name: "Selected Requirements" })).toBeNull();
    expect(rowOf(1).hasAttribute("data-checked")).toBe(false);
  });

  it("a chosen Category stays after a reload drops its last Requirement", async () => {
    const user = userEvent.setup();
    renderSection(list(MIXED));
    acceptRequirementChange.mockResolvedValue({ kind: "no-change" });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list(MIXED.filter((item) => item.classification !== "security")),
    });
    await user.click(within(banner()).getByRole("button", { name: "Review R5" }));
    const category = screen.getByRole("combobox", { name: "Category" }) as HTMLSelectElement;
    await user.selectOptions(category, "security");

    // Already decided: the list is read again, now without Security.
    await user.click(within(section()).getByRole("button", { name: "Accept" }));

    await waitFor(() => expect(loadRequirements).toHaveBeenCalledWith(OPP_ID));
    await waitFor(() =>
      expect(screen.getByText("No Requirements match these filters.")).toBeTruthy(),
    );
    expect(category.value).toBe("security");
    expect(Array.from(category.options).map((o) => o.textContent)).toContain("Category: Security");
  });

  it("a row's Split request is dropped once another row opens or the pane closes", async () => {
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts>
        <RightPaneToggle />
        <RequirementsSection opportunityId={OPP_ID} initial={list([requirement(1), requirement(2)])} />
        <RightPane />
      </ShellProviders>,
    );
    const first = () => screen.queryByRole("textbox", { name: "First Requirement" });

    await user.click(row(1));
    await user.click(within(rowOf(1)).getByRole("button", { name: "Split" }));
    expect(first()).toBeTruthy();
    await user.click(row(2));
    await user.click(row(1));
    expect(first()).toBeNull();

    await user.click(within(rowOf(1)).getByRole("button", { name: "Split" }));
    expect(first()).toBeTruthy();
    await user.click(within(pane()).getByRole("button", { name: "Close right pane" }));
    await user.click(screen.getByRole("button", { name: "Right pane" }));
    expect(within(pane()).getByRole("heading", { name: "[REQUIREMENT 1]" })).toBeTruthy();
    expect(first()).toBeNull();
  });
});
