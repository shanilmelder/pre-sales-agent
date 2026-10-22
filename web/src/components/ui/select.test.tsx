import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

import { Select } from "./select";

describe("Select", () => {
  it("is a native select with the control tokens", () => {
    render(
      <Select aria-label="Role">
        <option value="a">Engineer</option>
      </Select>,
    );
    const select = screen.getByRole("combobox", { name: "Role" });
    expect(select.tagName).toBe("SELECT");
    expect(select.className).toContain("bg-surface-alt");
    expect(select.className).toContain("border-border-strong");
  });

  it("changes value through the native option API and can be disabled", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Select aria-label="Role" onChange={onChange}>
        <option value="a">Engineer</option>
        <option value="b">QA</option>
      </Select>,
    );
    await userEvent.selectOptions(screen.getByLabelText("Role"), "b");
    expect(onChange).toHaveBeenCalledTimes(1);
    rerender(
      <Select aria-label="Role" disabled>
        <option value="a">Engineer</option>
      </Select>,
    );
    expect((screen.getByLabelText("Role") as HTMLSelectElement).disabled).toBe(true);
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <Select aria-label="Role">
        <option value="a">Engineer</option>
      </Select>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
