import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { NO_GAP_FILTERS, type Gap, type GapFilters } from "@/lib/gaps";
import { axeViolations } from "@/test/axe";

import { GapsFilters } from "./gaps-filters";

const ITEMS = [
  { category: "commercial" },
  { category: "data_volumes" },
  { category: "commercial" },
] as Pick<Gap, "category">[];

function Harness({ onChange }: { onChange?: (filters: GapFilters) => void }) {
  const [filters, setFilters] = useState<GapFilters>(NO_GAP_FILTERS);
  return (
    <GapsFilters
      items={ITEMS}
      filters={filters}
      onChange={(next) => {
        setFilters(next);
        onChange?.(next);
      }}
    />
  );
}

/** A filter's trigger, by its label (it may also show the picked value: "Impact: High"). */
const trigger = (label: string) =>
  screen.getByRole("button", { name: new RegExp(`^${label}(: .*)?$`) });

async function open(label: string) {
  fireEvent.click(trigger(label));
  return screen.findByRole("dialog", { name: `${label} filter` });
}

describe("GapsFilters", () => {
  it("shows the three dashed triggers", async () => {
    const { container } = render(<Harness />);
    const group = screen.getByRole("group", { name: "Filters" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Impact",
      "Area",
      "Question status",
    ]);
    expect(trigger("Impact").className).toContain("border-dashed");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("offers Any plus the options; Area lists only the categories present", async () => {
    render(<Harness />);
    let popover = await open("Impact");
    expect(within(popover).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(
      ["Any", "High", "Medium", "Low"],
    );
    expect((within(popover).getByRole("radio", { name: "Any" }) as HTMLInputElement).checked).toBe(
      true,
    );
    fireEvent.keyDown(popover, { key: "Escape" });

    popover = await open("Area");
    expect(within(popover).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(
      ["Any", "Data volumes", "Commercial"],
    );
    fireEvent.keyDown(popover, { key: "Escape" });

    popover = await open("Question status");
    expect(within(popover).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(
      ["Any", "Draft", "Approved", "Sent", "No answer", "Answered"],
    );
  });

  it("a pick reads 'Impact: High' on a solid trigger; Any clears it", async () => {
    const changes: GapFilters[] = [];
    render(<Harness onChange={(f) => changes.push(f)} />);
    const popover = await open("Impact");

    fireEvent.click(within(popover).getByRole("radio", { name: "High" }));
    expect(changes.at(-1)).toEqual({ ...NO_GAP_FILTERS, impact: "high" });
    expect(trigger("Impact").textContent).toBe("Impact: High");
    expect(trigger("Impact").className).toContain("border-solid");

    fireEvent.click(within(popover).getByRole("radio", { name: "Any" }));
    expect(changes.at(-1)).toEqual(NO_GAP_FILTERS);
    expect(trigger("Impact").textContent).toBe("Impact");
  });
});
