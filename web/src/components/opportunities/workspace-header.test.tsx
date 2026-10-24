import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  updateOpportunity: vi.fn(),
  loadOpportunity: vi.fn(),
  submitEstimateVersion: vi.fn(),
}));

import { ShellProviders } from "../shell/shell-context";
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
  can_add_sources: false,
};

const TODAY = "2026-10-21";

function renderHeader(overrides: Partial<Opportunity> = {}, today = TODAY) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <WorkspaceHeader opportunity={{ ...OPPORTUNITY, ...overrides }} today={today} />
    </ShellProviders>,
  );
}

describe("WorkspaceHeader", () => {
  it("shows breadcrumb, title with pill, chips and the date with a countdown", async () => {
    const { container } = renderHeader();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    const all = within(crumbs).getByRole("link", { name: "Opportunities" });
    expect(all.getAttribute("href")).toBe("/opportunities");
    const current = crumbs.querySelector('[aria-current="page"]');
    expect(current?.textContent).toBe("[TITLE]");
    expect(current?.querySelector("a")).toBeNull();

    const title = screen.getByRole("heading", { level: 1, name: "[TITLE]" });
    expect(title.className).toContain("text-title");
    expect(title.parentElement?.textContent).toContain("Gaps open");

    expect(screen.getByText("Owner:")).toBeTruthy();
    expect(screen.getByText("[OWNER]")).toBeTruthy();
    expect(screen.getByText("[MEMBER 1]")).toBeTruthy();
    expect(screen.getByText("[MEMBER 2]")).toBeTruthy();
    expect(screen.getAllByText("Collaborator:")).toHaveLength(2);
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(screen.getByText("11 days left")).toBeTruthy();
    expect(container.querySelector(".lucide-clock")?.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector(".lucide-calendar")?.getAttribute("aria-hidden")).toBe("true");
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["2026-10-22", "Due tomorrow", ".lucide-clock"],
    ["2026-10-21", "Due today", ".lucide-clock"],
    ["2026-10-18", "3 days overdue", ".lucide-triangle-alert"],
  ])("countdown for %s reads %s with an icon", (date, text, icon) => {
    renderHeader({ target_proposal_date: date });
    const label = screen.getByText(text);
    expect(label.querySelector(icon)).toBeTruthy();
    expect(label.className.includes("text-blocker")).toBe(text.endsWith("overdue"));
  });

  it("says so when there are no collaborators", () => {
    renderHeader({ collaborators: [] });
    expect(screen.getByText("No collaborators")).toBeTruthy();
    expect(screen.getByText("[OWNER]")).toBeTruthy();
  });

  it("non-owners (can_edit false) get no edit buttons, only the right-pane toggle", () => {
    renderHeader();
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Right pane",
    ]);
  });

  it("puts the 28px right-pane toggle on the breadcrumb row inside the surface band", () => {
    renderHeader();
    const toggle = screen.getByRole("button", { name: "Right pane" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.className).toContain("size-7");
    const row = toggle.parentElement!;
    expect(within(row).getByRole("navigation", { name: "Breadcrumb" })).toBeTruthy();
    const band = row.closest("header")!;
    expect(band.className).toContain("bg-surface");
    expect(band.className).toContain("px-page");
  });

  it("the owner (can_edit) edits the title and date inline; breadcrumb, chips and countdown stay", async () => {
    const { container } = renderHeader({ can_edit: true });
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Right pane",
      "Edit title",
      "Edit target proposal date",
    ]);
    expect(screen.getByText("Gaps open")).toBeTruthy();
    expect(screen.getByText("[OWNER]")).toBeTruthy();
    expect(screen.getByText("[MEMBER 1]")).toBeTruthy();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(screen.getByText("11 days left")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
