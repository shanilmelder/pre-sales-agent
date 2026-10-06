import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AdminUser } from "@/lib/admin";

import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders } from "../shell/shell-context";
import { UsersAdmin } from "./users-admin";

function user(n: number, roles: AdminUser["roles"] = [], rowVersion = 1): AdminUser {
  return {
    id: `00000000-0000-7000-8000-00000000000${n}`,
    name: `[USER ${n}]`,
    email: `user${n}@example.invalid`,
    roles,
    row_version: rowVersion,
  };
}

function ui(users: AdminUser[]) {
  return (
    <ShellProviders singleKeyShortcuts>
      <button type="button" id={RIGHT_PANE_TOGGLE_ID}>
        Toggle
      </button>
      <UsersAdmin initialUsers={users} manageRolesUrl="https://manage.auth0.com/" />
      <RightPane />
    </ShellProviders>
  );
}

const USERS = [user(1), user(2, ["commercial"])];
const pane = () => screen.queryByRole("complementary", { name: "Details" });

describe("UsersAdmin", () => {
  it("Enter opens the inspector and moves focus into it; closing returns focus to the row", async () => {
    const u = userEvent.setup();
    render(ui(USERS));
    await u.tab(); // Toggle
    await u.tab(); // first row
    await u.keyboard("j{Enter}");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(pane()!).getByRole("heading", { name: "[USER 2]" }),
      ),
    );
    await u.click(within(pane()!).getByRole("button", { name: "Close right pane" }));
    expect(pane()).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "[USER 2]" })),
    );
  });

  it("a mouse open leaves focus on the row", async () => {
    const u = userEvent.setup();
    render(ui(USERS));
    await u.click(screen.getByRole("button", { name: "[USER 1]" }));
    await waitFor(() => expect(pane()).not.toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "[USER 1]" }));
  });

  it("new server data for the same page replaces the rows", async () => {
    const { rerender } = render(ui(USERS));
    expect(screen.getByText("Commercial")).toBeTruthy();
    act(() => rerender(ui([user(1), user(2, ["pm_reviewer"], 2)])));
    expect(screen.getByText("PM reviewer")).toBeTruthy();
    expect(screen.queryByText("Commercial")).toBeNull();
  });
});
