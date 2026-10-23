import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatusPill as CatalogueStatusPill } from "@/components/admin/catalogue-table";
import { EvalStatusPill } from "@/components/admin/evals-view";
import { CoversChip, VersionPill } from "@/components/opportunities/estimate-grid";
import { GapStatusPill, QuestionPill } from "@/components/opportunities/gap-inspector";
import { axeViolations } from "@/test/axe";

import { Chip } from "./chip";

vi.mock("server-only", () => ({}));
vi.mock("@/app/opportunities/actions", () => ({}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => {} }) }));

function toneOf(container: HTMLElement, selector: string): string | null {
  return container.querySelector(selector)?.getAttribute("data-tone") ?? null;
}

describe("migrated status pills carry the right Pill tone", () => {
  it.each([
    [{ status: "active", retired: false }, "resolved"],
    [{ status: "retired", retired: true }, "neutral"],
  ])("catalogue entry %j -> %s", async (entry, tone) => {
    const { container } = render(
      <CatalogueStatusPill entry={entry as Parameters<typeof CatalogueStatusPill>[0]["entry"]} />,
    );
    expect(toneOf(container, "[data-entry-status]")).toBe(tone);
    expect(container.querySelector('[data-slot="pill"] svg')).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["pass", "resolved"],
    ["fail", "blocker"],
    ["not_measured", "neutral"],
  ] as const)("eval %s -> %s", (status, tone) => {
    const { container } = render(<EvalStatusPill status={status} />);
    expect(toneOf(container, "[data-eval-status]")).toBe(tone);
  });

  it.each([
    ["drafted", "neutral"],
    ["approved", "resolved"],
    ["sent", "neutral"],
    ["unanswered", "gap"],
    ["answered", "resolved"],
  ] as const)("question %s -> %s", (status, tone) => {
    const { container } = render(<QuestionPill status={status} />);
    expect(toneOf(container, "[data-question-status]")).toBe(tone);
  });

  it.each([
    ["open", "gap"],
    ["answered", "resolved"],
    ["converted", "neutral"],
    ["dismissed", "neutral"],
  ] as const)("gap %s -> %s", (status, tone) => {
    const { container } = render(<GapStatusPill status={status} />);
    expect(toneOf(container, "[data-gap-status]")).toBe(tone);
  });
});

describe("migrated neutral pills and chips", () => {
  it("VersionPill is a neutral Pill", () => {
    const { container } = render(
      <VersionPill version={{ status: "draft", version: 2, source: "manual", source_run: null } as never} />,
    );
    expect(toneOf(container, '[data-slot="pill"]')).toBe("neutral");
  });

  it("CoversChip and Chip render the chip look", async () => {
    const { container } = render(
      <div>
        <CoversChip count={3} />
        <Chip>S2</Chip>
      </div>,
    );
    const chips = container.querySelectorAll('[data-slot="chip"]');
    expect(chips).toHaveLength(2);
    for (const chip of chips) {
      expect(chip.className).toContain("border-border-strong");
      expect(chip.className).toContain("text-primary-text");
    }
    expect(await axeViolations(container)).toEqual([]);
  });
});
