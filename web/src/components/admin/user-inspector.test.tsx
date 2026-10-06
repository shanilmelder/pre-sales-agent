import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { auth0UsersUrl, type AdminUser } from "@/lib/admin";
import { axeViolations } from "@/test/axe";

import { UserInspector } from "./user-inspector";

const USER: AdminUser = {
  id: "00000000-0000-7000-8000-000000000001",
  name: "[TARGET]",
  email: "target@example.invalid",
  roles: ["commercial", "pm_reviewer"],
  row_version: 3,
};
const MANAGE_URL = "https://manage.auth0.com/dashboard/eu/psa/users";

describe("UserInspector", () => {
  it("shows the user's roles read-only, the as-of note and the Auth0 link", async () => {
    const { container } = render(<UserInspector user={USER} manageRolesUrl={MANAGE_URL} />);
    expect(screen.getByRole("heading", { name: "[TARGET]" })).toBeTruthy();
    const list = screen.getByRole("list", { name: "Roles as of last sign-in" });
    expect(list.textContent).toBe("CommercialPM reviewer");
    expect(screen.queryAllByRole("switch")).toHaveLength(0);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(
      screen.getByText(/managed in Auth0 and shown as of each person's last sign-in/),
    ).toBeTruthy();
    const link = screen.getByRole("link", { name: /Manage roles in Auth0/ });
    expect(link.getAttribute("href")).toBe(MANAGE_URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a user with no roles says so", () => {
    render(<UserInspector user={{ ...USER, roles: [] }} manageRolesUrl={MANAGE_URL} />);
    expect(screen.getByText("No roles")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("a focus request moves focus to the heading", () => {
    render(<UserInspector user={USER} manageRolesUrl={MANAGE_URL} focusRequest={1} />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "[TARGET]" }));
  });
});

describe("auth0UsersUrl", () => {
  it.each([
    ["psa.eu.auth0.com", "https://manage.auth0.com/dashboard/eu/psa/users"],
    ["https://psa-dev.eu.auth0.com/", "https://manage.auth0.com/dashboard/eu/psa-dev/users"],
    ["psa.auth0.com", "https://manage.auth0.com/dashboard/us/psa/users"],
    ["login.example.com", "https://manage.auth0.com/"],
    [undefined, "https://manage.auth0.com/"],
    ["", "https://manage.auth0.com/"],
  ])("%s -> %s", (domain, url) => {
    expect(auth0UsersUrl(domain)).toBe(url);
  });
});
