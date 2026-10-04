import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConfirmAllResult,
  PassageResult,
  RequirementEditInput,
  RequirementConfirmInput,
  RequirementWriteResult,
} from "@/app/opportunities/actions";
import type { RequirementsResult } from "@/app/opportunities/data";
import type { Classification, Requirement, RequirementList } from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const editRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementEditInput) => Promise<RequirementWriteResult>>(),
);
const confirmRequirement = vi.hoisted(() =>
  vi.fn<(input: RequirementConfirmInput) => Promise<RequirementWriteResult>>(),
);
const confirmAllRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<ConfirmAllResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
const getPassage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, passageId: string) => Promise<PassageResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  editRequirement,
  confirmRequirement,
  confirmAllRequirements,
  loadRequirements,
  getPassage,
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
import { ShellProviders } from "../shell/shell-context";
import { RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function requirement(
  n: number,
  classification: Classification = "functional",
  extra: Partial<Requirement> = {},
): Requirement {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    text: `[REQUIREMENT ${n}]`,
    classification,
    origin: "extracted",
    locked_by_human: false,
    version: 1,
    row_version: 1,
    created_at: "2026-10-04T13:05:00Z",
    confirmed_at: null,
    confirmed_by: null,
    last_changed_by: null,
    evidence: [],
    ...extra,
  };
}

const ME = { id: "00000000-0000-7000-8000-0000000000e1", name: "[OWNER]" };

function confirmed(item: Requirement): Requirement {
  return {
    ...item,
    confirmed_at: "2026-10-04T14:00:00Z",
    confirmed_by: ME,
    last_changed_by: ME,
    locked_by_human: true,
    row_version: item.row_version + 1,
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
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  editRequirement.mockReset();
  confirmRequirement.mockReset();
  confirmAllRequirements.mockReset();
  loadRequirements.mockReset();
  getPassage.mockReset();
});

describe("editing Requirements inline", () => {
  it("e edits the focused row; Enter saves with If-Match and focus returns to the row", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1, requirement(2)]));
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        text: "Fixed wording.",
        origin: "human",
        version: 2,
        row_version: 2,
      },
    });
    await user.tab(); // Confirm all (2)
    await user.tab(); // the list's one tab stop: the first row
    expect(document.activeElement).toBe(row(1));

    await user.keyboard("e");
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe("[REQUIREMENT 1]");
    await user.clear(input);
    await user.type(input, "  Fixed wording. {Enter}");

    expect(editRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 1,
      text: "Fixed wording.",
    });
    const saved = await screen.findByRole("button", { name: "Fixed wording." });
    await waitFor(() => expect(document.activeElement).toBe(saved));
    expect(within(saved.closest('[role="row"]') as HTMLElement).getByText("Edited")).toBeTruthy();
  });

  it("a double-click on the text edits; blur saves; Esc reverts without saving", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        text: "On blur.",
        origin: "human",
        version: 2,
        row_version: 2,
      },
    });

    await user.dblClick(row(1));
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "Never saved.{Escape}");
    expect(editRequirement).not.toHaveBeenCalled();
    expect(row(1)).toBeTruthy();

    await user.dblClick(row(1));
    const again = screen.getByRole("textbox", { name: "Requirement text" });
    await user.clear(again);
    await user.type(again, "On blur.");
    await user.click(document.body);
    expect(await screen.findByRole("button", { name: "On blur." })).toBeTruthy();
    expect(editRequirement).toHaveBeenCalledTimes(1);
  });

  it("an unchanged or blank text is not sent", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    await user.dblClick(row(1));
    await user.keyboard("{Enter}");
    expect(editRequirement).not.toHaveBeenCalled();

    await user.dblClick(row(1));
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "   {Enter}");
    expect(editRequirement).not.toHaveBeenCalled();
    expect(screen.getByText("The Requirement text can't be blank.")).toBeTruthy();
    // The editor stays open with what was typed.
    expect(screen.getByRole("textbox", { name: "Requirement text" })).toBeTruthy();
  });

  it("after Enter on blank text, typing and blurring sends the save", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: { ...r1, text: "Typed later.", origin: "human", version: 2, row_version: 2 },
    });

    await user.dblClick(row(1));
    await user.clear(screen.getByRole("textbox", { name: "Requirement text" }));
    await user.keyboard("{Enter}");
    expect(screen.getByText("The Requirement text can't be blank.")).toBeTruthy();
    await user.keyboard("{Enter}"); // the same blank text again: a fresh input each time
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    expect(document.activeElement).toBe(input);
    await user.type(input, "Typed later.");
    await user.click(document.body);

    expect(editRequirement).toHaveBeenCalledWith(
      expect.objectContaining({ requirementId: r1.id, rowVersion: 1, text: "Typed later." }),
    );
    expect(await screen.findByRole("button", { name: "Typed later." })).toBeTruthy();
  });

  it("e does nothing with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]), false);
    await user.tab();
    await user.keyboard("e");
    expect(screen.queryByRole("textbox", { name: "Requirement text" })).toBeNull();
  });

  it("on 412 shows who changed it with Reload, and the input keeps the user's text", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({
      kind: "stale",
      changedBy: "[COLLEAGUE]",
    });
    const newer = {
      ...r1,
      text: "Their wording.",
      row_version: 2,
      version: 2,
      origin: "human" as const,
    };
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([newer]) });

    await user.dblClick(row(1));
    const input = screen.getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "My wording.{Enter}");

    expect(await screen.findByText("Changed by [COLLEAGUE] since you opened it.")).toBeTruthy();
    const reload = screen.getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    const kept = screen.getByRole("textbox", {
      name: "Requirement text",
    }) as HTMLInputElement;
    expect(kept.value).toBe("My wording.");
    expect(screen.getByRole("button", { name: "Confirm: [REQUIREMENT 1]" })).toHaveProperty(
      "disabled",
      true,
    );

    await user.click(reload);
    await waitFor(() =>
      expect(screen.queryByText("Changed by [COLLEAGUE] since you opened it.")).toBeNull(),
    );
    const still = screen.getByRole("textbox", {
      name: "Requirement text",
    }) as HTMLInputElement;
    expect(still.value).toBe("My wording.");

    // Saving again goes against the reloaded version.
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...newer,
        text: "My wording.",
        row_version: 3,
        version: 3,
      },
    });
    still.focus();
    await user.keyboard("{Enter}");
    expect(editRequirement).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowVersion: 2, text: "My wording." }),
    );
  });
});

describe("confirming Requirements", () => {
  it("Confirm on a row confirms it and shows Confirmed", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1, requirement(2)]));
    confirmRequirement.mockResolvedValue({
      kind: "ok",
      requirement: confirmed(r1),
    });

    await user.click(screen.getByRole("button", { name: "Confirm: [REQUIREMENT 1]" }));

    expect(confirmRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 1,
    });
    const confirmedRow = row(1).closest('[role="row"]') as HTMLElement;
    await waitFor(() => expect(within(confirmedRow).getByText("Confirmed")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Confirm: [REQUIREMENT 1]" })).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm all (1)" })).toBeTruthy();
  });

  it("Confirm all (N) counts the unconfirmed, confirms them and reloads", async () => {
    const user = userEvent.setup();
    const items = [requirement(1), requirement(2), confirmed(requirement(3))];
    renderSection(list(items));
    confirmAllRequirements.mockResolvedValue({ kind: "ok", count: 2 });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list(items.map((i) => (i.confirmed_at ? i : confirmed(i)))),
    });

    await user.click(screen.getByRole("button", { name: "Confirm all (2)" }));

    expect(confirmAllRequirements).toHaveBeenCalledWith(OPP_ID);
    await waitFor(() => expect(screen.getAllByText("Confirmed")).toHaveLength(3));
    expect(screen.queryByRole("button", { name: /Confirm all/ })).toBeNull();
  });

  it("Confirm all is hidden when everything is confirmed", () => {
    renderSection(list([confirmed(requirement(1))]));
    expect(screen.queryByRole("button", { name: /Confirm all/ })).toBeNull();
    expect(screen.getByText("Confirmed")).toBeTruthy();
  });
});

describe("the inspector", () => {
  it("saves the text edited in the inspector", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: { ...r1, text: "Inspector wording.", origin: "human", version: 2, row_version: 2 },
    });

    await user.click(row(1));
    const inspector = pane();
    await user.click(within(inspector).getByRole("button", { name: "Edit Requirement text" }));
    const input = within(inspector).getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "Inspector wording.{Enter}");

    expect(editRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 1,
      text: "Inspector wording.",
    });
    expect(
      await within(inspector).findByRole("heading", { name: "Inspector wording." }),
    ).toBeTruthy();
  });

  it("a blank text in the inspector shows the reason there and keeps the user's text", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));

    await user.click(row(1));
    const inspector = pane();
    await user.click(within(inspector).getByRole("button", { name: "Edit Requirement text" }));
    const input = within(inspector).getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "   {Enter}");

    expect(editRequirement).not.toHaveBeenCalled();
    expect(within(inspector).getByText("The Requirement text can't be blank.")).toBeTruthy();
    // The list row's editor stays closed and focus stays in the pane.
    expect(screen.queryAllByRole("textbox", { name: "Requirement text" })).toHaveLength(0);
    expect(inspector.contains(document.activeElement)).toBe(true);
    await user.click(within(inspector).getByRole("button", { name: "Edit Requirement text" }));
    expect(
      (within(inspector).getByRole("textbox", { name: "Requirement text" }) as HTMLInputElement)
        .value,
    ).toBe("   ");
  });

  it("a 412 from the inspector shows who changed it there and keeps the user's text", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({ kind: "stale", changedBy: "[COLLEAGUE]" });

    await user.click(row(1));
    const inspector = pane();
    await user.click(within(inspector).getByRole("button", { name: "Edit Requirement text" }));
    const input = within(inspector).getByRole("textbox", { name: "Requirement text" });
    await user.clear(input);
    await user.type(input, "My wording.{Enter}");

    await waitFor(() =>
      expect(
        within(inspector).getByText("Changed by [COLLEAGUE] since you opened it."),
      ).toBeTruthy(),
    );
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.queryAllByRole("textbox", { name: "Requirement text" })).toHaveLength(0);

    loadRequirements.mockResolvedValue({ kind: "ok", list: list([{ ...r1, row_version: 2 }]) });
    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reload" })).toBeNull());
    await user.click(within(inspector).getByRole("button", { name: "Edit Requirement text" }));
    expect(
      (within(inspector).getByRole("textbox", { name: "Requirement text" }) as HTMLInputElement)
        .value,
    ).toBe("My wording.");
  });

  it("has a classification select, an editable text and Confirm", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, "functional");
    renderSection(list([r1]));
    editRequirement.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        classification: "security",
        origin: "human",
        version: 2,
        row_version: 2,
      },
    });
    confirmRequirement.mockResolvedValue({
      kind: "ok",
      requirement: confirmed({
        ...r1,
        classification: "security",
        origin: "human",
        version: 2,
        row_version: 2,
      }),
    });

    await user.click(row(1));
    const inspector = pane();
    await user.selectOptions(
      within(inspector).getByRole("combobox", { name: "Classification" }),
      "security",
    );
    expect(editRequirement).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 1,
      classification: "security",
    });
    await waitFor(() => expect(within(inspector).getByText("Edited")).toBeTruthy());
    expect(within(inspector).getByRole("button", { name: "Edit Requirement text" })).toBeTruthy();

    await user.click(within(inspector).getByRole("button", { name: "Confirm" }));
    expect(confirmRequirement).toHaveBeenCalledWith(expect.objectContaining({ rowVersion: 2 }));
    await waitFor(() => expect(within(inspector).getByText("Confirmed")).toBeTruthy());
    expect(within(inspector).queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(await axeViolations(document.body)).toEqual([]);
  });
});

describe("for those who may not edit (sales representatives, readers)", () => {
  it("hides inline edit, Confirm, Confirm all and the inspector controls", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1), confirmed(requirement(2))], false));

    expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    expect(screen.getByText("Confirmed")).toBeTruthy();
    await user.dblClick(row(1));
    await user.keyboard("e");
    expect(screen.queryByRole("textbox", { name: "Requirement text" })).toBeNull();
    const inspector = pane();
    expect(within(inspector).queryByRole("combobox")).toBeNull();
    expect(
      within(inspector).queryByRole("button", {
        name: "Edit Requirement text",
      }),
    ).toBeNull();
    expect(within(inspector).queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("a 403 says who may edit and re-reads the list", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    confirmRequirement.mockResolvedValue({ kind: "forbidden" });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list([requirement(1)], false),
    });

    await user.click(screen.getByRole("button", { name: "Confirm: [REQUIREMENT 1]" }));

    expect(
      await screen.findByText(
        "Only the owner and collaborators, except sales representatives, can edit Requirements.",
      ),
    ).toBeTruthy();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Confirm: [REQUIREMENT 1]" })).toBeNull(),
    );
  });
});

describe("accessibility", () => {
  it("has no axe violations while editing and while stale", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([requirement(1), confirmed(requirement(2, "data"))]));
    expect(await axeViolations(container)).toEqual([]);

    await user.dblClick(row(1));
    expect(await axeViolations(container)).toEqual([]);

    editRequirement.mockResolvedValue({ kind: "stale", changedBy: null });
    await user.type(screen.getByRole("textbox", { name: "Requirement text" }), "x{Enter}");
    await screen.findByText("Changed by someone else since you opened it.");
    await act(async () => {});
    expect(await axeViolations(container)).toEqual([]);
  });
});
