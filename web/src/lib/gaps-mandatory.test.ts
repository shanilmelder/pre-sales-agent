import { describe, expect, it } from "vitest";

import {
  canDismiss,
  checklistNoLongerApplies,
  isMandatory,
  rankGaps,
  triggerLabel,
  type Gap,
} from "./gaps";

describe("mandatory Gap helpers (Story 4.2)", () => {
  it("labels a Checklist trigger with the Checklist and its version", () => {
    expect(
      triggerLabel({
        category: "security_and_compliance",
        trigger: {
          kind: "checklist_item",
          checklist_id: "c",
          version: 2,
          item_id: "i",
          checklist_name: "Security baseline",
        },
      }),
    ).toBe("Checklist · Security baseline v2");
    expect(
      triggerLabel({
        category: "data_volumes",
        trigger: { kind: "agent_category", category: "data_volumes" },
      }),
    ).toBe("Clarification Agent · Data volumes");
  });

  it("offers Dismiss on a mandatory Gap only once its Checklist no longer applies", () => {
    const detected = { origin: "detected", checklist_applies: true } as const;
    const applies = { origin: "mandatory_checklist", checklist_applies: true } as const;
    const lapsed = { origin: "mandatory_checklist", checklist_applies: false } as const;
    expect([isMandatory(detected), isMandatory(applies)]).toEqual([false, true]);
    expect([canDismiss(detected), canDismiss(applies), canDismiss(lapsed)]).toEqual([
      true,
      false,
      true,
    ]);
    expect([checklistNoLongerApplies(applies), checklistNoLongerApplies(lapsed)]).toEqual([
      false,
      true,
    ]);
  });

  it("ranks mandatory Gaps first within an impact, then oldest first", () => {
    const g = (id: string, impact: Gap["impact"], origin: Gap["origin"], at: string) =>
      ({ id, status: "open", impact, origin, created_at: `2026-10-05T09:00:0${at}Z` }) as Gap;
    const ranked = rankGaps([
      g("low-m", "low", "mandatory_checklist", "0"),
      g("high-d", "high", "detected", "1"),
      g("high-m2", "high", "mandatory_checklist", "3"),
      g("high-m1", "high", "mandatory_checklist", "2"),
    ]);
    expect(ranked.map((x) => x.id)).toEqual(["high-m1", "high-m2", "high-d", "low-m"]);
  });
});
