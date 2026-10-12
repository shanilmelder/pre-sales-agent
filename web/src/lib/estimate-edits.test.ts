import { describe, expect, it } from "vitest";

import {
  editedLabel,
  editHistory,
  mixSum,
  keepReason,
  parseEffort,
  readKeptReason,
  roundedHours,
  roundHours,
  uncarriedEditsNote,
} from "@/lib/estimates";
import { eventLabel, fieldLabel, subjectHref, subjectLabel } from "@/lib/trace";

describe("editing an Estimate line (Story 8.2)", () => {
  it.each([
    ["32", 32],
    [" 12.25 ", 12.25],
    ["0", 0],
    ["2000", 2000],
    ["2000.04", 2000.04],
    ["1,000", 1000],
    ["1,500.5", 1500.5],
    [".5", 0.5],
  ])("parses %j as %d hours", (raw, value) => {
    expect(parseEffort(raw)).toBe(value);
  });

  it.each(["", "lots", "-1", "2000.05", "2000.1", "1e3", "3 h", "7,5", "1,00", "10,000,0"])(
    "refuses %j",
    (raw) => {
      expect(parseEffort(raw)).toBeNull();
    },
  );

  it("rounds hours half up to 0.1, as the server does", () => {
    expect(roundHours(0.35)).toBe(0.4);
    expect(roundHours(12.25)).toBe(12.3);
    expect(roundHours(1.04)).toBe(1);
    expect(roundedHours(0.35)).toBe("0.4");
    expect(roundedHours(2000.04)).toBe("2000.0");
  });

  it("adds up a role mix", () => {
    expect(mixSum({ engineer: 50, project_manager: 30, qa: 10 })).toBe(90);
  });

  it("labels an edited line, carried or not, and says who, when and why", () => {
    const base = {
      edited: true,
      edited_by_name: "Jane Doe",
      edited_at: "2026-10-05T10:00:00Z",
      edit_reason: "Reuse the existing connector",
      edit_carried_from_version: null,
    };
    expect(editedLabel({ ...base, edited: false })).toBeNull();
    expect(editedLabel(base)).toBe("Edited");
    expect(editedLabel({ ...base, edit_carried_from_version: 2 })).toBe("Edited, carried from v2");
    expect(editHistory(base)).toBe("Jane Doe, 5 Oct 2026: Reuse the existing connector");
    expect(editHistory({ ...base, edited: false })).toBeNull();
  });

  it("words the note for edits a re-draft couldn't carry", () => {
    expect(uncarriedEditsNote(1, 2)).toBe(
      "1 edited line from v2 had no matching line; it stays in v2 and the Trace.",
    );
    expect(uncarriedEditsNote(3, 4)).toBe(
      "3 edited lines from v4 had no matching line; they stay in v4 and the Trace.",
    );
  });

  it("keeps one last reason per Opportunity, for the version it was given on", () => {
    window.localStorage.clear();
    keepReason("opp", "v-1", "First");
    keepReason("opp", "v-2", "Second");
    expect(window.localStorage.length).toBe(1);
    expect(readKeptReason("opp", "v-2")).toBe("Second");
    expect(readKeptReason("opp", "v-1")).toBe("");
    expect(readKeptReason("other", "v-2")).toBe("");
  });

  it("names the edit in the Decision Trace and links it to the Estimate", () => {
    expect(eventLabel("estimates.estimate_line.edited")).toBe("Estimate line edited");
    expect(subjectLabel("estimates.estimate_line")).toBe("Estimate line");
    expect(subjectHref("x", "estimates.estimate_line")).toBe("/opportunities/x/estimate");
    expect(fieldLabel("before_hours")).toBe("Before (hours)");
    expect(fieldLabel("after_role_mix")).toBe("After (role mix %)");
  });
});
