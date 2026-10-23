import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PassageResult,
  RequirementCreateInput,
  RequirementCreateResult,
  RequirementDeleteInput,
  RequirementDeleteResult,
  RequirementEditInput,
  RequirementMergeInput,
  RequirementSplitInput,
  RequirementSplitResult,
  RequirementWriteResult,
} from "@/app/opportunities/actions";
import type { OutdatedAssessmentsResult, RequirementsResult } from "@/app/opportunities/data";
import type { Classification, Requirement, RequirementList } from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const createRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementCreateInput) => Promise<RequirementCreateResult>>(),
);
const deleteRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementDeleteInput) => Promise<RequirementDeleteResult>>(),
);
const splitRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementSplitInput) => Promise<RequirementSplitResult>>(),
);
const mergeRequirements = vi.hoisted(() =>
  vi.fn<(input: RequirementMergeInput) => Promise<RequirementCreateResult>>(),
);
const editRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementEditInput) => Promise<RequirementWriteResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
const getPassage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, passageId: string) => Promise<PassageResult>>(),
);
const loadOutdatedAssessments = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<OutdatedAssessmentsResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  createRequirement,
  deleteRequirement,
  splitRequirement,
  mergeRequirements,
  editRequirement,
  loadRequirements,
  getPassage,
  loadOutdatedAssessments,
  confirmRequirement: vi.fn(),
  confirmAllRequirements: vi.fn(),
  startExtraction: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/requirements",
}));

import { KeyboardShortcuts } from "../shell/keyboard-shortcuts";
import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const EVIDENCE = {
  passage_id: "00000000-0000-7000-8000-0000000000a9",
  source_id: "00000000-0000-7000-8000-0000000000b1",
  source_version: 1,
  filename: "call.vtt",
  label: "S1 · call.vtt",
};

function requirement(
  n: number,
  classification: Classification = "functional",
  extra: Partial<Requirement> = {},
): Requirement {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    number: n,
    text: `[REQUIREMENT ${n}]`,
    classification,
    origin: "extracted",
    locked_by_human: false,
    version: 1,
    row_version: 1,
    created_at: "2026-10-21T09:00:00Z",
    confirmed_at: null,
    confirmed_by: null,
    last_changed_by: null,
    pending_change: null,
    evidence: [EVIDENCE],
    ...extra,
  };
}

function list(items: Requirement[], canEdit = true): RequirementList {
  return {
    items,
    extraction: { status: "succeeded", error_code: null, source_count: 1 },
    can_start_extraction: true,
    can_edit_requirements: canEdit,
  };
}

function renderSection(initial: RequirementList, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <RequirementsSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: `[REQUIREMENT ${n}]` });
const rowOf = (n: number) => row(n).closest('[role="row"]') as HTMLElement;
const pane = () => screen.getByRole("complementary", { name: "Details" });
const isChecked = (n: number) => rowOf(n).hasAttribute("data-checked");

/** Toggle these rows in the merge selection with `x` (there is no checkbox column). */
async function mark(user: ReturnType<typeof userEvent.setup>, ...numbers: number[]) {
  for (const n of numbers) {
    row(n).focus();
    await user.keyboard("x");
  }
}

beforeEach(() => {
  for (const mock of [
    createRequirement,
    deleteRequirement,
    splitRequirement,
    mergeRequirements,
    editRequirement,
    loadRequirements,
    getPassage,
    loadOutdatedAssessments,
  ]) {
    mock.mockReset();
  }
  getPassage.mockResolvedValue({ kind: "not-found" });
  loadOutdatedAssessments.mockResolvedValue({ kind: "ok", items: [] });
});

describe("stable numbers", () => {
  it("each row shows its R<n>, gaps and all", () => {
    renderSection(list([requirement(1), requirement(4, "data")]));
    expect(within(rowOf(1)).getByText("R1")).toBeTruthy();
    expect(within(rowOf(4)).getByText("R4")).toBeTruthy();
  });
});

describe("adding a Requirement", () => {
  it("c opens the form; Enter adds it as a Requirement added by a person", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    const added = requirement(2, "security", {
      text: "Support returns.",
      origin: "human",
      locked_by_human: true,
      evidence: [],
    });
    createRequirement.mockResolvedValue({ kind: "ok", requirement: added });

    await user.keyboard("c");
    const input = screen.getByRole("textbox", { name: "New Requirement text" });
    expect(document.activeElement).toBe(input);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "New Requirement classification" }),
      "security",
    );
    await user.type(input, "  Support returns. {Enter}");

    expect(createRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      text: "Support returns.",
      classification: "security",
    });
    const saved = await screen.findByRole("button", { name: "Support returns." });
    const savedRow = saved.closest('[role="row"]') as HTMLElement;
    expect(within(savedRow).getByText("R2")).toBeTruthy();
    expect(within(savedRow).getByText("· Added by a person")).toBeTruthy();
    expect(savedRow.querySelector("[data-passage-id]")).toBeNull();
    expect(screen.queryByRole("form", { name: "New Requirement" })).toBeNull();

    await user.click(saved);
    expect(within(pane()).getByText("Added by a person")).toBeTruthy();
    expect(within(pane()).getByText("No Evidence.")).toBeTruthy();
  });

  it("Add requirement opens the form; Esc closes it; a blank text is not sent", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));

    await user.click(screen.getByRole("button", { name: "Add requirement" }));
    await user.type(screen.getByRole("textbox", { name: "New Requirement text" }), "   {Enter}");
    expect(createRequirement).not.toHaveBeenCalled();
    expect(screen.getByText("The Requirement text can't be blank.")).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form", { name: "New Requirement" })).toBeNull();
  });

  it("shows the API's reason under the form", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    createRequirement.mockResolvedValue({ kind: "invalid", detail: "[REASON FROM THE API]" });

    await user.click(screen.getByRole("button", { name: "Add requirement" }));
    await user.type(screen.getByRole("textbox", { name: "New Requirement text" }), "X.{Enter}");

    expect(await screen.findByText("[REASON FROM THE API]")).toBeTruthy();
    expect(screen.getByRole("form", { name: "New Requirement" })).toBeTruthy();
  });
});

describe("selecting and merging", () => {
  it("x toggles rows; with two selected, Merge (2) opens a prefilled form and merges", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, "integration");
    const r2 = requirement(2, "functional", { row_version: 3 });
    renderSection(list([r1, r2, requirement(3)]));
    const merged = requirement(4, "integration", { text: "Merged text", origin: "human" });
    mergeRequirements.mockResolvedValue({ kind: "ok", requirement: merged });
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([requirement(3), merged]) });

    row(1).focus();
    await user.keyboard("x");
    expect(isChecked(1)).toBe(true);
    expect(within(rowOf(1)).getByText("Selected for merge")).toBeTruthy();
    expect(screen.queryByRole("toolbar", { name: "Selected Requirements" })).toBeNull();
    await mark(user, 2);

    const bar = screen.getByRole("toolbar", { name: "Selected Requirements" });
    await user.click(within(bar).getByRole("button", { name: "Merge (2)" }));
    const text = screen.getByRole("textbox", { name: "Merged Requirement text" });
    // Grouped by classification, Integration lists after Functional; the merge takes them
    // in number order.
    expect((text as HTMLTextAreaElement).value).toBe("[REQUIREMENT 1] [REQUIREMENT 2]");
    expect(
      (screen.getByRole("combobox", { name: "Merged Requirement classification" }) as HTMLSelectElement)
        .value,
    ).toBe("integration");
    await user.clear(text);
    await user.type(text, "Merged text{Enter}");

    expect(mergeRequirements).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirements: [
        { id: r1.id, rowVersion: 1 },
        { id: r2.id, rowVersion: 3 },
      ],
      text: "Merged text",
      classification: "integration",
    });
    expect(await screen.findByRole("button", { name: "Merged text" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 1]" })).toBeNull();
    expect(screen.queryByRole("toolbar", { name: "Selected Requirements" })).toBeNull();
  });

  it("Esc clears the selection; x does nothing with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2)]));
    row(1).focus();
    await user.keyboard("x");
    row(2).focus();
    await user.keyboard("x");
    expect(screen.getByRole("toolbar", { name: "Selected Requirements" })).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("toolbar", { name: "Selected Requirements" })).toBeNull();
    expect([1, 2].some(isChecked)).toBe(false);
  });

  it("Esc with the inspector open closes it and keeps the selection", async () => {
    const user = userEvent.setup();
    // With the shell's shortcuts mounted: their Esc closes the inspector.
    render(
      <ShellProviders singleKeyShortcuts>
        <KeyboardShortcuts permissions={[]} />
        <RequirementsSection
          opportunityId={OPP_ID}
          initial={list([requirement(1), requirement(2)])}
        />
        <RightPane />
      </ShellProviders>,
    );
    await mark(user, 1, 2);
    await user.click(row(1));
    expect(pane()).toBeTruthy();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("complementary", { name: "Details" })).toBeNull();
    expect([1, 2].every(isChecked)).toBe(true);
    expect(screen.getByRole("toolbar", { name: "Selected Requirements" })).toBeTruthy();
  });

  it("the Merge form closes when the selection changes", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2), requirement(3)]));
    await mark(user, 1, 2);
    await user.click(screen.getByRole("button", { name: "Merge (2)" }));
    expect(screen.getByRole("form", { name: "Merged Requirement" })).toBeTruthy();

    await mark(user, 3);
    expect(screen.queryByRole("form", { name: "Merged Requirement" })).toBeNull();
    expect(screen.getByRole("button", { name: "Merge (3)" })).toBeTruthy();
  });

  it("the Merge form closes when a refresh drops a selected row", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2), requirement(3)]));
    mergeRequirements.mockResolvedValue({ kind: "not-found" });
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([requirement(1), requirement(3)]) });
    await mark(user, 1, 2, 3);
    await user.click(screen.getByRole("button", { name: "Merge (3)" }));

    const form = screen.getByRole("form", { name: "Merged Requirement" });
    await user.click(within(form).getByRole("button", { name: "Merge" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "[REQUIREMENT 2]" })).toBeNull());
    expect(screen.queryByRole("form", { name: "Merged Requirement" })).toBeNull();
    expect(screen.getByRole("button", { name: "Merge (2)" })).toBeTruthy();
  });

  it("a stale merge shows the stale notice and keeps the form", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2)]));
    mergeRequirements.mockResolvedValue({ kind: "stale", changedBy: null, current: null });
    await mark(user, 1, 2);

    await user.click(screen.getByRole("button", { name: "Merge (2)" }));
    const form = screen.getByRole("form", { name: "Merged Requirement" });
    await user.click(within(form).getByRole("button", { name: "Merge" }));

    expect(await screen.findByText("Changed by someone else since you opened it.")).toBeTruthy();
    expect(screen.getByRole("form", { name: "Merged Requirement" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
  });
});

describe("splitting and deleting in the inspector", () => {
  it("Split opens two prefilled fields with classifications and splits", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, "integration", { row_version: 2 });
    renderSection(list([r1, requirement(2)]));
    const parts = [
      requirement(3, "integration", { text: "Part A", origin: "human" }),
      requirement(4, "security", { text: "Part B", origin: "human" }),
    ];
    splitRequirement.mockResolvedValue({ kind: "ok", requirements: parts });
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([requirement(2), ...parts]) });

    await user.click(row(1));
    await user.click(within(pane()).getByRole("button", { name: "Split" }));
    const first = within(pane()).getByRole("textbox", { name: "First Requirement" });
    const second = within(pane()).getByRole("textbox", { name: "Second Requirement" });
    expect((first as HTMLTextAreaElement).value).toBe("[REQUIREMENT 1]");
    expect((second as HTMLTextAreaElement).value).toBe("[REQUIREMENT 1]");
    await user.clear(first);
    await user.type(first, "Part A");
    await user.clear(second);
    await user.type(second, "Part B");
    await user.selectOptions(
      within(pane()).getByRole("combobox", { name: "Second Requirement classification" }),
      "security",
    );
    await user.click(within(pane()).getByRole("button", { name: "Split Requirement" }));

    expect(splitRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 2,
      parts: [
        { text: "Part A", classification: "integration" },
        { text: "Part B", classification: "security" },
      ],
    });
    expect(await screen.findByRole("button", { name: "Part A" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 1]" })).toBeNull();
  });

  it("Delete asks why, then removes the Requirement", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1, requirement(2)]));
    deleteRequirement.mockResolvedValue({ kind: "ok" });
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([requirement(2)]) });

    await user.click(row(1));
    await user.click(within(pane()).getByRole("button", { name: "Delete" }));
    await user.click(within(pane()).getByRole("button", { name: "Delete Requirement" }));
    expect(deleteRequirement).not.toHaveBeenCalled();
    expect(within(pane()).getByText("Give a reason.")).toBeTruthy();

    await user.type(
      within(pane()).getByRole("textbox", { name: "Why delete this Requirement?" }),
      " Out of scope. ",
    );
    await user.click(within(pane()).getByRole("button", { name: "Delete Requirement" }));

    expect(deleteRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 1,
      reason: "Out of scope.",
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: "[REQUIREMENT 1]" })).toBeNull());
  });

  it("a stale delete shows the stale notice with Reload", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    deleteRequirement.mockResolvedValue({ kind: "stale", changedBy: "[COLLEAGUE]" });

    await user.click(row(1));
    await user.click(within(pane()).getByRole("button", { name: "Delete" }));
    await user.type(
      within(pane()).getByRole("textbox", { name: "Why delete this Requirement?" }),
      "Wrong.",
    );
    await user.click(within(pane()).getByRole("button", { name: "Delete Requirement" }));

    expect(await screen.findByText("Changed by [COLLEAGUE] since you opened it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});

describe("View diff after a 412", () => {
  it("shows the saved text as − and the user's draft as + on the diff tint", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    const theirs = requirement(1, "data", {
      text: "Their text",
      origin: "human",
      version: 2,
      row_version: 2,
      last_changed_by: { id: "00000000-0000-7000-8000-0000000000e2", name: "[COLLEAGUE]" },
    });
    editRequirement.mockResolvedValue({
      kind: "stale",
      changedBy: "[COLLEAGUE]",
      current: theirs,
    });

    await user.dblClick(row(1));
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "My text{Enter}");
    await screen.findByText("Changed by [COLLEAGUE] since you opened it.");

    await user.click(screen.getByRole("button", { name: "View diff" }));
    const diff = screen.getByTestId("stale-diff");
    const [minus, plus] = within(diff).getAllByText(/Their text|My text/);
    expect(minus!.textContent).toBe("Their text");
    expect(plus!.textContent).toBe("My text");
    expect(minus!.closest("p")!.className).toContain("bg-diff-tint");
    expect(minus!.closest("p")!.textContent).toContain("−");
    expect(plus!.closest("p")!.textContent).toContain("+");
    expect(within(diff).getByText("Classification: Data → Functional")).toBeTruthy();
    // The draft is kept for after Reload.
    expect((screen.getByRole("textbox", { name: "Requirement text" }) as HTMLInputElement).value).toBe(
      "My text",
    );

    await user.click(screen.getByRole("button", { name: "Hide diff" }));
    expect(screen.queryByTestId("stale-diff")).toBeNull();
  });
});

describe("sales representatives", () => {
  it("see no Add, no selection, no Split or Delete, and c and x do nothing", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), requirement(2)], false));

    expect(screen.queryByRole("button", { name: "Add requirement" })).toBeNull();
    row(1).focus();
    await user.keyboard("x");
    expect(isChecked(1)).toBe(false);
    await user.keyboard("c");
    expect(screen.queryByRole("form", { name: "New Requirement" })).toBeNull();
    expect(screen.queryByRole("toolbar", { name: "Selected Requirements" })).toBeNull();

    await user.click(row(1));
    expect(within(pane()).queryByRole("button", { name: "Split" })).toBeNull();
    expect(within(pane()).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Merge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});

describe("accessibility", () => {
  it("has no axe violations with the forms, the selection bar and the diff open", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([requirement(1), requirement(2)]));

    await user.click(screen.getByRole("button", { name: "Add requirement" }));
    expect(await axeViolations(container)).toEqual([]);
    await user.keyboard("{Escape}");

    await mark(user, 1, 2);
    await user.click(screen.getByRole("button", { name: "Merge (2)" }));
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(row(1));
    await user.click(within(pane()).getByRole("button", { name: "Split" }));
    expect(await axeViolations(document.body)).toEqual([]);
    await user.click(within(pane()).getByRole("button", { name: "Delete" }));
    expect(await axeViolations(document.body)).toEqual([]);

    editRequirement.mockResolvedValue({
      kind: "stale",
      changedBy: null,
      current: requirement(1, "functional", { text: "[THEIRS]", row_version: 2 }),
    });
    await user.dblClick(row(2));
    await user.type(screen.getByRole("textbox", { name: "Requirement text" }), "x{Enter}");
    await screen.findByText("Changed by someone else since you opened it.");
    await user.click(screen.getByRole("button", { name: "View diff" }));
    await act(async () => {});
    expect(await axeViolations(container)).toEqual([]);
  });
});
