import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  NO_DUE,
  NO_RECENT,
  RETENTION_FOOTNOTE,
  type PurgeEvent,
  type RetentionDue,
} from "@/lib/retention";
import { axeViolations } from "@/test/axe";

import { RetentionTables } from "./retention-tables";

const LOST = "01a16ea4-dd68-7f04-8c34-a82544b2e521";
const WON = "01a16ea4-e196-73c1-8898-7251e747c73b";
const PURGED = "01a16eb0-0000-7000-8000-000000000001";

const due: RetentionDue[] = [
  { opportunity_id: LOST, outcome: "lost", rule: "lost_3y", retention_until: "2026-10-20" },
  { opportunity_id: WON, outcome: "won", rule: "won_7y", retention_until: "2026-11-14" },
];
const recent: PurgeEvent[] = [
  {
    purged_opportunity_id: PURGED,
    rule: "lost_3y",
    rows_by_module: { opportunities: 2, intake: 1200, platform: 40 },
    files_deleted: 3,
    occurred_at: "2026-10-28T02:00:00Z",
  },
];

describe("RetentionTables", () => {
  it("lists what is due and what was purged, with ids, outcomes, dates and counts", async () => {
    const { container } = render(<RetentionTables due={due} recent={recent} />);

    const dueTable = screen.getByRole("table", { name: "Due for purge" });
    expect(within(dueTable).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Opportunity",
      "Outcome",
      "Rule",
      "Retention date",
    ]);
    expect(within(dueTable).getAllByRole("rowheader").map((c) => c.textContent)).toEqual([
      LOST,
      WON,
    ]);
    const lostRow = container.querySelector(`[data-opportunity-id="${LOST}"]`) as HTMLElement;
    const lostPill = within(lostRow).getByText("Lost");
    expect(lostPill.closest('[data-slot="pill"]')?.getAttribute("data-tone")).toBe("neutral");
    expect(within(lostRow).getByText("Lost + 3 years")).toBeTruthy();
    expect(within(lostRow).getByText("20 Oct 2026")).toBeTruthy();
    const wonRow = container.querySelector(`[data-opportunity-id="${WON}"]`) as HTMLElement;
    expect(within(wonRow).getByText("Won").closest('[data-slot="pill"]')).toBeTruthy();
    expect(within(wonRow).getByText("Won + 7 years")).toBeTruthy();

    const recentTable = screen.getByRole("table", { name: "Recent purges" });
    expect(within(recentTable).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(
      ["When", "Opportunity", "Rule", "Rows", "Files"],
    );
    const row = container.querySelector(`[data-purged-id="${PURGED}"]`) as HTMLElement;
    expect(within(row).getByText("28 Oct 2026, 02:00 UTC")).toBeTruthy();
    expect(within(row).getByText("1,242 rows")).toBeTruthy();
    expect(within(row).getByText("intake 1,200 · opportunities 2 · platform 40")).toBeTruthy();
    expect(within(row).getByText("3 files")).toBeTruthy();

    expect(screen.getByText(RETENTION_FOOTNOTE)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("offers no control that deletes", () => {
    render(<RetentionTables due={due} recent={recent} />);
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryAllByRole("link")).toEqual([]);
    expect(screen.queryByText(/delete now|purge now/i)).toBeNull();
  });

  it("shows an empty sentence in each card when there is nothing", async () => {
    const { container } = render(<RetentionTables due={[]} recent={[]} />);
    expect(screen.getByText(NO_DUE)).toBeTruthy();
    expect(screen.getByText(NO_RECENT)).toBeTruthy();
    expect(screen.queryAllByRole("table")).toEqual([]);
    expect(screen.getByRole("heading", { name: "Due for purge" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Recent purges" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
