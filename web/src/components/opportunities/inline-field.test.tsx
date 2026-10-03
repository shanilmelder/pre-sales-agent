import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { utcToday, type Opportunity } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const updateOpportunity = vi.hoisted(() => vi.fn());
const loadOpportunity = vi.hoisted(() => vi.fn());
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh }),
}));
vi.mock("@/app/opportunities/actions", () => ({ updateOpportunity, loadOpportunity }));

import { LiveRegionProvider } from "../shell/live-region";
import { EditableWorkspaceHeader, InlineField } from "./inline-field";

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: "00000000-0000-7000-8000-000000000001",
    title: "[TITLE]",
    customer_name: "[CUSTOMER]",
    products: ["AutoStore"],
    industry: "Retail",
    target_proposal_date: "2026-11-01",
    status: "intake",
    owner: { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" },
    collaborators: [],
    row_version: 2,
    created_at: "2026-10-04T10:00:00Z",
    last_changed_by: "[OWNER]",
    can_manage_collaborators: true,
    can_edit: true,
    ...overrides,
  };
}

function header(initial: Opportunity = opportunity()) {
  return (
    <LiveRegionProvider>
      <EditableWorkspaceHeader opportunity={initial} meta={<span>[META]</span>} />
    </LiveRegionProvider>
  );
}

function renderHeader(initial: Opportunity = opportunity()) {
  const utils = render(header(initial));
  return { user: userEvent.setup(), ...utils };
}

/** A promise the test resolves by hand, to look at the optimistic state. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const liveRegion = () => document.querySelector('[role="status"]');

beforeEach(() => {
  updateOpportunity.mockReset();
  loadOpportunity.mockReset();
  refresh.mockReset();
});

describe("InlineField", () => {
  function renderField(value = "Old") {
    const onCommit = vi.fn();
    render(
      <InlineField label="Edit name" inputLabel="Name" type="text" value={value} onCommit={onCommit}>
        <span>{value}</span>
      </InlineField>,
    );
    return { user: userEvent.setup(), onCommit };
  }

  it("blur saves the new value", async () => {
    const { user, onCommit } = renderField();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    const input = screen.getByRole("textbox", { name: "Name" });
    expect(document.activeElement).toBe(input);
    await user.clear(input);
    await user.type(input, "New");
    await user.tab();
    expect(onCommit).toHaveBeenCalledExactlyOnceWith("New");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("Enter saves once and returns focus to the button", async () => {
    const { user, onCommit } = renderField();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "er{Enter}");
    expect(onCommit).toHaveBeenCalledExactlyOnceWith("Older");
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Edit name" })),
    );
  });

  it("Esc reverts, sends nothing and leaves the field", async () => {
    const { user, onCommit } = renderField();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "changed{Escape}");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Old")).toBeTruthy();
    await user.click(document.body);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("an unchanged value sends nothing", async () => {
    const { user, onCommit } = renderField();
    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.keyboard("{Enter}");
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("EditableWorkspaceHeader", () => {
  it("shows the title and date as click-to-edit buttons, with no axe violations", async () => {
    const { user, container } = renderHeader();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit title" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit target proposal date" })).toBeTruthy();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(screen.getByText("[META]")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Edit target proposal date" }));
    const date = screen.getByLabelText("Target proposal date") as HTMLInputElement;
    expect(date.type).toBe("date");
    expect(date.min).toBe(utcToday());
    expect(date.value).toBe("2026-11-01");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("saves the title optimistically with the row version, then announces and refreshes", async () => {
    const answer = deferred<unknown>();
    updateOpportunity.mockReturnValue(answer.promise);
    const { user } = renderHeader();

    await user.click(screen.getByRole("button", { name: "Edit title" }));
    const input = screen.getByRole("textbox", { name: "Title" });
    await user.clear(input);
    await user.type(input, "  Phase 2  ");
    await user.tab();

    expect(updateOpportunity).toHaveBeenCalledWith({
      opportunityId: opportunity().id,
      rowVersion: 2,
      title: "Phase 2",
    });
    // Optimistic: the new title shows before the API answers.
    expect(screen.getByRole("heading", { level: 1, name: "Phase 2" })).toBeTruthy();

    answer.resolve({ kind: "ok", opportunity: opportunity({ title: "Phase 2", row_version: 3 }) });
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { level: 1, name: "Phase 2" })).toBeTruthy();
    await waitFor(() => expect(liveRegion()?.textContent).toBe("Title saved"));

    // The next save uses the returned version.
    updateOpportunity.mockResolvedValue({
      kind: "ok",
      opportunity: opportunity({ target_proposal_date: "2026-12-24", row_version: 4 }),
    });
    await user.click(screen.getByRole("button", { name: "Edit target proposal date" }));
    const date = screen.getByLabelText("Target proposal date");
    await user.clear(date);
    await user.type(date, "2026-12-24{Enter}");
    expect(updateOpportunity).toHaveBeenLastCalledWith({
      opportunityId: opportunity().id,
      rowVersion: 3,
      target_proposal_date: "2026-12-24",
    });
    expect(await screen.findByText("24 Dec 2026")).toBeTruthy();
  });

  it("a blank title shows the customer name; an unchanged one sends nothing", async () => {
    updateOpportunity.mockResolvedValue({
      kind: "ok",
      opportunity: opportunity({ title: "[CUSTOMER]", row_version: 3 }),
    });
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.clear(screen.getByRole("textbox", { name: "Title" }));
    await user.keyboard("{Enter}");
    expect(updateOpportunity).toHaveBeenCalledWith(expect.objectContaining({ title: "" }));
    expect(await screen.findByRole("heading", { level: 1, name: "[CUSTOMER]" })).toBeTruthy();

    // Spaces around the same title change nothing.
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "  {Enter}");
    expect(updateOpportunity).toHaveBeenCalledTimes(1);
  });

  it("422: rolls back and shows the API's reason under the field, announced", async () => {
    updateOpportunity.mockResolvedValue({
      kind: "invalid",
      detail: "The target proposal date can't be in the past.",
    });
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit target proposal date" }));
    const date = screen.getByLabelText("Target proposal date");
    await user.clear(date);
    await user.type(date, "2020-01-01");
    await user.tab();

    const reason = await screen.findByText("The target proposal date can't be in the past.");
    expect(screen.getByText("1 Nov 2026")).toBeTruthy(); // rolled back
    const button = screen.getByRole("button", { name: "Edit target proposal date" });
    expect(button.getAttribute("aria-describedby")).toBe(reason.id);
    await waitFor(() =>
      expect(liveRegion()?.textContent).toBe(
        "Target proposal date not saved. The target proposal date can't be in the past.",
      ),
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("a title over 200 code points is refused without calling the API", async () => {
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    const input = screen.getByRole("textbox", { name: "Title" });
    await user.clear(input);
    await user.click(input);
    await user.paste("😀".repeat(201));
    await user.tab();
    expect(await screen.findByText("The title can be at most 200 characters.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(updateOpportunity).not.toHaveBeenCalled();
  });

  it("412: rolls back, says who changed it with Reload, and Reload discards the edit", async () => {
    updateOpportunity.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    loadOpportunity.mockResolvedValue({
      kind: "ok",
      opportunity: opportunity({ title: "[THEIR TITLE]", row_version: 5 }),
    });
    const { user, container } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), " mine{Enter}");

    expect(await screen.findByText("Changed by [OTHER] since you opened it.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    const reload = screen.getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    expect(await axeViolations(container)).toEqual([]);
    // Locked: nothing can be overwritten until Reload.
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(updateOpportunity).toHaveBeenCalledTimes(1);

    await user.click(reload);
    expect(await screen.findByRole("heading", { level: 1, name: "[THEIR TITLE]" })).toBeTruthy();
    expect(screen.queryByText(/Changed by/, { selector: "p" })).toBeNull();
    expect(loadOpportunity).toHaveBeenCalledWith(opportunity().id);
    expect(refresh).toHaveBeenCalledTimes(1);

    // The next save sends the reloaded version.
    updateOpportunity.mockResolvedValue({ kind: "ok", opportunity: opportunity({ row_version: 6 }) });
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    expect(updateOpportunity).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowVersion: 5, title: "[THEIR TITLE]!" }),
    );
  });

  it.each([
    ["403", { kind: "forbidden" }, "Only the owner can edit this Opportunity.", 1],
    ["404", { kind: "not-found" }, "You don't have access to this Opportunity", 1],
    ["network", { kind: "error" }, "The change could not be saved. Try again.", 0],
  ])("%s: rolls back with a short message", async (_label, result, message, refreshes) => {
    updateOpportunity.mockResolvedValue(result);
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    // 403/404: access changed, so `can_edit` is re-read from the server.
    expect(refresh).toHaveBeenCalledTimes(refreshes);
  });

  it("clearing the date and leaving sends nothing and keeps the date", async () => {
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit target proposal date" }));
    await user.clear(screen.getByLabelText("Target proposal date"));
    await user.tab();
    expect(updateOpportunity).not.toHaveBeenCalled();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(document.querySelector(".text-destructive")).toBeNull();
  });

  it("Reload failing keeps the stale notice and the lock, and says so", async () => {
    updateOpportunity.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    loadOpportunity.mockResolvedValueOnce({ kind: "error" });
    loadOpportunity.mockRejectedValueOnce(new Error("offline"));
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    const notice = "Changed by [OTHER] since you opened it.";
    expect(await screen.findByText(notice, { selector: "p" })).toBeTruthy();

    // First an `error` answer, then a thrown action: both keep the notice and the lock.
    for (let attempt = 1; attempt <= 2; attempt++) {
      await user.click(screen.getByRole("button", { name: "Reload" }));
      await waitFor(() => expect(loadOpportunity).toHaveBeenCalledTimes(attempt));
      if (attempt === 1) {
        // The live region speaks at most once per 5 s, so this waits out the throttle.
        await waitFor(
          () =>
            expect(liveRegion()?.textContent).toBe(
              "The Opportunity could not be reloaded. Try again.",
            ),
          { timeout: 7000 },
        );
      }
      expect(screen.getByText(notice, { selector: "p" })).toBeTruthy();
      await user.click(screen.getByRole("button", { name: "Edit title" }));
      expect(screen.queryByRole("textbox")).toBeNull(); // still locked
    }
    expect(updateOpportunity).toHaveBeenCalledTimes(1);
  }, 15000);

  it("Reload finding no access shows the no-access sentence", async () => {
    updateOpportunity.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    loadOpportunity.mockResolvedValue({ kind: "not-found" });
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    await user.click(await screen.findByRole("button", { name: "Reload" }));
    expect(
      await screen.findByText("You don't have access to this Opportunity", { selector: "p" }),
    ).toBeTruthy();
  });

  it("a newer version from a refresh clears the header's 412 notice and unlocks it", async () => {
    updateOpportunity.mockResolvedValueOnce({ kind: "stale", changedBy: "[OTHER]" });
    const { user, rerender } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();

    rerender(header(opportunity({ title: "[THEIR TITLE]", row_version: 3 })));
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
    expect(screen.queryByText(/Changed by/, { selector: "p" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "[THEIR TITLE]" })).toBeTruthy();
    updateOpportunity.mockResolvedValue({ kind: "ok", opportunity: opportunity({ row_version: 4 }) });
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "?{Enter}");
    expect(updateOpportunity).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowVersion: 3, title: "[THEIR TITLE]?" }),
    );
  });

  it("a save's answer never replaces a newer version a refresh already brought", async () => {
    const answer = deferred<unknown>();
    updateOpportunity.mockReturnValueOnce(answer.promise);
    const { user, rerender } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    // While the save is in flight, a refresh brings version 4 (save + a collaborator change).
    rerender(header(opportunity({ title: "[TITLE]!", row_version: 4 })));
    answer.resolve({ kind: "ok", opportunity: opportunity({ title: "[TITLE]!", row_version: 3 }) });
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));

    updateOpportunity.mockResolvedValue({ kind: "ok", opportunity: opportunity({ row_version: 5 }) });
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "?{Enter}");
    expect(updateOpportunity).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowVersion: 4 }),
    );
  });

  it("a thrown server action is a network error too", async () => {
    updateOpportunity.mockRejectedValue(new Error("offline"));
    const { user } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    expect(await screen.findByText("The change could not be saved. Try again.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
  });

  it("follows a newer row version from a refresh (e.g. after a collaborator change)", async () => {
    updateOpportunity.mockResolvedValue({ kind: "ok", opportunity: opportunity({ row_version: 5 }) });
    const { user, rerender } = renderHeader();
    rerender(header(opportunity({ row_version: 4 })));
    // An older one (a refresh racing a save) is ignored.
    rerender(header(opportunity({ row_version: 3 })));
    await user.click(screen.getByRole("button", { name: "Edit title" }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), "!{Enter}");
    expect(updateOpportunity).toHaveBeenCalledWith(expect.objectContaining({ rowVersion: 4 }));
  });
});
