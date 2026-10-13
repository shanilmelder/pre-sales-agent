import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PassageResult } from "@/app/opportunities/actions";
import type { RequirementsResult } from "@/app/opportunities/data";
import type { Classification, Passage, Requirement, RequirementList } from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const getPassage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, passageId: string) => Promise<PassageResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  getPassage,
  loadRequirements,
  startExtraction: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/requirements",
}));

import { KeyboardShortcuts } from "../shell/keyboard-shortcuts";
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders, useShell } from "../shell/shell-context";
import { RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function passageId(n: number, i: number): string {
  return `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}${i}aa`;
}

function requirement(n: number, classification: Classification, ...files: string[]): Requirement {
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
    evidence: files.map((file, i) => ({
      passage_id: passageId(n, i),
      source_id: `00000000-0000-7000-8000-0000000000b${i}`,
      source_version: 2,
      filename: file,
      label: `S${i + 1} · ${file}`,
    })),
  };
}

function passage(id: string, quote: string, filename = "call.vtt"): Passage {
  return {
    passage_id: id,
    source_id: "00000000-0000-7000-8000-0000000000b0",
    source_version: 2,
    filename,
    label: `S1 · ${filename}`,
    before: "…we said\nthat ",
    text: quote,
    after: " and more.",
  };
}

const R1 = requirement(1, "functional", "call.vtt", "mail.eml");
const R2 = requirement(2, "integration", "notes.txt");
const QUOTES: Record<string, string> = {
  [passageId(1, 0)]: "[QUOTE 1A]",
  [passageId(1, 1)]: "[QUOTE 1B]",
  [passageId(2, 0)]: "[QUOTE 2A]",
};

function list(items: Requirement[], status: "succeeded" | "running" = "succeeded"): RequirementList {
  return {
    items,
    extraction: { status, error_code: null, source_count: 2 },
    can_start_extraction: true,
    can_edit_requirements: false,
  };
}

/** Stands in for the shell's right-pane toggle. */
function PaneToggle() {
  const { toggleRightPane } = useShell();
  return (
    <button type="button" id={RIGHT_PANE_TOGGLE_ID} onClick={toggleRightPane}>
      Toggle
    </button>
  );
}

function ui(initial: RequirementList) {
  return (
    <ShellProviders singleKeyShortcuts>
      <KeyboardShortcuts permissions={["opportunities.opportunity.create"]} />
      <PaneToggle />
      <RequirementsSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>
  );
}

const pane = () => screen.queryByRole("complementary", { name: "Details" });
const row = (n: number) => screen.getByRole("button", { name: `[REQUIREMENT ${n}]` });
const chip = (name: string) => within(pane()!).getByRole("button", { name });

beforeEach(() => {
  getPassage.mockReset();
  loadRequirements.mockReset();
  getPassage.mockImplementation(async (_opp, id) => ({
    kind: "ok",
    passage: passage(id, QUOTES[id] ?? "[QUOTE]"),
  }));
});

describe("Requirements list and Evidence inspector", () => {
  it("Enter opens the row: Requirement, first passage highlighted, focus on the first chip", async () => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    expect(pane()).toBeNull();
    await user.tab(); // Toggle
    await user.tab(); // the list's one tab stop: the first row
    expect(document.activeElement).toBe(row(1));

    await user.keyboard("{Enter}");

    await waitFor(() => expect(document.activeElement).toBe(chip("S1 · call.vtt")));
    const inspector = pane()!;
    expect(within(inspector).getByRole("heading", { name: "[REQUIREMENT 1]" })).toBeTruthy();
    expect(within(inspector).getByText("Functional")).toBeTruthy();
    expect(within(inspector).getByText("Extracted")).toBeTruthy();
    const chips = within(within(inspector).getByRole("group", { name: "Evidence" })).getAllByRole(
      "button",
    );
    expect(chips.map((c) => [c.textContent, c.getAttribute("aria-pressed")])).toEqual([
      ["S1 · call.vtt", "true"],
      ["S2 · mail.eml", "false"],
    ]);
    const mark = await within(inspector).findByText("[QUOTE 1A]");
    expect(mark.tagName).toBe("MARK");
    expect(mark.className).toContain("bg-evidence-highlight");
    const quote = mark.closest("blockquote")!;
    expect(quote.textContent).toBe("…we said\nthat [QUOTE 1A] and more.");
    expect(quote.className).toContain("whitespace-pre-wrap");
    expect(within(inspector).getByText("call.vtt")).toBeTruthy();
    expect(within(inspector).getByText("v2")).toBeTruthy();
    expect(getPassage).toHaveBeenCalledWith(OPP_ID, passageId(1, 0));
    expect(row(1).closest('[role="row"]')!.getAttribute("aria-selected")).toBe("true");
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("j/k and the arrow keys move between rows across groups; Space opens", async () => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    await user.tab();
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("j"); // stays on the last row
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard(" ");
    await waitFor(() => expect(pane()).not.toBeNull());
    expect(within(pane()!).getByRole("heading", { name: "[REQUIREMENT 1]" })).toBeTruthy();
  });

  it("a click on the second chip shows its passage and moves aria-pressed", async () => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    await user.click(row(1));
    await waitFor(() => expect(pane()).not.toBeNull());
    expect(document.activeElement).toBe(row(1)); // a pointer open leaves focus on the row
    await within(pane()!).findByText("[QUOTE 1A]");

    await user.click(chip("S2 · mail.eml"));

    expect(await within(pane()!).findByText("[QUOTE 1B]")).toBeTruthy();
    expect(within(pane()!).queryByText("[QUOTE 1A]")).toBeNull();
    expect(chip("S2 · mail.eml").getAttribute("aria-pressed")).toBe("true");
    expect(chip("S1 · call.vtt").getAttribute("aria-pressed")).toBe("false");
    expect(getPassage).toHaveBeenLastCalledWith(OPP_ID, passageId(1, 1));
  });

  it("a chip in a list row opens that Requirement with that passage", async () => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    const r1Row = row(1).closest<HTMLElement>('[role="row"]')!;

    await user.click(within(r1Row).getByRole("button", { name: "S2 · mail.eml" }));

    await waitFor(() => expect(pane()).not.toBeNull());
    expect(within(pane()!).getByRole("heading", { name: "[REQUIREMENT 1]" })).toBeTruthy();
    expect(await within(pane()!).findByText("[QUOTE 1B]")).toBeTruthy();
    expect(chip("S2 · mail.eml").getAttribute("aria-pressed")).toBe("true");
    expect(getPassage).toHaveBeenCalledTimes(1);

    // Another row's chip switches the inspector to that Requirement.
    const r2Row = row(2).closest<HTMLElement>('[role="row"]')!;
    await user.click(within(r2Row).getByRole("button", { name: "S1 · notes.txt" }));
    expect(await within(pane()!).findByText("[QUOTE 2A]")).toBeTruthy();
    expect(r2Row.getAttribute("aria-selected")).toBe("true");
    expect(r1Row.getAttribute("aria-selected")).toBe("false");
  });

  it("a late reply for an earlier chip doesn't replace the shown passage", async () => {
    const user = userEvent.setup();
    const pending: Record<string, (result: PassageResult) => void> = {};
    getPassage.mockImplementation(
      (_opp, id) => new Promise<PassageResult>((resolve) => (pending[id] = resolve)),
    );
    render(ui(list([R1])));
    await user.click(row(1));
    await waitFor(() => expect(pending[passageId(1, 0)]).toBeDefined());

    await user.click(chip("S2 · mail.eml"));
    await waitFor(() => expect(pending[passageId(1, 1)]).toBeDefined());
    await act(async () => {
      pending[passageId(1, 1)]({ kind: "ok", passage: passage(passageId(1, 1), "[QUOTE 1B]") });
    });
    expect(await within(pane()!).findByText("[QUOTE 1B]")).toBeTruthy();
    await act(async () => {
      pending[passageId(1, 0)]({ kind: "ok", passage: passage(passageId(1, 0), "[QUOTE 1A]") });
    });

    expect(within(pane()!).getByText("[QUOTE 1B]")).toBeTruthy();
    expect(within(pane()!).queryByText("[QUOTE 1A]")).toBeNull();
    expect(chip("S2 · mail.eml").getAttribute("aria-pressed")).toBe("true");
  });

  it("reopening the pane with the toggle after a keyboard open doesn't take focus", async () => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(document.activeElement).toBe(chip("S1 · call.vtt")));
    await user.click(within(pane()!).getByRole("button", { name: "Close right pane" }));
    await waitFor(() => expect(document.activeElement).toBe(row(1)));

    await user.click(screen.getByRole("button", { name: "Toggle" }));
    await waitFor(() => expect(pane()).not.toBeNull());
    await within(pane()!).findByRole("heading", { name: "[REQUIREMENT 1]" });

    expect(pane()!.contains(document.activeElement)).toBe(false);
  });

  it("says Loading passage… while the request is in flight", async () => {
    const user = userEvent.setup();
    getPassage.mockImplementation(() => new Promise(() => {}));
    render(ui(list([R1])));
    await user.click(row(1));
    expect(await within(pane()!).findByText("Loading passage…")).toBeTruthy();
  });

  it.each([
    ["an error result", () => Promise.resolve<PassageResult>({ kind: "error" })],
    ["a thrown call", () => Promise.reject(new Error("network"))],
  ])("on failure (%s) shows the error line with Retry, which refetches", async (_, failure) => {
    const user = userEvent.setup();
    getPassage.mockImplementationOnce(failure);
    render(ui(list([R1])));
    await user.click(row(1));

    expect(await within(pane()!).findByText("The passage couldn't be loaded.")).toBeTruthy();
    expect(await axeViolations(pane()!)).toEqual([]);
    await user.click(within(pane()!).getByRole("button", { name: "Retry" }));

    expect(await within(pane()!).findByText("[QUOTE 1A]")).toBeTruthy();
    expect(within(pane()!).queryByText("The passage couldn't be loaded.")).toBeNull();
    expect(getPassage).toHaveBeenCalledTimes(2);
  });

  it("a 404 says the passage is no longer available", async () => {
    const user = userEvent.setup();
    getPassage.mockResolvedValue({ kind: "not-found" });
    render(ui(list([R1])));
    await user.click(row(1));
    expect(await within(pane()!).findByText("This passage is no longer available.")).toBeTruthy();
    expect(within(pane()!).queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows Nothing selected. when a poll removes the selected Requirement", async () => {
    const user = userEvent.setup();
    const R3 = requirement(3, "functional", "call.vtt");
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([R3]) });
    render(ui(list([R1], "running")));
    await user.click(row(1));
    await within(pane()!).findByText("[QUOTE 1A]");

    await waitFor(() => expect(screen.getByText("[REQUIREMENT 3]")).toBeTruthy(), {
      timeout: 4000,
    });

    expect(pane()).not.toBeNull();
    // The pane's content count drops in an effect, a render after the list updates.
    expect(await within(pane()!).findByText("Nothing selected.")).toBeTruthy();
    expect(within(pane()!).queryByText("[REQUIREMENT 1]")).toBeNull();
  }, 10_000);

  it.each([
    ["Close", async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(within(pane()!).getByRole("button", { name: "Close right pane" }));
    }],
    ["Esc", async (user: ReturnType<typeof userEvent.setup>) => {
      await user.keyboard("{Escape}");
    }],
  ])("%s after a keyboard open returns focus to the row", async (_, close) => {
    const user = userEvent.setup();
    render(ui(list([R1, R2])));
    await user.tab();
    await user.tab();
    await user.keyboard("j{Enter}");
    await waitFor(() => expect(document.activeElement).toBe(chip("S1 · notes.txt")));

    await close(user);

    expect(pane()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(row(2)));
  });
});
