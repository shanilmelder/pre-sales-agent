import { describe, expect, it } from "vitest";

import { NAV_ITEMS, landingFor, visibleNav, type Role } from "./navigation";
import { canCreateOpportunity, shortcutsFor } from "./shortcuts";

describe("NAV_ITEMS", () => {
  it("lists the sidebar items in order, each with an icon", () => {
    expect(NAV_ITEMS.map((item) => item.label)).toEqual([
      "Inbox",
      "My Opportunities",
      "All Opportunities",
      "Knowledge",
      "Reports",
      "Admin",
    ]);
    for (const item of NAV_ITEMS) expect(item.icon).toBeTruthy();
  });

  it("gives g-keys i, m, a, k and r", () => {
    expect(NAV_ITEMS.flatMap((item) => (item.gKey ? [item.gKey] : []))).toEqual([
      "i",
      "m",
      "a",
      "k",
      "r",
    ]);
  });
});

describe("visibleNav", () => {
  it("hides Admin from users without identity.user.list", () => {
    const labels = visibleNav(["identity.user.search", "opportunities.opportunity.create"]).map(
      (i) => i.label,
    );
    expect(labels).not.toContain("Admin");
    expect(labels).toHaveLength(5);
    expect(visibleNav([]).map((i) => i.label)).not.toContain("Admin");
  });

  it("shows Admin to holders of identity.user.list, whatever their roles", () => {
    expect(visibleNav(["identity.user.list"]).map((i) => i.label)).toContain("Admin");
  });
});

describe("landingFor", () => {
  it.each<[Role[], string]>([
    [["presales_engineer"], "/my-opportunities"],
    [["pm_reviewer", "presales_engineer"], "/my-opportunities"],
    [["pm_reviewer"], "/inbox"],
    [["platform_administrator"], "/inbox"],
    [["sales_representative", "commercial"], "/inbox"],
  ])("%j lands on %s", (roles, href) => {
    expect(landingFor(roles)).toBe(href);
  });
});

describe("canCreateOpportunity and shortcutsFor", () => {
  it("follow the opportunities.opportunity.create permission, not the role", () => {
    const create = ["opportunities.opportunity.create"];
    expect(canCreateOpportunity(create)).toBe(true);
    expect(canCreateOpportunity(["identity.user.search"])).toBe(false);
    expect(shortcutsFor(create).some((s) => s.id === "create-opportunity")).toBe(true);
    expect(shortcutsFor([]).some((s) => s.id === "create-opportunity")).toBe(false);
  });
});
