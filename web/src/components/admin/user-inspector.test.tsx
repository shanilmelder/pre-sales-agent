import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUser } from "@/app/admin/users/actions";
import { axeViolations } from "@/test/axe";

const changeRole = vi.hoisted(() => vi.fn());
const loadUser = vi.hoisted(() => vi.fn());
vi.mock("@/app/admin/users/actions", () => ({ changeRole, loadUser }));

import { LiveRegionProvider } from "../shell/live-region";
import { UserInspector } from "./user-inspector";

const USER: AdminUser = {
  id: "00000000-0000-7000-8000-000000000001",
  name: "[TARGET]",
  email: "target@example.invalid",
  roles: ["commercial"],
  row_version: 3,
  last_changed_by: null,
};

function renderInspector(user: AdminUser = USER) {
  const onChange = vi.fn();
  const utils = render(
    <LiveRegionProvider>
      <UserInspector user={user} onChange={onChange} />
    </LiveRegionProvider>,
  );
  return { onChange, user: userEvent.setup(), ...utils };
}

const roleSwitch = (name: string) => screen.getByRole("switch", { name }) as HTMLInputElement;

beforeEach(() => {
  changeRole.mockReset();
  loadUser.mockReset();
});

describe("UserInspector", () => {
  it("shows the user and nine labelled role switches", () => {
    renderInspector();
    expect(screen.getByRole("heading", { name: "[TARGET]" })).toBeTruthy();
    expect(screen.getAllByRole("switch")).toHaveLength(9);
    expect(roleSwitch("Commercial").checked).toBe(true);
    expect(roleSwitch("PM reviewer").checked).toBe(false);
    expect(roleSwitch("Platform administrator").checked).toBe(false);
  });

  it("saves a toggle with the row version, reports the stored user and announces it", async () => {
    const saved: AdminUser = { ...USER, roles: ["commercial", "pm_reviewer"], row_version: 4 };
    changeRole.mockResolvedValue({ kind: "ok", user: saved });
    const { user, onChange } = renderInspector();

    await user.click(roleSwitch("PM reviewer"));

    expect(changeRole).toHaveBeenCalledWith({
      userId: USER.id,
      role: "pm_reviewer",
      assigned: true,
      rowVersion: 3,
    });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(saved));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("PM reviewer assigned to [TARGET]"),
    );
  });

  it("removing a role sends assigned: false", async () => {
    changeRole.mockResolvedValue({ kind: "ok", user: { ...USER, roles: [], row_version: 4 } });
    const { user } = renderInspector();
    await user.click(roleSwitch("Commercial"));
    expect(changeRole).toHaveBeenCalledWith(
      expect.objectContaining({ role: "commercial", assigned: false }),
    );
  });

  it("on 412 shows who changed the user, disables the switches and reloads on request", async () => {
    changeRole.mockResolvedValue({ kind: "stale", changedBy: "[OTHER ADMIN]" });
    const fresh: AdminUser = { ...USER, roles: ["commercial", "pm_reviewer"], row_version: 5 };
    loadUser.mockResolvedValue({ kind: "ok", user: fresh });
    const { user, onChange } = renderInspector();

    await user.click(roleSwitch("Security reviewer"));

    expect(
      (await screen.findAllByText("Changed by [OTHER ADMIN] since you opened it.")).length,
    ).toBeGreaterThan(0);
    expect(onChange).not.toHaveBeenCalled();
    expect(roleSwitch("Security reviewer").checked).toBe(false);
    // Locked but still focusable; focus moves to Reload.
    expect(roleSwitch("Security reviewer").getAttribute("aria-disabled")).toBe("true");
    expect(roleSwitch("Security reviewer").disabled).toBe(false);
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Reload" })),
    );
    // Input is ignored while locked.
    await user.click(roleSwitch("Commercial"));
    expect(changeRole).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(loadUser).toHaveBeenCalledWith(USER.id);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(fresh));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reload" })).toBeNull());
    expect(screen.getByRole("region").textContent).not.toMatch(/since you opened it/);
  });

  it("on 412 with nobody recorded names another administrator", async () => {
    changeRole.mockResolvedValue({ kind: "stale", changedBy: null });
    const { user } = renderInspector();
    await user.click(roleSwitch("Commercial"));
    expect(
      (await screen.findAllByText("Changed by another administrator since you opened it.")).length,
    ).toBeGreaterThan(0);
  });

  it("on 409 shows the detail from the API and keeps the switch as stored", async () => {
    const detail = "At least one platform administrator is required";
    changeRole.mockResolvedValue({ kind: "conflict", detail });
    const { user, onChange } = renderInspector({ ...USER, roles: ["platform_administrator"] });

    await user.click(roleSwitch("Platform administrator"));

    expect((await screen.findAllByText(detail)).length).toBeGreaterThan(0);
    expect(roleSwitch("Platform administrator").checked).toBe(true);
    await waitFor(() =>
      expect(roleSwitch("Platform administrator").getAttribute("aria-disabled")).toBeNull(),
    );
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps keyboard focus on the switch while the save is pending", async () => {
    let resolve: (value: unknown) => void = () => {};
    changeRole.mockReturnValue(new Promise((r) => (resolve = r)));
    const { user } = renderInspector();
    roleSwitch("PM reviewer").focus();
    await user.keyboard(" ");
    await waitFor(() =>
      expect(roleSwitch("PM reviewer").getAttribute("aria-disabled")).toBe("true"),
    );
    expect(document.activeElement).toBe(roleSwitch("PM reviewer"));
    await user.keyboard(" "); // ignored while pending
    expect(changeRole).toHaveBeenCalledTimes(1);
    resolve({ kind: "ok", user: { ...USER, roles: ["commercial", "pm_reviewer"], row_version: 4 } });
    await waitFor(() =>
      expect(roleSwitch("PM reviewer").getAttribute("aria-disabled")).toBeNull(),
    );
    expect(document.activeElement).toBe(roleSwitch("PM reviewer"));
  });

  it.each([
    ["not-found", "This user no longer exists."],
    ["forbidden", "You don't have access to change roles."],
  ])("a %s save shows its message", async (kind, message) => {
    changeRole.mockResolvedValue({ kind });
    const { user } = renderInspector();
    await user.click(roleSwitch("Commercial"));
    expect((await screen.findAllByText(message)).length).toBeGreaterThan(0);
  });

  it.each([
    ["not-found", "This user no longer exists."],
    ["forbidden", "You don't have access to change roles."],
  ])("a %s reload after 412 shows its message, not a generic failure", async (kind, message) => {
    changeRole.mockResolvedValue({ kind: "stale", changedBy: null });
    loadUser.mockResolvedValue({ kind });
    const { user, onChange } = renderInspector();
    await user.click(roleSwitch("Commercial"));
    await user.click(await screen.findByRole("button", { name: "Reload" }));
    expect((await screen.findAllByText(message)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
    expect(screen.queryByText(/could not be reloaded/)).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "[TARGET]" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("focusRequest moves focus to the heading", () => {
    render(
      <LiveRegionProvider>
        <UserInspector user={USER} onChange={vi.fn()} focusRequest={1} />
      </LiveRegionProvider>,
    );
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "[TARGET]" }));
  });

  it("a failed action shows a retry message", async () => {
    changeRole.mockRejectedValue(new Error("network"));
    const { user } = renderInspector();
    await user.click(roleSwitch("Commercial"));
    expect((await screen.findAllByText(/could not be saved/)).length).toBeGreaterThan(0);
  });

  it("has no WCAG 2.1 AA violations, including the 412 notice", async () => {
    changeRole.mockResolvedValue({ kind: "stale", changedBy: null });
    const { container, user } = renderInspector();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(roleSwitch("Commercial"));
    await screen.findByRole("button", { name: "Reload" });
    expect(await axeViolations(container)).toEqual([]);
  });
});
