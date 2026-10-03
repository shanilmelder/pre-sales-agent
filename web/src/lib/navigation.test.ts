import { describe, expect, it } from "vitest";

import { NAV_ITEMS, landingFor, visibleNav, type Role } from "./navigation";

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
  it("hides Admin from non-admins", () => {
    const labels = visibleNav(["presales_engineer", "pm_reviewer"]).map((i) => i.label);
    expect(labels).not.toContain("Admin");
    expect(labels).toHaveLength(5);
  });

  it("shows Admin to platform administrators", () => {
    expect(visibleNav(["platform_administrator"]).map((i) => i.label)).toContain("Admin");
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
