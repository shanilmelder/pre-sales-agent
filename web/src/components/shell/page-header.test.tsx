import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { PageContent, PageHeader } from "./page-header";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders, useShell } from "./shell-context";

function PaneState() {
  const { rightPaneOpen } = useShell();
  return <p data-testid="pane-state">{rightPaneOpen ? "open" : "closed"}</p>;
}

function renderHeader(props: Parameters<typeof PageHeader>[0]) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <main>
        <PageHeader {...props} />
        <PageContent>
          <p>[BODY]</p>
        </PageContent>
      </main>
      <PaneState />
    </ShellProviders>,
  );
}

describe("PageHeader", () => {
  it("renders the band: h1, subtitle and the 34px pane toggle, with no axe violations", async () => {
    const { container } = renderHeader({ title: "Knowledge", subtitle: "[SUBTITLE]" });
    const header = screen.getByTestId("page-header");
    expect(header.className).toContain("bg-surface");
    expect(header.className).toContain("border-b");
    expect(header.className).toContain("px-page");
    expect(header.className).toContain("pt-7");
    expect(header.className).toContain("pb-5");
    expect(within(header).getByRole("heading", { level: 1, name: "Knowledge" }).className).toContain(
      "text-title",
    );
    expect(within(header).getByText("[SUBTITLE]").className).toContain("text-text-secondary");
    const toggle = within(header).getByRole("button", { name: "Right pane" });
    expect(toggle.id).toBe(RIGHT_PANE_TOGGLE_ID);
    expect(toggle.className).toContain("size-[34px]");
    expect(toggle.className).toContain("border-border");
    expect(toggle.getAttribute("title")).toBe("Show or hide the right pane (])");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("puts the primary action before the pane toggle", () => {
    renderHeader({ title: "All Opportunities", action: <a href="/new">New Opportunity</a> });
    const header = screen.getByTestId("page-header");
    const action = within(header).getByRole("link", { name: "New Opportunity" });
    const toggle = within(header).getByRole("button", { name: "Right pane" });
    expect(action.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("leaves the subtitle and action out when not given", () => {
    renderHeader({ title: "Reports" });
    const header = screen.getByTestId("page-header");
    expect(within(header).getAllByRole("button")).toHaveLength(1);
    expect(within(header).getByRole("heading", { level: 1 }).nextElementSibling).toBeNull();
  });

  it("the toggle opens and closes the pane, reflected in aria-pressed", async () => {
    const user = userEvent.setup();
    renderHeader({ title: "Inbox" });
    const toggle = screen.getByRole("button", { name: "Right pane" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    await user.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("pane-state").textContent).toBe("open");
    await user.click(toggle);
    expect(screen.getByTestId("pane-state").textContent).toBe("closed");
  });

  it("PageContent pads 28/32/40 with sections 24px apart", () => {
    renderHeader({ title: "Settings" });
    const content = screen.getByTestId("page-content");
    for (const cls of ["px-page", "pt-7", "pb-10", "gap-6"]) expect(content.className).toContain(cls);
  });
});
