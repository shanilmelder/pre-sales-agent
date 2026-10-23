import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TraceEvent, TracePage } from "@/lib/trace";
import { axeViolations } from "@/test/axe";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace,
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/opportunities/x/trace",
}));

import { KeyboardShortcuts } from "../shell/keyboard-shortcuts";
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders, useShell } from "../shell/shell-context";
import { TraceList, TraceSection } from "./trace-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const NOW = Date.parse("2026-10-05T12:00:00Z");

const RED_TEAM: TraceEvent = {
  id: "00000000-0000-7000-8000-0000000000e1",
  occurred_at: "2026-10-05T11:55:00Z",
  event_type: "assessments.red_team_review.completed",
  actor: {
    type: "agent",
    id: "red_team_agent@1.2.0",
    name: "Red Team Agent",
    version: "1.2.0",
  },
  subject: {
    type: "assessments.review",
    id: "00000000-0000-7000-8000-0000000000c1",
    version: 1,
  },
  payload: { version: 1, finding_count: 3, critical_count: 0 },
};
const ACCEPTED: TraceEvent = {
  id: "00000000-0000-7000-8000-0000000000e2",
  occurred_at: "2026-10-05T09:00:00Z",
  event_type: "estimates.assumption.accepted",
  actor: {
    type: "user",
    id: "00000000-0000-7000-8000-0000000000a1",
    name: "[NAME]",
    version: null,
  },
  subject: {
    type: "estimates.assumption",
    id: "00000000-0000-7000-8000-0000000000f1",
    version: null,
  },
  payload: {
    version_id: "00000000-0000-7000-8000-0000000000d1",
    kind: "contingency",
    amount_hours: 16,
    line_id: null,
    gap_id: "00000000-0000-7000-8000-0000000000b1",
    accepted_by: "00000000-0000-7000-8000-0000000000a1",
  },
};
const PARSED: TraceEvent = {
  id: "00000000-0000-7000-8000-0000000000e3",
  occurred_at: "2026-10-01T09:00:00Z",
  event_type: "intake.future_thing.happened",
  actor: {
    type: "system",
    id: "intake.parse_source",
    name: "System",
    version: null,
  },
  subject: {
    type: "identity.user",
    id: "00000000-0000-7000-8000-0000000000a9",
    version: null,
  },
  payload: {},
};

const LINE_EDITED: TraceEvent = {
  id: "00000000-0000-7000-8000-0000000000e4",
  occurred_at: "2026-10-05T10:00:00Z",
  event_type: "estimates.estimate_line.edited",
  actor: {
    type: "user",
    id: "00000000-0000-7000-8000-0000000000a1",
    name: "Sam Delivery",
    version: null,
  },
  subject: {
    type: "estimates.estimate_line",
    id: "00000000-0000-7000-8000-0000000000f2",
    version: 3,
  },
  payload: {
    version: 3,
    before_hours: 12,
    after_hours: 16,
    before_role_mix: { engineer: 70, project_manager: 20, qa: 10 },
    after_role_mix: { engineer: 60, project_manager: 20, qa: 20 },
    reason: "[REASON]",
  },
};
const CHECKLIST: TraceEvent = {
  id: "00000000-0000-7000-8000-0000000000e5",
  occurred_at: "2026-10-05T08:00:00Z",
  event_type: "knowledge.checklist.published",
  actor: {
    type: "system",
    id: "knowledge.publish",
    name: "System",
    version: null,
  },
  subject: {
    type: "knowledge.checklist",
    id: "00000000-0000-7000-8000-0000000000f3",
    version: 2,
  },
  payload: {},
};

const OPTIONS: TracePage["options"] = {
  subject_types: [
    "assessments.review",
    "estimates.assumption",
    "identity.user",
  ],
  actor_types: ["agent", "system", "user"],
  event_types: [
    "assessments.red_team_review.completed",
    "estimates.assumption.accepted",
  ],
};

function page(items: TraceEvent[], extra: Partial<TracePage> = {}): TracePage {
  return {
    items,
    page: 1,
    page_size: 50,
    total: items.length,
    options: OPTIONS,
    ...extra,
  };
}

function renderSection(
  initial: TracePage,
  filters: Record<string, string> = {},
  singleKeyShortcuts = true,
) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <TraceSection
        opportunityId={OPP_ID}
        page={initial}
        filters={filters}
        now={NOW}
      />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (name: RegExp) => screen.getByRole("button", { name });
const pane = () => screen.getByRole("complementary", { name: "Details" });
/** A filter chip, by its label (it may also show the applied value: "Actor: Agent"). */
const chip = (label: string) =>
  screen.getByRole("button", { name: new RegExp(`^${label}(: .*)?$`) });
/** Opens a chip's popover and returns its select. */
async function openSelect(label: string) {
  fireEvent.click(chip(label));
  await screen.findByRole("dialog", { name: `${label} filter` });
  return screen.getByLabelText(label) as HTMLSelectElement;
}

beforeEach(() => {
  replace.mockReset();
});

describe("TraceList", () => {
  it("shows 4-column rows: relative time, actor tile and name, the event and the subject link", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <TraceList
          opportunityId={OPP_ID}
          items={[RED_TEAM, ACCEPTED, PARSED]}
          now={NOW}
        />
      </ShellProviders>,
    );
    const rows = screen.getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "5 min ago" +
        "RA" +
        "Red Team Agent" +
        "Red Team Review completed" +
        "Red Team Review v1",
      "3 h ago" + "[" + "[NAME]" + "Assumption accepted" + "Assumption",
      "4 d ago" + "S" + "System" + "intake.future_thing.happened" + "User",
    ]);
    // The 4-column grid from md up; the initials tile is decorative.
    expect(rows[0].className).toContain(
      "md:grid-cols-[130px_190px_minmax(0,1fr)_190px]",
    );
    expect(
      within(rows[0]).getByRole("button", { name: /^5 min ago\s*Red Team Agent/ }),
    ).toBeTruthy();
    expect(rows[0].querySelector("time")?.getAttribute("title")).toBe(
      "5 Oct 2026, 11:55:00 UTC",
    );
    expect(within(rows[0]).getByRole("link").getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/assessments`,
    );
    expect(within(rows[1]).getByRole("link").getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/estimate`,
    );
    // A subject with no tab is plain text.
    expect(within(rows[2]).queryByRole("link")).toBeNull();
    expect(within(rows[2]).getByText("User").className).toContain("text-text-secondary");
    const tabStops = screen
      .getAllByRole("button")
      .filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([row(/Red Team Review completed/)]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tiles: agents and the system a primary square, people a green circle", () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <TraceList
          opportunityId={OPP_ID}
          items={[RED_TEAM, ACCEPTED, PARSED]}
          now={NOW}
        />
      </ShellProviders>,
    );
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>("[data-actor-type][aria-hidden]"),
    );
    expect(tiles.map((t) => [t.dataset.actorType, t.textContent])).toEqual([
      ["agent", "RA"],
      ["user", "["],
      ["system", "S"],
    ]);
    expect(tiles[0].className).toContain("rounded-md");
    expect(tiles[0].className).toContain("bg-primary-tint");
    expect(tiles[1].className).toContain("rounded-full");
    expect(tiles[1].className).toContain("bg-resolved-tint");
    expect(tiles[2].className).toContain("bg-primary-tint");
    // The names are shown beside them.
    expect(screen.getByText("Red Team Agent")).toBeTruthy();
    expect(screen.getByText("[NAME]")).toBeTruthy();
    expect(screen.getByText("System")).toBeTruthy();
  });

  it("j/k and the arrows move between rows; j/k are off with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    const items = [RED_TEAM, ACCEPTED];
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <TraceList opportunityId={OPP_ID} items={items} now={NOW} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(/Red Team/));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/Assumption accepted/));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(/Red Team/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/Assumption accepted/));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <TraceList opportunityId={OPP_ID} items={items} now={NOW} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(/Red Team/));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(/Assumption accepted/));
  });
});

describe("the inspector", () => {
  it("Enter opens the event in sections, every field in catalogue order, focus on its label", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(page([RED_TEAM, ACCEPTED]));

    // The filters come first in Tab order; the list is the next stop.
    row(/Red Team/).focus();
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", {
      level: 3,
      name: "Assumption accepted",
    });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(
      row(/Assumption accepted/)
        .closest('[role="row"]')
        ?.getAttribute("aria-selected"),
    ).toBe("true");
    const terms = within(inspector)
      .getAllByRole("term")
      .map((t) => t.textContent);
    const values = within(inspector)
      .getAllByRole("definition")
      .map((d) => d.textContent);
    expect(terms).toEqual([
      "Event",
      "Actor",
      "Subject",
      "Subject id",
      "Estimate Version id",
      "Kind",
      "Amount (hours)",
      "Line id",
      "Gap id",
      "Accepted by",
    ]);
    expect(values).toEqual([
      "estimates.assumption.accepted",
      "[NAME]",
      "Assumption",
      ACCEPTED.subject.id,
      ACCEPTED.payload.version_id,
      "contingency",
      "16",
      "None",
      ACCEPTED.payload.gap_id,
      ACCEPTED.payload.accepted_by,
    ]);
    expect(within(inspector).getByText("Trace event · 5 Oct 2026, 09:00:00 UTC")).toBeTruthy();
    expect(within(inspector).getByText("· Person")).toBeTruthy();
    expect(within(inspector).getByRole("heading", { level: 4, name: "Payload" })).toBeTruthy();
    // No Change section for any event but a line edit.
    expect(within(inspector).queryByRole("heading", { name: "Change" })).toBeNull();
    expect(
      within(inspector).getByText(
        "Trace rows are append-only. Model reasoning is not stored, only decisions and Evidence.",
      ),
    ).toBeTruthy();
    const section = within(inspector).getByRole("region", {
      name: "Assumption accepted",
    });
    expect(within(section).queryByRole("button")).toBeNull();
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows an agent with its version; a click opens without moving focus", async () => {
    const user = userEvent.setup();
    renderSection(page([RED_TEAM]));

    await user.click(row(/Red Team/));

    const inspector = pane();
    expect(
      within(inspector).getByRole("heading", { level: 3 }).textContent,
    ).toBe("Red Team Review completed");
    // In the header (with the actor type) and the Payload's Actor row.
    expect(within(inspector).getAllByText("Red Team Agent (v1.2.0)")).toHaveLength(2);
    expect(within(inspector).getByText("· Agent")).toBeTruthy();
    expect(within(inspector).getByText("Finding count")).toBeTruthy();
    expect(document.activeElement).toBe(row(/Red Team/));
  });
});

describe("the inspector's sections", () => {
  it("a line edit shows the Change: − before and + after hours and role mix", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(page([LINE_EDITED]));
    await user.click(row(/Estimate line edited/));

    const inspector = pane();
    const change = within(inspector).getByRole("heading", { level: 4, name: "Change" });
    const items = within(change.parentElement!).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "−Before: 12.0 h · E 70 · PM 20 · QA 10",
      "+After: 16.0 h · E 60 · PM 20 · QA 20",
    ]);
    expect(items[0].className).toContain("bg-blocker-tint");
    expect(items[1].className).toContain("bg-resolved-tint");
    // The signs are decorative; the words carry the meaning.
    expect(items[0].querySelector("[aria-hidden]")?.textContent).toBe("−");
    expect(within(items[0]).getByText("Before:").className).toContain("sr-only");
    expect(within(inspector).getAllByText("Estimate line v3").length).toBeGreaterThan(0);
    // The Payload shows the role mixes the same way, not as raw JSON.
    const terms = within(inspector).getAllByRole("term").map((t) => t.textContent);
    const values = within(inspector).getAllByRole("definition").map((d) => d.textContent);
    expect(values[terms.indexOf("Before (role mix %)")]).toBe("E 70 · PM 20 · QA 10");
    expect(values[terms.indexOf("After (role mix %)")]).toBe("E 60 · PM 20 · QA 20");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a subject without a tab: plain text in the row, no Open link in the inspector", async () => {
    const user = userEvent.setup();
    renderSection(page([CHECKLIST]));
    const checklistRow = row(/Checklist published/).closest<HTMLElement>('[role="row"]')!;
    expect(within(checklistRow).queryByRole("link")).toBeNull();
    expect(within(checklistRow).getByText("Checklist v2").className).toContain(
      "text-text-secondary",
    );

    await user.click(row(/Checklist published/));
    const inspector = pane();
    expect(within(inspector).queryByRole("link")).toBeNull();
    expect(within(inspector).getByText("· System")).toBeTruthy();
    expect(within(inspector).queryByRole("heading", { name: "Change" })).toBeNull();
  });
});

function PaneToggle() {
  const { toggleRightPane } = useShell();
  return (
    <button type="button" id={RIGHT_PANE_TOGGLE_ID} onClick={toggleRightPane}>
      Toggle
    </button>
  );
}

describe("the inspector's focus", () => {
  function renderWithToggle(initial: TracePage) {
    return render(
      <ShellProviders singleKeyShortcuts>
        <KeyboardShortcuts permissions={["opportunities.opportunity.create"]} />
        <PaneToggle />
        <TraceSection opportunityId={OPP_ID} page={initial} filters={{}} now={NOW} />
        <RightPane />
      </ShellProviders>,
    );
  }
  const openPane = () => screen.queryByRole("complementary", { name: "Details" });
  const toggle = () => screen.getByRole("button", { name: "Toggle" });

  it("the subject link in the inspector is reachable by Tab", async () => {
    const user = userEvent.setup();
    renderWithToggle(page([RED_TEAM, ACCEPTED]));
    row(/Assumption accepted/).focus();
    await user.keyboard("{Enter}");
    const heading = within(openPane()!).getByRole("heading", { level: 3 });
    await waitFor(() => expect(document.activeElement).toBe(heading));

    await user.tab();

    const link = within(openPane()!).getByRole("link", { name: "Open in Estimate" });
    expect(document.activeElement).toBe(link);
    expect(link.getAttribute("href")).toBe(`/opportunities/${OPP_ID}/estimate`);
  });

  it.each([
    [
      "Esc",
      async (user: ReturnType<typeof userEvent.setup>) => {
        await user.keyboard("{Escape}");
      },
    ],
    [
      "the pane toggle",
      async (user: ReturnType<typeof userEvent.setup>) => {
        await user.click(toggle());
      },
    ],
  ])("closing with %s after a keyboard open returns focus to the row", async (_, close) => {
    const user = userEvent.setup();
    renderWithToggle(page([RED_TEAM, ACCEPTED]));
    row(/Assumption accepted/).focus();
    await user.keyboard("{Enter}");
    const heading = within(openPane()!).getByRole("heading", { level: 3 });
    await waitFor(() => expect(document.activeElement).toBe(heading));

    await close(user);

    expect(openPane()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(row(/Assumption accepted/)));

    // Reopening with the toggle shows the event again without taking focus.
    await user.click(toggle());
    const reopened = within(openPane()!).getByRole("heading", { level: 3 });
    expect(reopened.textContent).toBe("Assumption accepted");
    expect(document.activeElement).not.toBe(reopened);
    expect(document.activeElement).toBe(toggle());
  });
});

describe("TraceSection", () => {
  it("a visible Trace title, the card and the append-only footnote", async () => {
    const { container } = renderSection(page([RED_TEAM, ACCEPTED]));
    expect(screen.getByRole("heading", { level: 2, name: "Trace" }).className).toContain(
      "flex-1",
    );
    const group = screen.getByRole("group", { name: "Filters" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Subject",
      "Actor",
      "Event",
    ]);
    expect(chip("Actor").className).toContain("border-dashed");
    expect(within(group).queryByRole("link", { name: "Clear filters" })).toBeNull();
    expect(screen.getByText("Trace rows are append-only and cannot be edited.")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("an applied filter reads 'Label: value' in the primary tint, with Clear filters", () => {
    renderSection(page([RED_TEAM]), { actor: "agent" });
    const actor = chip("Actor");
    expect(actor.textContent).toBe("Actor: Agent");
    expect(actor.className).toContain("bg-primary-tint");
    expect(chip("Subject").textContent).toBe("Subject");
    expect(
      within(screen.getByRole("group", { name: "Filters" }))
        .getByRole("link", { name: "Clear filters" })
        .getAttribute("href"),
    ).toBe(`/opportunities/${OPP_ID}/trace`);
  });

  it("says so when nothing is recorded, without filters", () => {
    renderSection(
      page([], {
        options: { subject_types: [], actor_types: [], event_types: [] },
      }),
    );
    expect(screen.getByTestId("empty-tab-card")).toBeTruthy();
    expect(screen.getByText("No trace events")).toBeTruthy();
    expect(
      screen.getByText("Decisions and Evidence are recorded here as work happens."),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Overview" }).getAttribute("href"),
    ).toMatch(/\/overview$/);
    expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
  });

  it("filtered to nothing: says so, with Clear filters", async () => {
    const { container } = renderSection(page([]), {
      actor: "system",
      event: "x.y.z",
    });
    expect(screen.getByText("No events match these filters.")).toBeTruthy();
    expect(screen.queryByTestId("empty-tab-card")).toBeNull();
    // No card and no footnote.
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.queryByText("Trace rows are append-only and cannot be edited.")).toBeNull();
    const clears = screen.getAllByRole("link", { name: "Clear filters" });
    expect(clears.map((link) => link.getAttribute("href"))).toEqual([
      `/opportunities/${OPP_ID}/trace`,
      `/opportunities/${OPP_ID}/trace`,
    ]);
    expect(await axeViolations(container)).toEqual([]);
    // A value from the URL that isn't among the options is still shown as applied.
    expect(chip("Event").textContent).toBe("Event: x.y.z");
    expect(chip("Actor").textContent).toBe("Actor: System");
    const event = await openSelect("Event");
    expect(event.value).toBe("x.y.z");
  });

  it("each chip's select offers only the values present, in words, and writes the URL", async () => {
    const user = userEvent.setup();
    renderSection(page([RED_TEAM, ACCEPTED]), {
      subject: "assessments.review",
    });

    const actor = await openSelect("Actor");
    expect(
      Array.from(actor.options).map((o) => [o.value, o.textContent]),
    ).toEqual([
      ["", "Any actor"],
      ["agent", "Agent"],
      ["system", "System"],
      ["user", "Person"],
    ]);
    await user.keyboard("{Escape}");
    const subject = await openSelect("Subject");
    expect(subject.value).toBe("assessments.review");
    expect(Array.from(subject.options).map((o) => o.textContent)).toEqual([
      "Any subject",
      "Red Team Review",
      "Assumption",
      "User",
    ]);
    await user.keyboard("{Escape}");
    const event = await openSelect("Event");
    expect(Array.from(event.options).map((o) => o.textContent)).toEqual([
      "Any event",
      "Red Team Review completed",
      "Assumption accepted",
    ]);
    await user.keyboard("{Escape}");

    await user.selectOptions(await openSelect("Actor"), "agent");
    expect(replace).toHaveBeenLastCalledWith(
      `/opportunities/${OPP_ID}/trace?subject=assessments.review&actor=agent`,
      { scroll: false },
    );
    // A pick closes the popover; the chip shows the value at once.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(chip("Actor").textContent).toBe("Actor: Agent");
    await user.selectOptions(await openSelect("Subject"), "");
    expect(replace).toHaveBeenLastCalledWith(
      `/opportunities/${OPP_ID}/trace?actor=agent`,
      {
        scroll: false,
      },
    );
    await user.click(screen.getByRole("link", { name: "Clear filters" }));
    expect(replace).toHaveBeenLastCalledWith(`/opportunities/${OPP_ID}/trace`, {
      scroll: false,
    });
  });

  it("pages with Previous/Next and 'Page n of m', keeping the filters", () => {
    renderSection(page([RED_TEAM], { page: 2, total: 120 }), {
      actor: "agent",
    });
    expect(screen.getByText("Page 2 of 3")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Previous" }).getAttribute("href"),
    ).toBe(`/opportunities/${OPP_ID}/trace?actor=agent`);
    expect(
      screen.getByRole("link", { name: "Next" }).getAttribute("href"),
    ).toBe(`/opportunities/${OPP_ID}/trace?actor=agent&page=3`);
  });
});
