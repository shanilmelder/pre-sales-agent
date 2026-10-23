import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

import { EmptyTabCard } from "./empty-tab-card";

describe("EmptyTabCard", () => {
  it("shows a title, a sentence and a link button", async () => {
    const { container } = render(
      <EmptyTabCard title="No Gaps" body="Gaps appear." actionLabel="Open Requirements" href="/x/requirements" />,
    );
    expect(screen.getByText("No Gaps")).toBeTruthy();
    expect(screen.getByText("Gaps appear.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Requirements" }).getAttribute("href")).toBe("/x/requirements");
    expect(container.querySelector('[data-slot="card"]')).not.toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("runs onClick from a button", async () => {
    const onClick = vi.fn();
    render(<EmptyTabCard title="T" body="B" actionLabel="Choose files" onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Choose files" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders no button without an action", () => {
    render(<EmptyTabCard title="T" body="B" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
