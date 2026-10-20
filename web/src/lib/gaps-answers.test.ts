import { describe, expect, it } from "vitest";

import {
  answeredLabel,
  answeredOnProblem,
  answerTextProblem,
  dayMonth,
  gapStatus,
  gapsChangedAnnouncement,
  historyAction,
  isAnswerable,
  isSent,
  openGapCount,
  possibleAnswerLabel,
  questionStatus,
  rankGaps,
  requirementChangeLabel,
  requirementHref,
  type Gap,
  type GapHistoryEntry,
} from "./gaps";

describe("answer helpers (Story 4.7)", () => {
  it("formats day and month, and the answered label", () => {
    expect(dayMonth("2026-10-12")).toBe("12 Oct");
    expect(dayMonth("2026-01-05T09:00:00Z")).toBe("5 Jan");
    expect(dayMonth("not a date")).toBe("not a date");
    expect(answeredLabel("2026-10-12")).toBe("Answered by customer, 12 Oct");
  });

  it("answered pills: the question and the Gap, a resolved check, not a fill", () => {
    const question = questionStatus("answered");
    const gap = gapStatus("answered");
    expect([question.label, question.tone]).toEqual(["Answered", "text-resolved"]);
    expect([gap.label, gap.tone]).toEqual(["Answered", "text-resolved"]);
    expect(question.icon).toBe(gap.icon);
  });

  it("only sent or No answer questions can be answered; answered ones count as sent", () => {
    expect(isAnswerable("sent")).toBe(true);
    expect(isAnswerable("unanswered")).toBe(true);
    expect(isAnswerable("approved")).toBe(false);
    expect(isAnswerable("answered")).toBe(false);
    expect(isSent("answered")).toBe(true);
  });

  it("checks the answer text and date", () => {
    expect(answerTextProblem("  ")).toBe("Give the customer’s answer.");
    expect(answerTextProblem("x".repeat(20001))).toBe(
      "The answer can be at most 20,000 characters.",
    );
    expect(answerTextProblem("Yes")).toBeNull();
    expect(answeredOnProblem("", "2026-10-19")).toBe("Give the date the customer answered.");
    expect(answeredOnProblem("2026-10-20", "2026-10-19")).toBe(
      "The date answered can’t be in the future.",
    );
    expect(answeredOnProblem("2026-10-19", "2026-10-19")).toBeNull();
  });

  it("labels suggestions, Requirement changes and their links", () => {
    expect(
      possibleAnswerLabel({
        passage: {
          passage_id: "p",
          source_id: "s",
          source_version: 1,
          filename: "reply.txt",
          label: "S2 · reply.txt",
          excerpt: "",
        },
      }),
    ).toBe("Possible answer in Source 'reply.txt'");
    expect(requirementChangeLabel({ requirement_id: "r", label: "R1", kind: "pending" })).toBe(
      "R1 · pending change",
    );
    expect(requirementChangeLabel({ requirement_id: "r", label: "R2", kind: "versioned" })).toBe(
      "R2 · updated",
    );
    expect(requirementHref("o 1", "r/1")).toBe("/opportunities/o%201/requirements?requirement=r%2F1");
  });

  it("counts open Gaps and announces answered and open counts only when they change", () => {
    const open = { status: "open" } as const;
    const answered = { status: "answered" } as const;
    expect(openGapCount([open, answered, open])).toBe(2);
    expect(gapsChangedAnnouncement([open, open], [answered, open])).toBe("1 Gap answered, 1 open");
    expect(gapsChangedAnnouncement([open, answered], [open, answered])).toBeNull();
    expect(gapsChangedAnnouncement([open, open, open], [answered, answered, open])).toBe(
      "2 Gaps answered, 1 open",
    );
  });

  it("ranks answered Gaps after open ones and names the answered history entry", () => {
    const g = (id: string, status: Gap["status"]) =>
      ({ id, status, impact: "high", created_at: "2026-10-05T09:00:00Z" }) as Gap;
    expect(rankGaps([g("d", "dismissed"), g("a", "answered"), g("o", "open")]).map((x) => x.id))
      .toEqual(["o", "a", "d"]);
    expect(historyAction({ kind: "answered" } as GapHistoryEntry)).toBe("Answered");
  });
});
