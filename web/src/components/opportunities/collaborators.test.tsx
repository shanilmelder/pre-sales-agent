import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const changeCollaborator = vi.hoisted(() => vi.fn());
const loadOpportunity = vi.hoisted(() => vi.fn());
const searchUsers = vi.hoisted(() => vi.fn());
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  changeCollaborator,
  loadOpportunity,
  searchUsers,
}));

import { LiveRegionProvider } from "../shell/live-region";
import { Collaborators } from "./collaborators";

const OWNER = { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" };
const MEMBER = { id: "00000000-0000-7000-8000-0000000000b2", name: "[MEMBER]" };
const CANDIDATE = {
  id: "00000000-0000-7000-8000-0000000000c3",
  name: "[CANDIDATE]",
  email: "candidate@example.invalid",
};

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: "00000000-0000-7000-8000-000000000001",
    title: "[TITLE]",
    customer_name: "[CUSTOMER]",
    products: ["AutoStore"],
    industry: "Retail",
    target_proposal_date: "2026-11-01",
    status: "intake",
    owner: OWNER,
    collaborators: [MEMBER],
    row_version: 2,
    created_at: "2026-10-04T10:00:00Z",
    last_changed_by: "[OWNER]",
    can_manage_collaborators: true,
    ...overrides,
  };
}

function renderPanel(initial: Opportunity = opportunity()) {
  const utils = render(
    <LiveRegionProvider>
      <Collaborators initial={initial} />
    </LiveRegionProvider>,
  );
  return { user: userEvent.setup(), ...utils };
}

beforeEach(() => {
  changeCollaborator.mockReset();
  loadOpportunity.mockReset();
  searchUsers.mockReset();
  refresh.mockReset();
  searchUsers.mockResolvedValue({ kind: "ok", users: [CANDIDATE, { ...OWNER, email: "o@x" }] });
});

describe("Collaborators", () => {
  it("lists the owner and collaborators", () => {
    renderPanel();
    const list = screen.getAllByRole("list")[0];
    expect(within(list).getByText("[OWNER]")).toBeTruthy();
    expect(within(list).getByText("Owner")).toBeTruthy();
    expect(within(list).getByText("[MEMBER]")).toBeTruthy();
  });

  it("non-owners see no search and no Remove", () => {
    renderPanel(opportunity({ can_manage_collaborators: false }));
    expect(screen.queryByLabelText("Add collaborator")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });

  it("the owner searches people and adds one with the row version", async () => {
    const after = opportunity({
      collaborators: [MEMBER, { id: CANDIDATE.id, name: CANDIDATE.name }],
      row_version: 3,
    });
    changeCollaborator.mockResolvedValue({ kind: "ok", opportunity: after });
    const { user } = renderPanel();

    await user.type(screen.getByLabelText("Add collaborator"), "cand");
    const add = await screen.findByRole("button", { name: "Add [CANDIDATE]" });
    // The owner (already on it) is not offered.
    expect(screen.queryByRole("button", { name: "Add [OWNER]" })).toBeNull();
    expect(searchUsers).toHaveBeenLastCalledWith("cand");
    await user.click(add);

    expect(changeCollaborator).toHaveBeenCalledWith({
      opportunityId: after.id,
      userId: CANDIDATE.id,
      add: true,
      rowVersion: 2,
    });
    expect(await screen.findByRole("button", { name: "Remove [CANDIDATE]" })).toBeTruthy();
    expect((screen.getByLabelText("Add collaborator") as HTMLInputElement).value).toBe("");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("the owner removes a collaborator", async () => {
    changeCollaborator.mockResolvedValue({
      kind: "ok",
      opportunity: opportunity({ collaborators: [], row_version: 3 }),
    });
    const { user } = renderPanel();
    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));
    expect(changeCollaborator).toHaveBeenCalledWith(
      expect.objectContaining({ userId: MEMBER.id, add: false, rowVersion: 2 }),
    );
    expect(await screen.findByText("No collaborators yet.")).toBeTruthy();
    // The workspace header lists collaborators too.
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("412: says who changed it, locks changes, and Reload brings the current state", async () => {
    changeCollaborator.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    loadOpportunity.mockResolvedValue({
      kind: "ok",
      opportunity: opportunity({ collaborators: [], row_version: 5 }),
    });
    const { user } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));

    expect(await screen.findByText("Changed by [OTHER] since you opened it.")).toBeTruthy();
    const reload = screen.getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));
    expect(changeCollaborator).toHaveBeenCalledTimes(1); // locked: nothing overwritten

    await user.click(reload);
    expect(await screen.findByText("No collaborators yet.")).toBeTruthy();
    expect(screen.queryByText(/Changed by/, { selector: "p" })).toBeNull();
    expect(loadOpportunity).toHaveBeenCalledWith(opportunity().id);
  });

  it("shows the API's reason for a bad member (422) and access problems", async () => {
    changeCollaborator.mockResolvedValueOnce({
      kind: "invalid",
      detail: "Only users who hold a role can be collaborators.",
    });
    const { user } = renderPanel();
    await user.type(screen.getByLabelText("Add collaborator"), "cand");
    await user.click(await screen.findByRole("button", { name: "Add [CANDIDATE]" }));
    expect(
      await screen.findByText("Only users who hold a role can be collaborators."),
    ).toBeTruthy();

    changeCollaborator.mockResolvedValueOnce({ kind: "not-found" });
    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));
    expect(await screen.findByText("You don't have access to this Opportunity")).toBeTruthy();
  });

  it.each([
    ["412", { kind: "stale", changedBy: "[OTHER]" }, "Changed by [OTHER] since you opened it."],
    [
      "422",
      { kind: "invalid", detail: "Only users who hold a role can be collaborators." },
      "Only users who hold a role can be collaborators.",
    ],
    ["error", { kind: "error" }, "The change could not be saved. Try again."],
  ])("no workspace refresh after %s", async (_label, result, message) => {
    changeCollaborator.mockResolvedValueOnce(result);
    const { user } = renderPanel();
    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));
    expect(await screen.findByText(message, { selector: "p" })).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("never shows or adds the previous query's people while a new search is pending", async () => {
    const { user } = renderPanel();
    const input = screen.getByLabelText("Add collaborator");
    await user.type(input, "cand");
    expect(await screen.findByRole("button", { name: "Add [CANDIDATE]" })).toBeTruthy();
    searchUsers.mockReturnValue(new Promise(() => {})); // the next search never answers
    await user.type(input, "x");
    expect(screen.queryByRole("button", { name: "Add [CANDIDATE]" })).toBeNull();
    await user.clear(input);
    expect(screen.queryByRole("button", { name: "Add [CANDIDATE]" })).toBeNull();
    expect(changeCollaborator).not.toHaveBeenCalled();
  });

  it("a search error goes away when the query is cleared or changed", async () => {
    searchUsers.mockResolvedValue({ kind: "error" });
    const { user } = renderPanel();
    const input = screen.getByLabelText("Add collaborator");
    await user.type(input, "cand");
    expect(await screen.findByText("People search is not available right now.")).toBeTruthy();
    await user.clear(input);
    expect(screen.queryByText("People search is not available right now.")).toBeNull();
    searchUsers.mockReturnValue(new Promise(() => {}));
    await user.type(input, "ca");
    expect(screen.queryByText("People search is not available right now.")).toBeNull();
  });

  it("does not search for a single character", async () => {
    const { user } = renderPanel();
    await user.type(screen.getByLabelText("Add collaborator"), "c");
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(searchUsers).not.toHaveBeenCalled();
  });

  it("has no WCAG 2.1 AA violations, with results and with a stale notice", async () => {
    changeCollaborator.mockResolvedValue({ kind: "stale", changedBy: null });
    const { user, container } = renderPanel();
    await user.type(screen.getByLabelText("Add collaborator"), "cand");
    await screen.findByRole("button", { name: "Add [CANDIDATE]" });
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Remove [MEMBER]" }));
    expect(await screen.findByText("Changed by someone else since you opened it.")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
