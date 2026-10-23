import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { PageHeader } from "./page-header";

describe("PageHeader", () => {
  it("renders the title, the subtitle and no action by default", async () => {
    const { container } = render(<PageHeader title="Reports" subtitle="Pipeline reports." />);
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeTruthy();
    expect(screen.getByText("Pipeline reports.").className).toContain("text-muted-foreground");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("renders the action slot", async () => {
    const { container } = render(
      <PageHeader title="Opportunities" subtitle="All." action={<a href="/new">New</a>} />,
    );
    expect(screen.getByRole("link", { name: "New" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
