import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  updateOpportunity: vi.fn(),
  loadOpportunity: vi.fn(),
}));

import { WorkspaceHeader } from "./workspace-header";

const OPPORTUNITY: Opportunity = {
  id: "00000000-0000-7000-8000-000000000001",
  title: "[TITLE]",
  customer_name: "[CUSTOMER]",
  status: "gaps_open",
  owner: { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" },
  target_proposal_date: "2026-11-01",
  created_at: "2026-10-04T10:00:00Z",
  products: ["AutoStore"],
  industry: "Retail",
  collaborators: [
    { id: "00000000-0000-7000-8000-0000000000b2", name: "[MEMBER 1]" },
    { id: "00000000-0000-7000-8000-0000000000b3", name: "[MEMBER 2]" },
  ],
  row_version: 2,
  last_changed_by: null,
  can_manage_collaborators: false,
  can_edit: false,
};

describe("WorkspaceHeader", () => {
  it("shows the title, then status, owner, collaborators and target proposal date", async () => {
    const { container } = render(<WorkspaceHeader opportunity={OPPORTUNITY} />);
    const title = screen.getByRole("heading", { level: 1, name: "[TITLE]" });
    expect(title.className).toContain("text-title");
    expect(screen.getByText("Gaps open")).toBeTruthy();
    expect(screen.getByText("[OWNER]")).toBeTruthy();
    expect(screen.getByText("[MEMBER 1], [MEMBER 2]")).toBeTruthy();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(container.querySelector(".lucide-calendar")?.getAttribute("aria-hidden")).toBe("true");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says so when there are no collaborators", () => {
    render(<WorkspaceHeader opportunity={{ ...OPPORTUNITY, collaborators: [] }} />);
    expect(screen.getByText("No collaborators")).toBeTruthy();
  });

  it("non-owners (can_edit false) get plain text and no buttons", () => {
    render(<WorkspaceHeader opportunity={OPPORTUNITY} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("the owner (can_edit) edits the title and date inline; the meta row stays", async () => {
    const { container } = render(
      <WorkspaceHeader opportunity={{ ...OPPORTUNITY, can_edit: true }} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Edit title",
      "Edit target proposal date",
    ]);
    expect(screen.getByText("Gaps open")).toBeTruthy();
    expect(screen.getByText("[OWNER]")).toBeTruthy();
    expect(screen.getByText("[MEMBER 1], [MEMBER 2]")).toBeTruthy();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
