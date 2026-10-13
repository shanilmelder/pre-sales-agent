import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdminUser } from "@/lib/admin";
import { axeViolations } from "@/test/axe";

import { ShellProviders } from "../shell/shell-context";
import { UsersTable } from "./users-table";

function user(n: number, roles: AdminUser["roles"] = []): AdminUser {
  return {
    id: `00000000-0000-7000-8000-00000000000${n}`,
    name: `[USER ${n}]`,
    email: `user${n}@example.invalid`,
    roles,
    row_version: 1,
  };
}

const USERS = [
  user(1, ["pm_reviewer", "commercial"]),
  user(2),
  user(3, ["platform_administrator"]),
];

function renderTable(
  users: AdminUser[] = USERS,
  singleKeyShortcuts = true,
  selectedId: string | null = null,
) {
  const onOpen = vi.fn();
  const utils = render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <UsersTable users={users} selectedId={selectedId} onOpen={onOpen} />
      <button type="button">After</button>
    </ShellProviders>,
  );
  return { onOpen, user: userEvent.setup(), ...utils };
}

const row = (name: string) => screen.getByRole("button", { name });

describe("UsersTable", () => {
  it("lists each user with email and role labels", () => {
    renderTable();
    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3
    expect(screen.getByText("user1@example.invalid")).toBeTruthy();
    expect(screen.getByText("PM reviewer, Commercial")).toBeTruthy();
    expect(screen.getByText("No roles")).toBeTruthy();
    expect(screen.getByText("Platform administrator")).toBeTruthy();
  });

  it("j/k and the arrow keys move between rows; Enter opens the inspector", async () => {
    const { user, onOpen } = renderTable();
    await user.tab();
    expect(document.activeElement).toBe(row("[USER 1]"));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[USER 2]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[USER 3]"));
    await user.keyboard("j"); // stays on the last row
    expect(document.activeElement).toBe(row("[USER 3]"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("[USER 2]"));
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(USERS[1], true);
  });

  it("the list is a single Tab stop that remembers the focused row", async () => {
    const { user } = renderTable();
    const tabbable = () =>
      screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabbable().map((b) => b.textContent)).toEqual(["[USER 1]", "After"]);
    await user.tab();
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "After" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(row("[USER 1]"));
    await user.keyboard("j");
    await user.tab();
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(row("[USER 2]"));
  });

  it("the selected row is the Tab stop", async () => {
    const { user } = renderTable(USERS, true, USERS[2].id);
    await user.tab();
    expect(document.activeElement).toBe(row("[USER 3]"));
    expect(row("[USER 3]").getAttribute("aria-current")).toBe("true");
  });

  it("j/k are off with single-key shortcuts off; arrows still work", async () => {
    const { user } = renderTable(USERS, false);
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[USER 1]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[USER 2]"));
  });

  it("clicking a row opens it", async () => {
    const { user, onOpen } = renderTable();
    await user.click(row("[USER 3]"));
    expect(onOpen).toHaveBeenCalledWith(USERS[2], false);
  });

  it("shows a plain empty state", () => {
    renderTable([]);
    expect(screen.getByText("No users yet.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("has no WCAG 2.1 AA violations", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
  });
});
