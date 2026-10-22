import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Input } from "./input";
import { Select } from "./select";
import { Textarea } from "./textarea";

describe("Input, Textarea and Select", () => {
  it("use the surface-alt fill, border-strong outline and radius 8", () => {
    render(
      <div>
        <Input aria-label="Name" />
        <Textarea aria-label="Notes" />
        <Select aria-label="Role">
          <option value="a">Engineer</option>
        </Select>
      </div>,
    );
    for (const name of ["Name", "Notes", "Role"]) {
      const cls = screen.getByLabelText(name).className;
      expect(cls).toContain("bg-surface-alt");
      expect(cls).toContain("border-border-strong");
      expect(cls).toContain("rounded-md");
      expect(cls).toContain("text-body");
      expect(cls).not.toContain("dark:");
    }
    expect(screen.getByLabelText("Name").className).toContain("h-[38px]");
  });

  it("keeps native select behaviour", () => {
    render(
      <Select aria-label="Role" defaultValue="b">
        <option value="a">Engineer</option>
        <option value="b">QA</option>
      </Select>,
    );
    expect((screen.getByLabelText("Role") as HTMLSelectElement).value).toBe("b");
    expect(screen.getByRole("combobox", { name: "Role" })).toBeTruthy();
  });

  it("marks disabled fields", () => {
    render(<Input aria-label="Name" disabled />);
    const input = screen.getByLabelText("Name") as HTMLInputElement;
    expect(input.disabled).toBe(true);
    expect(input.className).toContain("disabled:opacity-40");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <Input aria-label="Name" />
        <Textarea aria-label="Notes" />
        <Select aria-label="Role">
          <option value="a">Engineer</option>
        </Select>
      </div>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
