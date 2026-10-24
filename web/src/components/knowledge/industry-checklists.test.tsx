import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { IndustryChecklists, NO_INDUSTRIES } from "./industry-checklists";

describe("IndustryChecklists", () => {
  it("lists each industry with its Checklists", async () => {
    const { container } = render(
      <IndustryChecklists
        industries={[
          { industry: "Healthcare", checklists: 1, names: ["HIPAA controls"] },
          { industry: "Retail", checklists: 2, names: ["PCI baseline", "Store rollout"] },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Industry Checklists" })).toBeTruthy();
    const items = within(screen.getByRole("list", { name: "Industry Checklists" })).getAllByRole(
      "listitem",
    );
    expect(items.map((i) => i.firstElementChild?.textContent)).toEqual(["Healthcare", "Retail"]);
    expect(items[1].textContent).toContain("PCI baseline, Store rollout");
    const link = within(items[1]).getByRole("link", { name: "2 Checklists for Retail" });
    expect(link.getAttribute("href")).toBe("/knowledge/checklists");
    expect(within(items[0]).getByRole("link").textContent).toBe("1 Checklist");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when there are none", () => {
    render(<IndustryChecklists industries={[]} />);
    expect(screen.getByText(NO_INDUSTRIES)).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
