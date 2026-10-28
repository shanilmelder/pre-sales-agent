import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssumptionLineageResult, LineLineageResult } from "@/app/opportunities/data";
import { SKELETON_MIN_MS } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";
import {
  actualStep,
  assumptionLineage,
  LINEAGE_LINE,
  LINEAGE_OPP,
  lineContingency,
  lineLineage,
  PASSAGE_ID,
} from "@/test/lineage-fixtures";

const loadLineLineage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, lineId: string) => Promise<LineLineageResult>>(),
);
const loadAssumptionLineage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, assumptionId: string) => Promise<AssumptionLineageResult>>(),
);
const getPassage = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({
  loadLineLineage,
  loadAssumptionLineage,
  getPassage,
}));

import { AssumptionLineageSection, LineLineageSection } from "./lineage-section";

beforeEach(() => {
  loadLineLineage.mockReset();
  loadAssumptionLineage.mockReset();
  getPassage.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

const headings = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("h5")).map((h) => h.textContent);

describe("LineLineageSection", () => {
  it("shows a skeleton for at least 150 ms, then every section in order", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const { container } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />,
    );

    expect(container.querySelector("[data-lineage-loading]")).not.toBeNull();
    expect(screen.getByText("Loading lineage")).toBeTruthy();
    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(SKELETON_MIN_MS - 10);
    });
    expect(container.querySelector("[data-lineage-loading]")).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    await waitFor(() => expect(container.querySelector("[data-lineage-loading]")).toBeNull());
    expect(loadLineLineage).toHaveBeenCalledWith(LINEAGE_OPP, LINEAGE_LINE);
    expect(headings(container)).toEqual([
      "Requirements",
      "Findings",
      "Decisions",
      "Assumptions",
      "Edits",
      "Reviews",
    ]);
    // An empty section says so.
    const assumptions = container.querySelector("[data-lineage-section='assumptions']")!;
    expect(within(assumptions as HTMLElement).getByText("Nothing recorded.")).toBeTruthy();
  });

  it("strikes superseded items through and labels them, and they still open the cited version", async () => {
    const user = userEvent.setup();
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const { container } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />,
    );
    await screen.findByText("[FINDING TITLE]");
    const requirements = container.querySelector(
      "[data-lineage-section='requirements']",
    ) as HTMLElement;

    const chip = within(requirements).getByRole("button", { name: /R1 v1/ });
    expect(chip.querySelector("s")?.textContent).toBe("R1 v1");
    expect(chip.textContent).toContain("(superseded)");
    expect(chip.className).toContain("bg-primary-tint");
    expect(chip.className).toContain("rounded-[6px]");
    expect(chip.querySelector("svg")?.getAttribute("class")).toContain("size-[11px]");
    expect(chip.getAttribute("aria-pressed")).toBe("false");

    await user.click(chip);

    expect(chip.getAttribute("aria-pressed")).toBe("true");
    const cited = requirements.querySelector("[data-cited-version]") as HTMLElement;
    expect(within(cited).getByText("[R1 v1 TEXT]").tagName).toBe("MARK");
    expect(within(cited).getByText("v1")).toBeTruthy();

    // Edits: the earlier one struck through and labelled.
    const edits = container.querySelectorAll("[data-lineage-edit]");
    expect(edits[0]!.querySelector("s")?.textContent).toBe("v2: 34.0 h → 30.0 h (−4.0 h)");
    expect(edits[0]!.textContent).toContain("[FIRST EDIT REASON]");
    expect(edits[1]!.querySelector("s")).toBeNull();
    expect(edits[1]!.textContent).toContain("Owner Person · 22 Oct 2026");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("lists Findings with their agent and Assessment version; the source opens its summary", async () => {
    const user = userEvent.setup();
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const { container } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />,
    );
    await screen.findByText("[FINDING TITLE]");

    const [finding, effort] = Array.from(container.querySelectorAll("[data-lineage-finding]"));
    expect(finding!.getAttribute("data-lineage-finding")).toBe("finding");
    expect(effort!.textContent).toContain("R1 sized at 20 h · 20.0 h");
    const source = within(finding as HTMLElement).getByRole("button", {
      name: "Engineering Agent · Assessment v2",
    });
    expect(source.getAttribute("aria-expanded")).toBe("false");
    await user.click(source);
    const summary = finding!.querySelector("[data-assessment-summary]") as HTMLElement;
    expect(within(summary).getByText("[FINDING DETAIL]")).toBeTruthy();
    expect(within(summary).getByText("high")).toBeTruthy();

    const decision = container.querySelector("[data-lineage-decision]") as HTMLElement;
    expect(decision.textContent).toContain("Conflict resolved: 20 h");
    expect(decision.textContent).toContain("[CONFLICT REASON]");
    expect(decision.textContent).toContain("Owner Person · 21 Oct 2026");
    const review = container.querySelector("[data-lineage-review]") as HTMLElement;
    expect(review.textContent).toContain("Approved");
    expect(review.textContent).toContain("Ana Reviewer");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Open in Trace links to the line's trace events", async () => {
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    render(<LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />);
    const link = screen.getByRole("link", { name: "Open in Trace" });
    expect(link.getAttribute("href")).toBe(
      `/opportunities/${LINEAGE_OPP}/trace?subject=estimates.estimate_line&subject_id=${LINEAGE_LINE}`,
    );
  });

  it("a focus request scrolls to and focuses the Lineage heading", async () => {
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const { rerender } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} focusRequest={0} />,
    );
    expect(scrolled).not.toHaveBeenCalled();

    rerender(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} focusRequest={1} />,
    );

    expect(document.activeElement?.textContent).toBe("Lineage");
    expect(scrolled).toHaveBeenCalled();
  });

  it("a grid request already acted on, or one that goes down, moves no focus", () => {
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const onFocus = vi.fn();
    const section = (request: number, handled: number) => (
      <LineLineageSection
        opportunityId={LINEAGE_OPP}
        lineId={LINEAGE_LINE}
        externalFocusRequest={request}
        externalFocusHandled={handled}
        onExternalFocus={onFocus}
      />
    );
    // Mounted (e.g. remounted for a new version) with a request already handled: nothing.
    const { rerender, unmount } = render(section(2, 2));
    expect(scrolled).not.toHaveBeenCalled();
    rerender(section(3, 2));
    expect(document.activeElement?.textContent).toBe("Lineage");
    expect(onFocus).toHaveBeenCalledWith(3);
    unmount();

    // A fresh request on mount (`t` opening the line) acts once.
    scrolled.mockClear();
    render(section(4, 3));
    expect(scrolled).toHaveBeenCalledTimes(1);
  });

  it("reads the lineage again when the reload key changes (the line was edited)", async () => {
    loadLineLineage.mockResolvedValue({ kind: "ok", lineage: lineLineage() });
    const { rerender } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} reloadKey="1:34" />,
    );
    await waitFor(() => expect(loadLineLineage).toHaveBeenCalledTimes(1));
    rerender(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} reloadKey="2:30" />,
    );
    await waitFor(() => expect(loadLineLineage).toHaveBeenCalledTimes(2));
  });

  it("lists a Contingency linked to the line with its hours and who accepted it", async () => {
    loadLineLineage.mockResolvedValue({
      kind: "ok",
      lineage: lineLineage({ assumptions: [lineContingency()] }),
    });
    const { container } = render(
      <LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />,
    );
    const item = (await waitFor(() => {
      const found = container.querySelector("[data-lineage-assumption]");
      if (!found) throw new Error("not yet");
      return found;
    })) as HTMLElement;
    expect(item.textContent).toContain("A2 · 8.0 h · [CONTINGENCY WORDING]");
    expect(item.textContent).toContain("Accepted · Owner Person · 20 Oct 2026");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when it could not be loaded, also when the action throws", async () => {
    loadLineLineage.mockRejectedValue(new Error("down"));
    render(<LineLineageSection opportunityId={LINEAGE_OPP} lineId={LINEAGE_LINE} />);
    expect(await screen.findByText("The lineage could not be loaded.")).toBeTruthy();
  });
});

describe("AssumptionLineageSection", () => {
  it("shows the chain: origin, question, answer with its passage, conversion, acceptance", async () => {
    const user = userEvent.setup();
    loadAssumptionLineage.mockResolvedValue({ kind: "ok", lineage: assumptionLineage() });
    getPassage.mockResolvedValue({
      kind: "ok",
      passage: {
        passage_id: PASSAGE_ID,
        source_id: "00000000-0000-7000-8000-0000000000e8",
        source_version: 1,
        filename: "answer.txt",
        label: "S2 · answer.txt",
        before: "[BEFORE] ",
        text: "[ANSWER]",
        after: " [AFTER]",
      },
    });
    const { container } = render(
      <AssumptionLineageSection
        opportunityId={LINEAGE_OPP}
        assumptionId="00000000-0000-7000-8000-0000000000aa"
      />,
    );
    const chain = await screen.findByRole("list", { name: "Chain of origin" });

    expect(
      Array.from(chain.querySelectorAll("[data-lineage-step]")).map((li) =>
        li.getAttribute("data-lineage-step"),
      ),
    ).toEqual(["gap", "question", "answer", "conversion", "acceptance"]);
    expect(headings(container)).toEqual([
      "Gap",
      "Clarification Question",
      "Answer",
      "Conversion",
      "Acceptance",
    ]);
    expect(within(chain).getByText("Clarification Agent · 18 Oct 2026")).toBeTruthy();

    await user.click(within(chain).getByRole("button", { name: /S2 · answer.txt/ }));

    expect(getPassage).toHaveBeenCalledWith(LINEAGE_OPP, PASSAGE_ID);
    expect((await within(chain).findByText("[ANSWER]")).tagName).toBe("MARK");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Story 10.4: the chain ends with the Actuals that recorded it as failed", async () => {
    const base = assumptionLineage();
    loadAssumptionLineage.mockResolvedValue({
      kind: "ok",
      lineage: assumptionLineage({
        steps: [...base.steps, actualStep({ superseded: true }), actualStep({ id: "c2", title: "L2 · Final Actual · 52.0 h" })],
      }),
    });
    const { container } = render(
      <AssumptionLineageSection
        opportunityId={LINEAGE_OPP}
        assumptionId="00000000-0000-7000-8000-0000000000aa"
      />,
    );
    const chain = await screen.findByRole("list", { name: "Chain of origin" });
    const steps = Array.from(chain.querySelectorAll("[data-lineage-step]"));
    expect(steps.map((li) => li.getAttribute("data-lineage-step")).slice(-3)).toEqual([
      "acceptance",
      "actual",
      "actual",
    ]);
    expect(headings(container).slice(-2)).toEqual(["Actual", "Actual"]);
    const [first, second] = steps.slice(-2) as HTMLElement[];
    expect(first!.querySelector("s")?.textContent).toBe("L2 · Final Actual · 48.0 h");
    expect(within(first!).getByText("(superseded)")).toBeTruthy();
    expect(within(second!).getByText("L2 · Final Actual · 52.0 h")).toBeTruthy();
    expect(within(second!).getByText("Integration complexity")).toBeTruthy();
    expect(within(second!).getByText("Dana Delivery · 26 Oct 2026")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("an empty chain reads Nothing recorded.", async () => {
    loadAssumptionLineage.mockResolvedValue({
      kind: "ok",
      lineage: assumptionLineage({ steps: [] }),
    });
    render(
      <AssumptionLineageSection
        opportunityId={LINEAGE_OPP}
        assumptionId="00000000-0000-7000-8000-0000000000aa"
      />,
    );
    expect(await screen.findByText("Nothing recorded.")).toBeTruthy();
  });
});
