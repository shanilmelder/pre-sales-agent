import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./table";

function Example() {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Line</TableHead>
          <TableHead>Effort</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>Integration</TableCell>
          <TableCell>12.5</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

describe("Table", () => {
  it("has a sticky header, tabular figures and h-row body rows", () => {
    render(<Example />);
    expect(screen.getByRole("table").className).toContain("tabular-nums");
    expect(document.querySelector("thead")?.className).toContain("sticky");
    expect(document.querySelector("thead")?.className).toContain("bg-surface-alt");
    expect(document.querySelector("tbody tr")?.className).toContain("h-row");
    expect(screen.getByRole("columnheader", { name: "Line" })).toBeTruthy();
  });

  it("keeps the type class when a caller passes a colour", () => {
    render(
      <Table className="text-foreground">
        <TableBody />
      </Table>,
    );
    const cls = screen.getByRole("table").className;
    expect(cls).toContain("text-foreground");
    expect(cls).toContain("text-body");
  });

  it("has no axe violations", async () => {
    const { container } = render(<Example />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
