import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Card, CardContent, CardHeader, CardTitle } from "./card";

describe("Card", () => {
  it("is a 12px surface with a 1px border and the card shadow", () => {
    render(
      <Card data-testid="card">
        <CardHeader data-testid="header">
          <CardTitle>Blockers</CardTitle>
        </CardHeader>
        <CardContent>Body</CardContent>
      </Card>,
    );
    const cls = screen.getByTestId("card").className;
    expect(cls).toContain("bg-surface");
    expect(cls).toContain("border border-border");
    expect(cls).toContain("rounded-xl");
    expect(cls).toContain("shadow-card");
    const header = screen.getByTestId("header").className;
    expect(header).toContain("px-5");
    expect(header).toContain("py-[18px]");
  });

  it("keeps the type class when a caller passes a colour", () => {
    render(<CardTitle className="text-foreground">T</CardTitle>);
    const cls = screen.getByText("T").className;
    expect(cls).toContain("text-foreground");
    expect(cls).toContain("text-section");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <Card>
        <CardHeader>
          <CardTitle>Blockers</CardTitle>
        </CardHeader>
        <CardContent>Body</CardContent>
      </Card>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
