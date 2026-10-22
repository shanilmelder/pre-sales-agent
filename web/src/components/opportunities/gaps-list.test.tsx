import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AnswerWriteResult,
  ApproveAllQuestionsResult,
  CopyQuestionsResult,
  GapWriteResult,
  MarkSentResult,
  QuestionWriteResult,
  StartGapDetectionResult,
} from "@/app/opportunities/actions";
import type { GapsResult } from "@/app/opportunities/data";
import type {
  ClarificationQuestion,
  Detection,
  Gap,
  GapCategory,
  GapHistoryEntry,
  GapList,
  Impact,
} from "@/lib/gaps";
import { GAPS_FALLBACK_POLL_MS } from "@/lib/gaps";
import { axeViolations } from "@/test/axe";

const startGapDetection = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartGapDetectionResult>>(),
);
const loadGaps = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<GapsResult>>());
const editClarificationQuestion = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<QuestionWriteResult>>(),
);
const approveClarificationQuestion = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<QuestionWriteResult>>(),
);
const approveAllClarificationQuestions = vi.hoisted(() =>
  vi.fn<(opportunityId: string, shown: unknown) => Promise<ApproveAllQuestionsResult>>(),
);
const approveSelectedClarificationQuestions = vi.hoisted(() =>
  vi.fn<(opportunityId: string, selected: unknown) => Promise<ApproveAllQuestionsResult>>(),
);
const changeGapImpact = vi.hoisted(() => vi.fn<(input: unknown) => Promise<GapWriteResult>>());
const dismissGap = vi.hoisted(() => vi.fn<(input: unknown) => Promise<GapWriteResult>>());
const reopenGap = vi.hoisted(() => vi.fn<(input: unknown) => Promise<GapWriteResult>>());
const markClarificationQuestionsSent = vi.hoisted(() =>
  vi.fn<
    (opportunityId: string, sentOn: string, questions: unknown) => Promise<MarkSentResult>
  >(),
);
const markClarificationQuestionUnanswered = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<QuestionWriteResult>>(),
);
const recordAnswer = vi.hoisted(() => vi.fn<(input: unknown) => Promise<AnswerWriteResult>>());
const confirmAnswerMatch = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<AnswerWriteResult>>(),
);
const rejectAnswerMatch = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<AnswerWriteResult>>(),
);
const copyClarificationQuestions = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<CopyQuestionsResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  recordAnswer,
  confirmAnswerMatch,
  rejectAnswerMatch,
  markClarificationQuestionsSent,
  markClarificationQuestionUnanswered,
  copyClarificationQuestions,
  startGapDetection,
  loadGaps,
  editClarificationQuestion,
  approveClarificationQuestion,
  approveAllClarificationQuestions,
  approveSelectedClarificationQuestions,
  changeGapImpact,
  dismissGap,
  reopenGap,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/gaps",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { DetectionStatus, GapsList, GapsSection } from "./gaps-list";
import { ImpactBar } from "./impact-bar";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function gap(n: number, impact: Impact, category: GapCategory = "integration_details"): Gap {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    title: `[GAP ${n}]`,
    category,
    trigger: { kind: "agent_category", category },
    why_it_matters: `[WHY ${n}]`,
    impact,
    impact_basis: `[BASIS ${n}]`,
    origin: "detected",
    status: "open",
    converted_to: null,
    row_version: 1,
    created_at: "2026-10-05T09:00:00Z",
    requirements: [
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0aa`,
        version: 1,
        label: "R2",
        excerpt: `[EXCERPT ${n}]`,
      },
    ],
    question: {
      id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0bb`,
      text: `[QUESTION ${n}]`,
      topic: `[TOPIC ${n}]`,
      status: "drafted",
      status_changed_at: "2026-10-05T09:00:00Z",
      row_version: 1,
      approved_by: null,
      approved_at: null,
      edited_by_human: false,
      last_changed_by: null,
      sent_on: null,
      sent_by: null,
      answered_on: null,
      answered_by: null,
    },
    dismissal: null,
    history: [
      {
        kind: "raised",
        at: "2026-10-05T09:00:00Z",
        actor: "agent",
        old_impact: null,
        new_impact: null,
        reason_kind: null,
        reason: null,
      },
    ],
    last_changed_by: null,
    answer: null,
    answer_suggestions: [],
  };
}

const queued: Detection = { status: "queued", error_code: null };
const running: Detection = { status: "running", error_code: null };
const succeeded: Detection = { status: "succeeded", error_code: null };
const failed: Detection = { status: "failed", error_code: "model_unavailable" };

function list(
  items: Gap[],
  detection: Detection | null,
  canStart = true,
  canEdit = false,
  canEditGaps = canEdit,
  canSend = false,
): GapList {
  return {
    items,
    detection,
    can_start_detection: canStart,
    can_edit_questions: canEdit,
    can_edit_gaps: canEditGaps,
    can_send_questions: canSend,
  };
}

function renderSection(initial: GapList, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <GapsSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: new RegExp(`\\[GAP ${n}\\]`) });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  startGapDetection.mockReset();
  loadGaps.mockReset();
  editClarificationQuestion.mockReset();
  approveClarificationQuestion.mockReset();
  approveAllClarificationQuestions.mockReset();
  approveSelectedClarificationQuestions.mockReset();
  changeGapImpact.mockReset();
  dismissGap.mockReset();
  reopenGap.mockReset();
  markClarificationQuestionsSent.mockReset();
  markClarificationQuestionUnanswered.mockReset();
  copyClarificationQuestions.mockReset();
  recordAnswer.mockReset();
  confirmAnswerMatch.mockReset();
  rejectAnswerMatch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ImpactBar", () => {
  it.each([
    ["high", "High", 3],
    ["medium", "Medium", 2],
    ["low", "Low", 1],
  ] as const)("%s fills %s segments of 3, with its label", (impact, label, filled) => {
    render(<ImpactBar impact={impact} />);
    expect(screen.getByText(label)).toBeTruthy();
    const bar = screen.getByTestId("impact-bar");
    expect(bar.getAttribute("aria-hidden")).toBe("true");
    expect(bar.children).toHaveLength(3);
    expect(bar.querySelectorAll("[data-filled]")).toHaveLength(filled);
  });
});

describe("GapsList", () => {
  it("shows each Gap as a row with impact, category, title and the Draft pill", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <GapsList
          items={[gap(1, "high"), gap(2, "medium", "data_volumes"), gap(3, "low", "commercial")]}
        />
      </ShellProviders>,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toBe(
      "Open[GAP 1]HighIntegration detailsClarification Agent · Integration detailsDraft",
    );
    expect(rows[1].textContent).toBe(
      "Open[GAP 2]MediumData volumesClarification Agent · Data volumesDraft",
    );
    expect(rows[2].textContent).toBe(
      "Open[GAP 3]LowCommercialClarification Agent · CommercialDraft",
    );
    expect(within(rows[0]).getByRole("button").className).toContain("min-h-row");
    const tabStops = screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([row(1)]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("greys out converted Gaps at the bottom, labelled by what they became", async () => {
    const condition: Gap = { ...gap(2, "high"), status: "converted", converted_to: "condition" };
    const contingency: Gap = {
      ...gap(3, "low", "commercial"),
      status: "converted",
      converted_to: "contingency",
    };
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <GapsList items={[gap(1, "medium"), condition, contingency]} />
      </ShellProviders>,
    );
    const rows = screen.getAllByRole("row");
    expect(rows[0].textContent).toBe(
      "Open[GAP 1]MediumIntegration detailsClarification Agent · Integration detailsDraft",
    );
    expect(rows[0].hasAttribute("data-converted")).toBe(false);
    expect(rows[1].textContent).toBe(
      "Converted[GAP 2]HighIntegration detailsClarification Agent · Integration detailsConverted to Condition",
    );
    expect(rows[2].textContent).toBe(
      "Converted[GAP 3]LowCommercialClarification Agent · CommercialConverted to Contingency",
    );
    expect(rows[1].hasAttribute("data-converted")).toBe(true);
    expect(rows[1].className).toContain("text-muted-foreground");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrows move between rows; j/k are off with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <GapsList items={[gap(1, "high"), gap(2, "low")]} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <GapsList items={[gap(1, "high"), gap(2, "low")]} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
  });
});

describe("the inspector", () => {
  it("Enter opens the Gap in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([gap(1, "high"), gap(2, "low")], succeeded));

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", { level: 3, name: "[GAP 2]" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(row(2).closest('[role="row"]')?.getAttribute("aria-current")).toBe("true");
    expect(within(inspector).getByText("Integration details")).toBeTruthy();
    expect(within(inspector).getByText("[WHY 2]")).toBeTruthy();
    expect(within(inspector).getByText("Low")).toBeTruthy();
    expect(within(inspector).getByText("[BASIS 2]")).toBeTruthy();
    expect(within(inspector).getByText("R2")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 2]")).toBeTruthy();
    const question = within(inspector).getByRole("group", {
      name: "Clarification Question (read-only)",
    });
    expect(within(question).getByText("[QUESTION 2]")).toBeTruthy();
    expect(within(question).getByText("[TOPIC 2]")).toBeTruthy();
    expect(within(inspector).getByText("Draft")).toBeTruthy();
    const section = within(inspector).getByRole("region", { name: "[GAP 2]" });
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a click opens the Gap without moving focus into the pane", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded));

    await user.click(row(1));

    expect(within(pane()).getByRole("heading", { level: 3, name: "[GAP 1]" })).toBeTruthy();
    expect(document.activeElement).toBe(row(1));
  });
});

describe("DetectionStatus", () => {
  it.each([queued, running])("shows Detecting Gaps with a running dot while $status", (d) => {
    render(<DetectionStatus detection={d} canStart />);
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    const runningDot = screen.getByTestId("running-dot");
    expect(runningDot.tagName.toLowerCase()).toBe("svg");
    expect(runningDot.getAttribute("class") ?? "").toContain("lucide-loader-circle");
    expect(runningDot.getAttribute("class") ?? "").toContain("text-agent");
    expect(runningDot.getAttribute("class") ?? "").not.toContain("animate");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the failure reason and Retry for those who may start a detection", () => {
    render(<DetectionStatus detection={failed} canStart />);
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it.each([
    ["model_timeout", "the model took too long to answer"],
    ["output_invalid", "the model's answer couldn't be used"],
  ] as const)("names the %s reason", (code, reason) => {
    render(<DetectionStatus detection={{ status: "failed", error_code: code }} />);
    expect(screen.getByText(`Gap detection failed: ${reason}`)).toBeTruthy();
  });

  it("hides Retry from those who may not start one (sales representatives, readers)", () => {
    render(<DetectionStatus detection={failed} canStart={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<DetectionStatus detection={running} stalled />);
    expect(screen.getByText("Still detecting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("shows nothing once succeeded", () => {
    const { container } = render(<DetectionStatus detection={succeeded} canStart />);
    expect(container.textContent).toBe("");
  });
});

describe("GapsSection", () => {
  it("shows the empty sentence before any detection", () => {
    renderSection(list([], null));
    expect(screen.getByText("Gaps appear after Requirements are checked against Checklists.")).toBeTruthy();
    expect(screen.getByText("No Gaps")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Open Requirements" });
    expect(link.getAttribute("href")).toBe(`/opportunities/${OPP_ID}/requirements`);
  });

  it("says when a finished detection found no Gaps", () => {
    renderSection(list([], succeeded));
    expect(screen.getByText("No Gaps were found in the Requirements.")).toBeTruthy();
  });

  it("polls every 2 s while detecting, then shows the ranked Gaps", async () => {
    vi.useFakeTimers();
    loadGaps
      .mockResolvedValueOnce({ kind: "ok", list: list([], running) })
      .mockResolvedValue({ kind: "ok", list: list([gap(1, "high"), gap(2, "low")], succeeded) });
    renderSection(list([], queued));
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    expect(screen.queryByText("Gaps appear after Requirements are checked against Checklists.")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadGaps).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadGaps).toHaveBeenCalledWith(OPP_ID);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("[GAP 1]")).toBeTruthy();
    expect(screen.queryByText("Detecting Gaps")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(GAPS_FALLBACK_POLL_MS - 1);
    });
    // Detection polling stopped; only the slower fallback for the event stream remains.
    expect(loadGaps).toHaveBeenCalledTimes(2);
  });

  it("without a detection running, only the event stream fallback polls (Story 4.7)", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(1, "high")], succeeded) });
    renderSection(list([gap(1, "high")], succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(GAPS_FALLBACK_POLL_MS - 1);
    });
    expect(loadGaps).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadGaps).toHaveBeenCalledTimes(1);
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(list([], running));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadGaps).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadGaps).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadGaps).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadGaps.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadGaps).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
    expect(screen.getByText("Still detecting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("Retry starts a new detection, which then polls to done", async () => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue({ kind: "ok", detection: queued });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(1, "high")], succeeded) });
    const { container } = renderSection(list([], failed));
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(startGapDetection).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await waitFor(() => expect(screen.getByText("[GAP 1]")).toBeTruthy(), { timeout: 4000 });
  });

  it("a Retry answered 409 re-reads the tab", async () => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue({ kind: "conflict" });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Detecting Gaps")).toBeTruthy());
  });

  it.each([
    [{ kind: "error" } as const, "The retry failed. Try again."],
    [
      { kind: "forbidden" } as const,
      "Only the owner and collaborators, except sales representatives, can detect Gaps.",
    ],
  ])("a failed Retry says so and keeps the button (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue(result);
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a sales representative sees the same Gaps, read-only, and no Retry", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], failed, false));
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await user.click(row(1));

    expect(within(pane()).getByText("[QUESTION 1]")).toBeTruthy();
    expect(within(pane()).queryByRole("textbox")).toBeNull();
  });

  it("clears the inspector when a poll drops the selected Gap", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(2, "low")], succeeded) });
    renderSection(list([gap(1, "high")], running));
    act(() => {
      row(1).click();
    });
    expect(within(pane()).getByRole("heading", { level: 3, name: "[GAP 1]" })).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByText("[GAP 2]")).toBeTruthy();
    expect(within(pane()).queryByText("[GAP 1]")).toBeNull();
    expect(within(pane()).getByText("Select a gap or estimate line to see its details.")).toBeTruthy();
  });

  it("announces the open Gap count when a detection finishes", async () => {
    vi.useFakeTimers();
    const converted: Gap = { ...gap(3, "high"), status: "converted", converted_to: "condition" };
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list([gap(1, "high"), gap(2, "low"), converted], succeeded),
    });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("2 Gaps");
  });
});

// --- editing and approving questions (Story 4.5) ---------------------------------------------

const OWNER = { id: "00000000-0000-7000-8000-0000000000aa", name: "Owner Person" };

function approvedQuestion(q: ClarificationQuestion, version = q.row_version + 1) {
  return {
    ...q,
    status: "approved" as const,
    row_version: version,
    approved_by: OWNER,
    approved_at: "2026-10-05T11:00:00Z",
    status_changed_at: "2026-10-05T11:00:00Z",
    last_changed_by: OWNER,
  };
}

function approvedGap(n: number, impact: Impact): Gap {
  const base = gap(n, impact);
  return { ...base, question: approvedQuestion(base.question!) };
}

async function openRow(user: ReturnType<typeof userEvent.setup>, n: number) {
  await user.click(row(n));
  return pane();
}

describe("question pills", () => {
  it("rows and the inspector show Draft or Approved, with the date of the last change", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([approvedGap(1, "high"), gap(2, "low")], succeeded));
    const rows = screen.getAllByRole("row");
    expect(rows[0].textContent).toBe("Open[GAP 1]HighIntegration detailsClarification Agent · Integration detailsApproved");
    expect(rows[1].textContent).toBe("Open[GAP 2]LowIntegration detailsClarification Agent · Integration detailsDraft");
    expect(rows[0].querySelector("[data-question-status] svg")).toBeTruthy(); // icon plus label

    const inspector = await openRow(user, 1);

    expect(within(inspector).getByText("Approved since 5 Oct 2026")).toBeTruthy();
    expect(within(inspector).getByText("Approved by Owner Person, 5 Oct 2026")).toBeTruthy();
    expect(within(inspector).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("editing questions", () => {
  it("edits the question text inline: Enter saves with If-Match, the new text shows", async () => {
    const user = userEvent.setup();
    const saved = { ...gap(1, "high").question!, text: "[NEW TEXT]", row_version: 2 };
    editClarificationQuestion.mockResolvedValue({ kind: "ok", question: saved });
    const { container } = renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(inspector).getByRole("button", { name: "Edit question" }));
    const input = within(inspector).getByRole("textbox", { name: "Question" });
    expect(document.activeElement).toBe(input);
    await user.clear(input);
    await user.type(input, "  [[NEW TEXT]  {Enter}");

    expect(editClarificationQuestion).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      questionId: gap(1, "high").question!.id,
      rowVersion: 1,
      text: "[NEW TEXT]",
    });
    expect(await within(inspector).findByText("[NEW TEXT]")).toBeTruthy();
    expect(document.activeElement).toBe(
      within(inspector).getByRole("button", { name: "Edit question" }),
    );
  });

  it("edits the topic; Esc reverts without saving; an unchanged value sends nothing", async () => {
    const user = userEvent.setup();
    const saved = { ...gap(1, "high").question!, topic: "[NEW TOPIC]", row_version: 2 };
    editClarificationQuestion.mockResolvedValue({ kind: "ok", question: saved });
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Edit question" }));
    await user.type(within(inspector).getByRole("textbox", { name: "Question" }), "more{Escape}");
    await user.click(within(inspector).getByRole("button", { name: "Edit topic" }));
    await user.keyboard("{Enter}");
    expect(editClarificationQuestion).not.toHaveBeenCalled();
    expect(within(inspector).getByText("[QUESTION 1]")).toBeTruthy();

    await user.click(within(inspector).getByRole("button", { name: "Edit topic" }));
    const topic = within(inspector).getByRole("textbox", { name: "Topic" });
    await user.clear(topic);
    await user.type(topic, "[[NEW TOPIC]{Enter}");

    expect(editClarificationQuestion).toHaveBeenCalledWith(
      expect.objectContaining({ topic: "[NEW TOPIC]", rowVersion: 1 }),
    );
    await waitFor(() => expect(within(inspector).getByText("[NEW TOPIC]")).toBeTruthy());
  });

  it("refuses a too-long topic before sending, keeping the text under the field", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Edit topic" }));
    const topic = within(inspector).getByRole("textbox", { name: "Topic" });
    await user.clear(topic);
    await user.paste("t".repeat(81));
    await user.keyboard("{Enter}");

    expect(editClarificationQuestion).not.toHaveBeenCalled();
    expect(within(inspector).getByText("The topic can be at most 80 characters.")).toBeTruthy();
  });

  it("a 412 says who changed it, keeps the text, and Reload re-reads the Gaps", async () => {
    const user = userEvent.setup();
    editClarificationQuestion.mockResolvedValue({ kind: "stale", changedBy: "Colleague" });
    const newer = { ...gap(1, "high").question!, text: "[THEIR TEXT]", row_version: 2 };
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list([{ ...gap(1, "high"), question: newer }], succeeded, true, true),
    });
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Edit question" }));
    const input = within(inspector).getByRole("textbox", { name: "Question" });
    await user.clear(input);
    await user.type(input, "[[MY TEXT]{Enter}");

    const reload = await screen.findByRole("button", { name: "Reload" });
    // The stale message is an inline alert with Reload only (no diff on Gaps).
    expect(screen.getByRole("alert").textContent).toContain("Changed by Colleague");
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
    expect(screen.getAllByText("Changed by Colleague since you opened it.").length).toBeGreaterThan(
      0,
    );
    expect(within(inspector).getByText("[QUESTION 1]")).toBeTruthy(); // rolled back
    await waitFor(() => expect(document.activeElement).toBe(reload));

    await user.click(reload);

    await waitFor(() => expect(screen.queryByRole("button", { name: "Reload" })).toBeNull());
    expect(loadGaps).toHaveBeenCalledWith(OPP_ID);
    expect(within(pane()).getByText("[THEIR TEXT]")).toBeTruthy();
    // The field still offers the user's text to save again.
    await user.click(within(pane()).getByRole("button", { name: "Edit question" }));
    expect(
      (within(pane()).getByRole("textbox", { name: "Question" }) as HTMLTextAreaElement).value,
    ).toBe("[MY TEXT]");
  });

  it("a 409 says the Gap is no longer open and re-reads the Gaps", async () => {
    const user = userEvent.setup();
    approveClarificationQuestion.mockResolvedValue({ kind: "gap-not-open" });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], succeeded, true, true) });
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText(
        "This Gap is no longer open: it was dismissed, converted or replaced by a newer Gap detection.",
      ),
    ).toBeTruthy();
    expect(loadGaps).toHaveBeenCalled();
  });

  it("a 409 question_not_editable says the question was sent and re-reads the Gaps", async () => {
    const user = userEvent.setup();
    editClarificationQuestion.mockResolvedValue({ kind: "question-not-editable" });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([sentGap(1, "high")], succeeded, true, true) });
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Edit question" }));
    const input = within(inspector).getByRole("textbox", { name: "Question" });
    await user.clear(input);
    await user.type(input, "Other wording{Enter}");

    expect(
      await screen.findByText(
        "This Clarification Question was sent: it can no longer be edited or approved.",
        { selector: "p" },
      ),
    ).toBeTruthy();
    expect(loadGaps).toHaveBeenCalled();
  });

  it("e on a row opens the inspector with the question text being edited", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high"), gap(2, "low")], succeeded, true, true));

    act(() => row(1).focus());
    await user.keyboard("j");
    await user.keyboard("e");

    const input = within(pane()).getByRole("textbox", { name: "Question" });
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect((input as HTMLTextAreaElement).value).toBe("[QUESTION 2]");
  });

  it("e does nothing for those who may not edit", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded, false, false));

    act(() => row(1).focus());
    await user.keyboard("e");

    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("approving questions", () => {
  it("Approve approves a drafted question and shows who approved it", async () => {
    const user = userEvent.setup();
    approveClarificationQuestion.mockResolvedValue({
      kind: "ok",
      question: approvedQuestion(gap(1, "high").question!),
    });
    const { container } = renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Approve" }));

    expect(approveClarificationQuestion).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      questionId: gap(1, "high").question!.id,
      rowVersion: 1,
    });
    expect(
      await within(inspector).findByText("Approved by Owner Person, 5 Oct 2026"),
    ).toBeTruthy();
    expect(screen.getAllByRole("row")[0].textContent).toBe(
      "Open[GAP 1]HighIntegration detailsClarification Agent · Integration detailsApproved",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Approve all (N) counts the drafted questions of open Gaps and re-reads after", async () => {
    const user = userEvent.setup();
    const converted: Gap = { ...gap(3, "low"), status: "converted", converted_to: "condition" };
    approveAllClarificationQuestions.mockResolvedValue({ kind: "ok", count: 2 });
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list(
        [approvedGap(1, "high"), approvedGap(2, "medium"), approvedGap(4, "low"), converted],
        succeeded,
        true,
        true,
      ),
    });
    renderSection(
      list(
        [gap(1, "high"), gap(2, "medium"), approvedGap(4, "low"), converted],
        succeeded,
        true,
        true,
      ),
    );

    await user.click(screen.getByRole("button", { name: "Approve all (2)" }));

    expect(approveAllClarificationQuestions).toHaveBeenCalledWith(OPP_ID, [
      { id: gap(1, "high").question!.id, row_version: 1 },
      { id: gap(2, "medium").question!.id, row_version: 1 },
    ]);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Approve all/ })).toBeNull(),
    );
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("2 questions approved"),
    );
    expect(screen.getAllByRole("row")[1].textContent).toBe(
      "Open[GAP 2]MediumIntegration detailsClarification Agent · Integration detailsApproved",
    );
  });

  it("a 412 on Approve all says who changed it and offers Reload", async () => {
    const user = userEvent.setup();
    approveAllClarificationQuestions.mockResolvedValue({ kind: "stale", changedBy: "Colleague" });
    renderSection(list([gap(1, "high")], succeeded, true, true));

    await user.click(screen.getByRole("button", { name: "Approve all (1)" }));

    const reload = await screen.findByRole("button", { name: "Reload" });
    expect(screen.getByText("Changed by Colleague since you opened it.", { selector: "p" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(reload));
    expect(screen.getAllByRole("row")[0].textContent).toBe("Open[GAP 1]HighIntegration detailsClarification Agent · Integration detailsDraft");
  });

  it("if the re-read after Approve all fails, offers Reload straight away", async () => {
    const user = userEvent.setup();
    approveAllClarificationQuestions.mockResolvedValue({ kind: "ok", count: 1 });
    loadGaps.mockResolvedValue({ kind: "error" });
    renderSection(list([gap(1, "high")], succeeded, true, true));

    await user.click(screen.getByRole("button", { name: "Approve all (1)" }));

    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.getByText("Changed by someone else since you opened it.")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("1 question approved"),
    );
  });

  it("hides Approve all from those who may not edit", () => {
    renderSection(list([gap(1, "high")], succeeded, false, false));
    expect(screen.queryByRole("button", { name: /Approve all/ })).toBeNull();
  });
});

describe("a sales representative", () => {
  it("sees Gaps without unapproved questions, and approved ones read-only", async () => {
    const user = userEvent.setup();
    const hidden: Gap = { ...gap(2, "low"), question: null };
    const { container } = renderSection(
      list([approvedGap(1, "high"), hidden], succeeded, false, false),
    );
    const rows = screen.getAllByRole("row");
    expect(rows[0].textContent).toBe("Open[GAP 1]HighIntegration detailsClarification Agent · Integration detailsApproved");
    expect(rows[1].textContent).toBe("Open[GAP 2]LowIntegration detailsClarification Agent · Integration details");

    const inspector = await openRow(user, 1);
    expect(
      within(inspector).getByRole("group", { name: "Clarification Question (read-only)" }),
    ).toBeTruthy();
    const section = within(inspector).getByRole("region", { name: "[GAP 1]" });
    expect(within(section).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(row(2));
    expect(within(pane()).queryByText("Clarification Question")).toBeNull();
  });
});

// --- Story 4.4: status icons, multi-select, impact change, dismiss, reopen, history ------------

function historyEntry(
  kind: GapHistoryEntry["kind"],
  extra: Partial<GapHistoryEntry> = {},
): GapHistoryEntry {
  return {
    kind,
    at: "2026-10-14T10:00:00Z",
    actor: OWNER,
    old_impact: null,
    new_impact: null,
    reason_kind: null,
    reason: null,
    ...extra,
  };
}

function dismissedGap(n: number, impact: Impact, note: string | null = null): Gap {
  const base = gap(n, impact);
  return {
    ...base,
    status: "dismissed",
    row_version: 2,
    dismissal: {
      reason_kind: note ? "other" : "not_relevant",
      note,
      by: OWNER,
      at: "2026-10-14T10:00:00Z",
    },
    history: [
      ...base.history,
      historyEntry("dismissed", {
        reason_kind: note ? "other" : "not_relevant",
        reason: note,
      }),
    ],
    last_changed_by: OWNER,
  };
}

describe("Gap status, groups and the header (Story 4.4)", () => {
  it("greys dismissed Gaps at the bottom, keeps their keys, and labels each status", async () => {
    const user = userEvent.setup();
    const converted: Gap = { ...gap(2, "high"), status: "converted", converted_to: "condition" };
    const { container } = renderSection(
      list([gap(1, "low"), converted, dismissedGap(3, "high")], succeeded),
    );

    expect(screen.getByText("3 Gaps · 1 open · ranked by impact")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    expect(rows[2].textContent).toBe(
      "Dismissed[GAP 3]HighIntegration detailsClarification Agent · Integration detailsDismissed · Not relevant",
    );
    expect(rows[2].hasAttribute("data-dismissed")).toBe(true);
    expect(rows[2].className).toContain("text-muted-foreground");
    await user.tab();
    await user.keyboard("jj");
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("{Enter}");
    const inspector = pane();
    expect(
      within(inspector).getByText("Dismissed · Not relevant · Owner Person, 14 Oct 2026"),
    ).toBeTruthy();
    // Read-only for those who may not change Gaps: no Reopen, but the history shows.
    expect(within(inspector).queryByRole("form", { name: "Reopen the Gap" })).toBeNull();
    const history = within(inspector).getByRole("list", { name: "Gap history" });
    expect(within(history).getByText("Raised by Clarification Agent")).toBeTruthy();
    expect(within(history).getByText("Dismissed: Not relevant")).toBeTruthy();
    expect(within(history).getByText("Owner Person, 14 Oct 2026")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the key hints under the list", () => {
    renderSection(list([gap(1, "high")], succeeded, true, true));
    for (const hint of ["move", "select", "open", "edit question"]) {
      expect(screen.getByText(hint)).toBeTruthy();
    }
  });
});

describe("multi-select (Story 4.4)", () => {
  it("x selects rows and Approve N selected approves exactly those", async () => {
    const user = userEvent.setup();
    approveSelectedClarificationQuestions.mockResolvedValue({ kind: "ok", count: 2 });
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list(
        [approvedGap(1, "high"), approvedGap(2, "medium"), gap(3, "low"), gap(4, "low")],
        succeeded,
        true,
        true,
      ),
    });
    const { container } = renderSection(
      list([gap(1, "high"), gap(2, "medium"), gap(3, "low"), gap(4, "low")], succeeded, true, true),
    );
    expect(screen.getByRole("button", { name: "Approve all (4)" })).toBeTruthy();

    row(1).focus();
    await user.keyboard("x");
    await user.keyboard("j");
    await user.keyboard("x");

    const rows = screen.getAllByRole("row");
    expect(rows.map((r) => r.getAttribute("aria-selected"))).toEqual([
      "true",
      "true",
      "false",
      "false",
    ]);
    expect(screen.getByRole("grid").getAttribute("aria-multiselectable")).toBe("true");
    expect(screen.queryByRole("button", { name: /Approve all/ })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Approve 2 selected" }));

    expect(approveSelectedClarificationQuestions).toHaveBeenCalledWith(OPP_ID, [
      { id: gap(1, "high").question!.id, row_version: 1 },
      { id: gap(2, "medium").question!.id, row_version: 1 },
    ]);
    await waitFor(() => expect(screen.getAllByRole("row")[0].textContent).toContain("Approved"));
    expect(loadGaps).toHaveBeenCalled();
    expect(screen.getAllByRole("row")[2].textContent).toContain("Draft");
    expect(screen.getByRole("button", { name: "Approve all (2)" })).toBeTruthy();
    expect(screen.getAllByRole("row").map((r) => r.getAttribute("aria-selected"))).toEqual([
      "false",
      "false",
      "false",
      "false",
    ]);
  });

  it("the checkbox toggles a row; Esc clears the selection while the inspector is closed", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high"), gap(2, "low")], succeeded, true, true));

    await user.click(screen.getByRole("checkbox", { name: "Select [GAP 2]" }));
    expect(screen.getByRole("button", { name: "Approve 1 selected" })).toBeTruthy();
    row(1).focus();
    await user.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: "Approve all (2)" })).toBeTruthy();
    expect(screen.getAllByRole("row").map((r) => r.getAttribute("aria-selected"))).toEqual([
      "false",
      "false",
    ]);
  });

  it("a 412 on Approve N selected approves nothing and offers Reload", async () => {
    const user = userEvent.setup();
    approveSelectedClarificationQuestions.mockResolvedValue({
      kind: "stale",
      changedBy: "Colleague",
    });
    renderSection(list([gap(1, "high"), gap(2, "low")], succeeded, true, true));

    await user.click(screen.getByRole("checkbox", { name: "Select [GAP 1]" }));
    await user.click(screen.getByRole("button", { name: "Approve 1 selected" }));

    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.getByText("Changed by Colleague since you opened it.", { selector: "p" })).toBeTruthy();
  });

  it("no selection for those who may not approve questions", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded, true, false));
    expect(screen.queryByRole("checkbox")).toBeNull();
    row(1).focus();
    await user.keyboard("x");
    expect(screen.getAllByRole("row")[0].hasAttribute("aria-selected")).toBe(false);
  });
});

describe("changing, dismissing and reopening Gaps (Story 4.4)", () => {
  it("changes the impact with a required reason and re-ranks the list", async () => {
    const user = userEvent.setup();
    const lowered: Gap = {
      ...gap(1, "low"),
      row_version: 2,
      history: [
        ...gap(1, "low").history,
        historyEntry("impact_changed", {
          old_impact: "high",
          new_impact: "low",
          reason: "Lower risk",
        }),
      ],
      last_changed_by: OWNER,
    };
    changeGapImpact.mockResolvedValue({ kind: "ok", gap: lowered });
    const { container } = renderSection(
      list([gap(1, "high"), gap(2, "medium")], succeeded, true, true),
    );
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Change impact" });

    // The same impact sends nothing and keeps the reason.
    const reasonField = within(form).getByLabelText("Reason for the change");
    await user.type(reasonField, "Same");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByText("Choose a different impact.")).toBeTruthy();
    expect((reasonField as HTMLTextAreaElement).value).toBe("Same");
    expect(changeGapImpact).not.toHaveBeenCalled();
    await user.clear(reasonField);

    await user.selectOptions(within(form).getByLabelText("New impact"), "low");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(within(form).getByText("Give a reason.")).toBeTruthy();
    expect(changeGapImpact).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(within(form).getByLabelText("Reason for the change"), "Lower risk");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(changeGapImpact).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      gapId: gap(1, "high").id,
      rowVersion: 1,
      impact: "low",
      reason: "Lower risk",
    });
    await waitFor(() =>
      expect(screen.getAllByRole("row").map((r) => r.textContent?.slice(0, 11))).toEqual([
        "Open[GAP 2]",
        "Open[GAP 1]",
      ]),
    );
    const history = within(pane()).getByRole("list", { name: "Gap history" });
    expect(within(history).getByText("Impact changed from High to Low")).toBeTruthy();
    expect(within(history).getByText("Lower risk")).toBeTruthy();
  });

  it("dismisses as Other only with a note, then shows it greyed last with Reopen", async () => {
    const user = userEvent.setup();
    dismissGap.mockResolvedValue({ kind: "ok", gap: dismissedGap(1, "high", "Covered elsewhere") });
    const { container } = renderSection(
      list([gap(1, "high"), gap(2, "low")], succeeded, true, true),
    );
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Dismiss the Gap" });

    await user.click(within(form).getByRole("radio", { name: "Other" }));
    await user.click(within(form).getByRole("button", { name: "Dismiss" }));
    expect(within(form).getByText(/a note is needed/)).toBeTruthy();
    expect(dismissGap).not.toHaveBeenCalled();

    await user.type(within(form).getByLabelText("Note"), "Covered elsewhere");
    await user.click(within(form).getByRole("button", { name: "Dismiss" }));

    expect(dismissGap).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      gapId: gap(1, "high").id,
      rowVersion: 1,
      reasonKind: "other",
      note: "Covered elsewhere",
    });
    await waitFor(() =>
      expect(screen.getAllByRole("row")[1].hasAttribute("data-dismissed")).toBe(true),
    );
    expect(screen.getByText("2 Gaps · 1 open · ranked by impact")).toBeTruthy();
    const updated = pane();
    expect(
      within(updated).getByText("Dismissed · Other · Owner Person, 14 Oct 2026"),
    ).toBeTruthy();
    expect(within(updated).getByRole("form", { name: "Reopen the Gap" })).toBeTruthy();
    expect(within(updated).queryByRole("form", { name: "Dismiss the Gap" })).toBeNull();
    expect(within(updated).queryByRole("form", { name: "Change impact" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("dismisses as Not relevant without a note", async () => {
    const user = userEvent.setup();
    dismissGap.mockResolvedValue({ kind: "ok", gap: dismissedGap(1, "high") });
    renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Dismiss the Gap" });

    await user.click(within(form).getByRole("button", { name: "Dismiss" }));

    expect(dismissGap).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      gapId: gap(1, "high").id,
      rowVersion: 1,
      reasonKind: "not_relevant",
    });
  });

  it("reopens a dismissed Gap with a reason", async () => {
    const user = userEvent.setup();
    const reopened: Gap = {
      ...gap(1, "high"),
      row_version: 3,
      history: [
        ...dismissedGap(1, "high").history,
        historyEntry("reopened", { reason: "Customer asked again" }),
      ],
    };
    reopenGap.mockResolvedValue({ kind: "ok", gap: reopened });
    renderSection(list([gap(2, "low"), dismissedGap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Reopen the Gap" });

    await user.click(within(form).getByRole("button", { name: "Reopen" }));
    expect(within(form).getByText("Give a reason.")).toBeTruthy();
    await user.type(within(form).getByLabelText("Reason for reopening"), "Customer asked again");
    await user.click(within(form).getByRole("button", { name: "Reopen" }));

    expect(reopenGap).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      gapId: gap(1, "high").id,
      rowVersion: 2,
      reason: "Customer asked again",
    });
    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].textContent?.slice(0, 11)).toBe("Open[GAP 1]"),
    );
    const history = within(pane()).getByRole("list", { name: "Gap history" });
    expect(within(history).getByText("Reopened")).toBeTruthy();
  });

  it("a 412 on a Gap write says who changed it and offers Reload; nothing is overwritten", async () => {
    const user = userEvent.setup();
    dismissGap.mockResolvedValue({ kind: "stale", changedBy: "Colleague" });
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list([dismissedGap(1, "high")], succeeded, true, true),
    });
    const { container } = renderSection(list([gap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Dismiss" }));

    const reload = await screen.findByRole("button", { name: "Reload" });
    expect(screen.getByText("Changed by Colleague since you opened it.", { selector: "p" })).toBeTruthy();
    expect(screen.getAllByRole("row")[0].hasAttribute("data-dismissed")).toBe(false);
    expect(await axeViolations(container)).toEqual([]);
    await user.click(reload);
    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].hasAttribute("data-dismissed")).toBe(true),
    );
  });

  it("a 409 on reopen says the Gap is no longer dismissed and re-reads", async () => {
    const user = userEvent.setup();
    reopenGap.mockResolvedValue({ kind: "gap-not-reopenable" });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(1, "high")], succeeded, true, true) });
    renderSection(list([dismissedGap(1, "high")], succeeded, true, true));
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Reopen the Gap" });

    await user.type(within(form).getByLabelText("Reason for reopening"), "x");
    await user.click(within(form).getByRole("button", { name: "Reopen" }));

    expect(
      await screen.findByText("This Gap is no longer dismissed or answered: someone reopened it."),
    ).toBeTruthy();
    expect(loadGaps).toHaveBeenCalled();
  });

  it("those who may not change Gaps see no impact, dismiss or reopen controls", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded, true, true, false));
    const inspector = await openRow(user, 1);
    expect(within(inspector).queryByRole("form", { name: "Change impact" })).toBeNull();
    expect(within(inspector).queryByRole("form", { name: "Dismiss the Gap" })).toBeNull();
    expect(within(inspector).getByRole("list", { name: "Gap history" })).toBeTruthy();
  });
});

// --- exporting and sending questions (Story 4.6) ---------------------------------------------

const REP = { id: "00000000-0000-7000-8000-0000000000e2", name: "Rep Person" };

function sentQuestion(q: ClarificationQuestion, status: "sent" | "unanswered" = "sent") {
  return {
    ...approvedQuestion(q),
    status,
    row_version: q.row_version + 2,
    sent_on: "2026-10-14",
    sent_by: REP,
    status_changed_at: "2026-10-14T09:00:00Z",
    last_changed_by: REP,
  };
}

function sentGap(n: number, impact: Impact, status: "sent" | "unanswered" = "sent"): Gap {
  const base = gap(n, impact);
  return { ...base, question: sentQuestion(base.question!, status) };
}

/** A sales representative's list: may send, may not edit. */
function repList(items: Gap[]): GapList {
  return list(items, succeeded, false, false, false, true);
}

describe("exporting and sending questions (Story 4.6)", () => {
  it("pills show Sent and No answer with icons; the inspector says when and by whom", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(
      repList([sentGap(1, "high"), sentGap(2, "medium", "unanswered")]),
    );
    const rows = screen.getAllByRole("row");
    expect(rows[0].textContent).toContain("Sent");
    expect(rows[1].textContent).toContain("No answer");
    expect(rows[0].querySelector('[data-question-status="sent"] svg')).toBeTruthy();
    expect(rows[1].querySelector('[data-question-status="unanswered"] svg')).toBeTruthy();

    const inspector = await openRow(user, 1);

    expect(within(inspector).getByText("Sent 14 Oct 2026 by Rep Person")).toBeTruthy();
    expect(within(inspector).getByText("Approved by Owner Person, 5 Oct 2026")).toBeTruthy();
    expect(within(inspector).getByRole("button", { name: "No answer" })).toBeTruthy();
    expect(within(inspector).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a sent question is read-only even for editors, and e does not edit it", async () => {
    const user = userEvent.setup();
    renderSection(list([sentGap(1, "high")], succeeded, true, true, true, true));

    row(1).focus();
    await user.keyboard("e");
    const inspector = await openRow(user, 1);

    expect(within(inspector).getByRole("group", { name: "Clarification Question (read-only)" }))
      .toBeTruthy();
    expect(within(inspector).queryByRole("button", { name: "Edit question" })).toBeNull();
    expect(within(inspector).queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("Mark all sent (N) opens a date form (today by default) and marks the shown questions", async () => {
    const user = userEvent.setup();
    markClarificationQuestionsSent.mockResolvedValue({ kind: "ok", count: 2 });
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: repList([sentGap(1, "high"), sentGap(2, "medium"), gap(3, "low")]),
    });
    const { container } = renderSection(
      repList([approvedGap(1, "high"), approvedGap(2, "medium"), gap(3, "low")]),
    );
    expect(screen.queryByRole("button", { name: /^Approve (all|[0-9])/ })).toBeNull(); // a rep

    await user.click(screen.getByRole("button", { name: "Mark all sent (2)" }));
    const form = screen.getByRole("form", { name: "Mark questions sent" });
    const date = within(form).getByLabelText("Date sent") as HTMLInputElement;
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    expect(date.value).toBe(today);
    expect(date.max).toBe(today);
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(form).getByRole("button", { name: "Mark 2 sent" }));

    expect(markClarificationQuestionsSent).toHaveBeenCalledWith(OPP_ID, today, [
      { id: gap(1, "high").question!.id, row_version: 2 },
      { id: gap(2, "medium").question!.id, row_version: 2 },
    ]);
    await waitFor(() => expect(screen.getAllByRole("row")[0].textContent).toContain("Sent"));
    expect(screen.queryByRole("form", { name: "Mark questions sent" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Mark all sent/ })).toBeNull();
  });

  it("x selects approved questions and Mark N selected sent marks exactly those", async () => {
    const user = userEvent.setup();
    markClarificationQuestionsSent.mockResolvedValue({ kind: "ok", count: 1 });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([approvedGap(1, "high")]) });
    renderSection(repList([approvedGap(1, "high"), approvedGap(2, "low")]));

    row(2).focus();
    await user.keyboard("x");
    await user.click(screen.getByRole("button", { name: "Mark 1 selected sent" }));
    const form = screen.getByRole("form", { name: "Mark questions sent" });
    await user.click(within(form).getByRole("button", { name: "Mark 1 sent" }));

    expect(markClarificationQuestionsSent).toHaveBeenCalledWith(OPP_ID, expect.any(String), [
      { id: gap(2, "low").question!.id, row_version: 2 },
    ]);
  });

  it("refuses a future date before sending, and shows a 422 under the date", async () => {
    const user = userEvent.setup();
    markClarificationQuestionsSent.mockResolvedValue({
      kind: "invalid",
      detail: "The date sent can't be in the future.",
    });
    renderSection(repList([approvedGap(1, "high")]));
    await user.click(screen.getByRole("button", { name: "Mark all sent (1)" }));
    const form = screen.getByRole("form", { name: "Mark questions sent" });
    const date = within(form).getByLabelText("Date sent");

    await user.clear(date);
    await user.type(date, "2999-01-01");
    await user.click(within(form).getByRole("button", { name: "Mark 1 sent" }));
    expect(within(form).getByText("The date sent can't be in the future.")).toBeTruthy();
    expect(markClarificationQuestionsSent).not.toHaveBeenCalled();

    await user.clear(date);
    await user.type(date, "2026-10-01");
    await user.click(within(form).getByRole("button", { name: "Mark 1 sent" }));
    expect(markClarificationQuestionsSent).toHaveBeenCalledTimes(1);
    expect(await within(form).findByText("The date sent can't be in the future.")).toBeTruthy();
  });

  it("a 412 on Mark sent marks nothing and offers Reload", async () => {
    const user = userEvent.setup();
    markClarificationQuestionsSent.mockResolvedValue({ kind: "stale", changedBy: "Colleague" });
    const { container } = renderSection(repList([approvedGap(1, "high")]));

    await user.click(screen.getByRole("button", { name: "Mark all sent (1)" }));
    await user.click(screen.getByRole("button", { name: "Mark 1 sent" }));

    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.getByText("Changed by Colleague since you opened it.", { selector: "p" })).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Mark questions sent" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the inspector marks one approved question sent", async () => {
    const user = userEvent.setup();
    markClarificationQuestionsSent.mockResolvedValue({ kind: "ok", count: 1 });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([sentGap(1, "high")]) });
    renderSection(repList([approvedGap(1, "high"), approvedGap(2, "low")]));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Mark sent" }));
    const form = within(inspector).getByRole("form", { name: "Mark this question sent" });
    await user.click(within(form).getByRole("button", { name: "Mark sent" }));

    expect(markClarificationQuestionsSent).toHaveBeenCalledWith(OPP_ID, expect.any(String), [
      { id: gap(1, "high").question!.id, row_version: 2 },
    ]);
    expect(await within(pane()).findByText("Sent 14 Oct 2026 by Rep Person")).toBeTruthy();
  });

  it("No answer marks a sent question and keeps the Gap open", async () => {
    const user = userEvent.setup();
    const sent = sentGap(1, "high");
    markClarificationQuestionUnanswered.mockResolvedValue({
      kind: "ok",
      question: { ...sent.question!, status: "unanswered", row_version: 4 },
    });
    renderSection(repList([sent]));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "No answer" }));

    expect(markClarificationQuestionUnanswered).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      questionId: sent.question!.id,
      rowVersion: 3,
    });
    await waitFor(() => expect(screen.getAllByRole("row")[0].textContent).toContain("No answer"));
    expect(screen.getAllByRole("row")[0].textContent).toContain("Open");
    expect(within(pane()).queryByRole("button", { name: "No answer" })).toBeNull();
  });

  it("a 409 on No answer says the question is no longer sent and re-reads", async () => {
    const user = userEvent.setup();
    markClarificationQuestionUnanswered.mockResolvedValue({ kind: "question-not-sent" });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([sentGap(1, "high", "unanswered")]) });
    renderSection(repList([sentGap(1, "high")]));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "No answer" }));

    expect(
      await screen.findByText("This Clarification Question is no longer sent."),
    ).toBeTruthy();
    expect(loadGaps).toHaveBeenCalled();
  });

  it("Export copies the approved questions and announces how many", async () => {
    const user = userEvent.setup();
    copyClarificationQuestions.mockResolvedValue({ kind: "ok", text: "[EXPORT TEXT]", count: 2 });
    const { container } = renderSection(repList([approvedGap(1, "high"), approvedGap(2, "low")]));

    await user.click(screen.getByRole("button", { name: "Export" }));
    const menu = screen.getByRole("group", { name: "Export questions as" });
    expect(within(menu).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Copy",
      "Word (.docx)",
      "Email draft (.eml)",
    ]);
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(menu).getByRole("button", { name: "Copy" }));

    expect(copyClarificationQuestions).toHaveBeenCalledWith(OPP_ID);
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe("[EXPORT TEXT]"));
    await waitFor(() => expect(screen.getByText("2 questions copied")).toBeTruthy());
  });

  it("Export downloads the email draft through the web route", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async () =>
      new Response("draft", {
        status: 200,
        headers: {
          "Content-Type": "message/rfc822",
          "Content-Disposition": 'attachment; filename="clarification-questions-x.eml"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:x");
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = vi.fn();
    try {
      renderSection(repList([approvedGap(1, "high")]));
      await user.click(screen.getByRole("button", { name: "Export" }));
      await user.click(screen.getByRole("button", { name: "Email draft (.eml)" }));

      await waitFor(() =>
        expect(screen.getByText("Exported clarification-questions-x.eml")).toBeTruthy(),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/opportunities/${OPP_ID}/questions-export?format=eml`,
        { method: "POST", credentials: "same-origin" },
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("no Export or Mark sent without approved questions, or for those who may not send", () => {
    const { unmount } = renderSection(repList([gap(1, "high")]));
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Mark all sent/ })).toBeNull();
    unmount();
    renderSection(list([approvedGap(1, "high")], succeeded, false, false, false, false));
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Mark all sent/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

// --- answering questions (Story 4.7) ----------------------------------------------------------

const PASSAGE = {
  passage_id: "00000000-0000-7000-8000-0000000000c1",
  source_id: "00000000-0000-7000-8000-0000000000c2",
  source_version: 1,
  filename: "reply.txt",
  label: "S2 · reply.txt",
  excerpt: "Our uptime window is 06:00 to 22:00.",
};
const R1_ID = "00000000-0000-7000-8000-0000000000d1";

function answeredGap(n: number, settles = true): Gap {
  const base = sentGap(n, "high");
  return {
    ...base,
    status: settles ? "answered" : "open",
    row_version: base.row_version + 1,
    question: {
      ...base.question!,
      status: "answered",
      row_version: base.question!.row_version + 1,
      answered_on: "2026-10-12",
      answered_by: REP,
    },
    answer: {
      answered_on: "2026-10-12",
      answered_by: REP,
      passage: PASSAGE,
      requirement_changes: [{ requirement_id: R1_ID, label: "R1", kind: "pending" }],
    },
  };
}

function suggestedGap(n: number, injection = false): Gap {
  const base = sentGap(n, "high");
  return {
    ...base,
    answer_suggestions: [
      {
        id: `00000000-0000-7000-8000-00000000${String(n).padStart(4, "0")}`,
        question_id: base.question!.id,
        passage: PASSAGE,
        injection_suspected: injection,
        row_version: 1,
        created_at: "2026-10-14T09:00:00Z",
      },
    ],
  };
}

const ANSWER_FORM = "Record the customer’s answer";
const ANSWER_FIELD = "Customer’s answer";

describe("answering questions (Story 4.7)", () => {
  it("Record answer sends the text, date and settles flag, and shows the Answered Gap", async () => {
    const user = userEvent.setup();
    recordAnswer.mockResolvedValue({ kind: "ok", gap: answeredGap(1) });
    const { container } = renderSection(repList([sentGap(1, "high")]));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Record answer" }));
    const form = within(inspector).getByRole("form", { name: ANSWER_FORM });
    expect(within(form).getByRole("checkbox")).toHaveProperty("checked", true);
    expect(await axeViolations(container)).toEqual([]);
    await user.type(within(form).getByLabelText(ANSWER_FIELD), "  Weekdays 06:00-22:00 ");
    await user.click(within(form).getByRole("button", { name: "Record answer" }));

    expect(recordAnswer).toHaveBeenCalledWith(
      expect.objectContaining({
        opportunityId: OPP_ID,
        questionId: sentGap(1, "high").question!.id,
        rowVersion: 3,
        text: "Weekdays 06:00-22:00",
        settlesGap: true,
      }),
    );
    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].textContent).toContain("Answered by customer, 12 Oct"),
    );
    expect(
      screen.getAllByRole("row")[0].querySelector('[data-question-status="answered"]'),
    ).toBeTruthy();
    expect(within(pane()).getAllByText("Answered by customer, 12 Oct").length).toBeGreaterThan(0);
  });

  it("unticking the checkbox sends settlesGap false; an empty or future answer is refused", async () => {
    const user = userEvent.setup();
    recordAnswer.mockResolvedValue({ kind: "ok", gap: answeredGap(1, false) });
    renderSection(repList([sentGap(1, "high")]));
    const inspector = await openRow(user, 1);
    await user.click(within(inspector).getByRole("button", { name: "Record answer" }));
    const form = within(inspector).getByRole("form", { name: ANSWER_FORM });

    await user.click(within(form).getByRole("button", { name: "Record answer" }));
    expect(within(form).getByText("Give the customer’s answer.")).toBeTruthy();
    await user.type(within(form).getByLabelText(ANSWER_FIELD), "Yes");
    const date = within(form).getByLabelText("Date answered");
    await user.clear(date);
    await user.type(date, "2999-01-01");
    await user.click(within(form).getByRole("button", { name: "Record answer" }));
    expect(within(form).getByText("The date answered can’t be in the future.")).toBeTruthy();
    expect(recordAnswer).not.toHaveBeenCalled();

    await user.clear(date);
    await user.type(date, "2026-10-12");
    await user.click(within(form).getByRole("checkbox"));
    await user.click(within(form).getByRole("button", { name: "Record answer" }));
    expect(recordAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ answeredOn: "2026-10-12", settlesGap: false }),
    );
  });

  it("a failed Record answer keeps the form open with the typed text", async () => {
    const user = userEvent.setup();
    recordAnswer.mockResolvedValue({ kind: "error" });
    renderSection(repList([sentGap(1, "high")]));
    const inspector = await openRow(user, 1);
    await user.click(within(inspector).getByRole("button", { name: "Record answer" }));
    const form = within(inspector).getByRole("form", { name: ANSWER_FORM });
    await user.type(within(form).getByLabelText(ANSWER_FIELD), "A long answer");
    await user.click(within(form).getByRole("button", { name: "Record answer" }));

    expect(await screen.findByText("The answer could not be recorded. Try again.")).toBeTruthy();
    const kept = within(inspector).getByRole("form", { name: ANSWER_FORM });
    expect((within(kept).getByLabelText(ANSWER_FIELD) as HTMLTextAreaElement).value).toBe(
      "A long answer",
    );
  });

  it("a 409 says the question is no longer sent and re-reads", async () => {
    const user = userEvent.setup();
    recordAnswer.mockResolvedValue({ kind: "question-not-sent" });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([answeredGap(1)]) });
    renderSection(repList([sentGap(1, "high")]));
    const inspector = await openRow(user, 1);
    await user.click(within(inspector).getByRole("button", { name: "Record answer" }));
    const form = within(inspector).getByRole("form", { name: ANSWER_FORM });
    await user.type(within(form).getByLabelText(ANSWER_FIELD), "Yes");
    await user.click(within(form).getByRole("button", { name: "Record answer" }));

    expect(await screen.findByText("This Clarification Question is no longer sent.")).toBeTruthy();
    expect(loadGaps).toHaveBeenCalled();
  });

  it("the Answer section shows the passage as Evidence and links the Requirement changes", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(repList([answeredGap(1)]));
    const inspector = await openRow(user, 1);

    expect(within(inspector).getByText("S2 · reply.txt")).toBeTruthy();
    expect(within(inspector).getByText(PASSAGE.excerpt)).toBeTruthy();
    expect(within(inspector).getByText("Recorded by Rep Person")).toBeTruthy();
    const link = within(inspector).getByRole("link", { name: "R1 · pending change" });
    expect(link.getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/requirements?requirement=${R1_ID}`,
    );
    expect(within(inspector).queryByRole("button", { name: "Record answer" })).toBeNull();
    // Reopen is for editors only.
    expect(within(inspector).queryByRole("form", { name: "Reopen the Gap" })).toBeNull();
    expect(screen.getAllByRole("row")[0].textContent).toContain("Answered");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("editors reopen an answered Gap", async () => {
    const user = userEvent.setup();
    reopenGap.mockResolvedValue({ kind: "ok", gap: { ...sentGap(1, "high"), row_version: 9 } });
    renderSection(list([answeredGap(1)], succeeded, true, true, true, true));
    const inspector = await openRow(user, 1);
    const form = within(inspector).getByRole("form", { name: "Reopen the Gap" });

    await user.type(within(form).getByRole("textbox"), "Incomplete");
    await user.click(within(form).getByRole("button", { name: "Reopen" }));

    expect(reopenGap).toHaveBeenCalledWith(
      expect.objectContaining({ gapId: answeredGap(1).id, reason: "Incomplete" }),
    );
    await waitFor(() => expect(screen.getAllByRole("row")[0].textContent).toContain("Sent"));
  });

  it("a suggestion shows its Source in the row and Confirm or Not an answer in the card", async () => {
    const user = userEvent.setup();
    confirmAnswerMatch.mockResolvedValue({ kind: "ok", gap: answeredGap(1) });
    const suggested = suggestedGap(1, true);
    const { container } = renderSection(repList([suggested]));
    expect(screen.getAllByRole("row")[0].textContent).toContain(
      "Possible answer in Source 'reply.txt'",
    );
    const inspector = await openRow(user, 1);
    const card = within(inspector).getByRole("article", {
      name: "Possible answer in Source 'reply.txt'",
    });
    expect(within(card).getByText("Injection suspected")).toBeTruthy();
    expect(within(card).getByText(PASSAGE.excerpt)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(card).getByRole("button", { name: "Confirm" }));

    expect(confirmAnswerMatch).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      matchId: suggested.answer_suggestions[0]!.id,
      rowVersion: 1,
    });
    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].textContent).toContain("Answered by customer, 12 Oct"),
    );
  });

  it("Not an answer rejects the suggestion; a stale one shows Reload", async () => {
    const user = userEvent.setup();
    rejectAnswerMatch.mockResolvedValueOnce({ kind: "stale" });
    renderSection(repList([suggestedGap(1)]));
    const inspector = await openRow(user, 1);

    await user.click(within(inspector).getByRole("button", { name: "Not an answer" }));

    expect(rejectAnswerMatch).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("readers without send rights see suggestions without the buttons", async () => {
    const user = userEvent.setup();
    renderSection(list([suggestedGap(1)], succeeded, false, false, false, false));
    const inspector = await openRow(user, 1);
    expect(within(inspector).queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(within(inspector).queryByRole("button", { name: "Record answer" })).toBeNull();
  });
});

/** A stand-in for the browser's EventSource (jsdom has none). */
class FakeGapsEventSource {
  static instances: FakeGapsEventSource[] = [];
  readonly listeners = new Map<string, ((event: Event) => void)[]>();

  constructor(readonly url: string) {
    FakeGapsEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {}

  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener(new Event(type));
  }
}

describe("live Gaps over the event stream (Story 4.7)", () => {
  beforeEach(() => {
    FakeGapsEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeGapsEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("a gaps.changed frame re-reads the list, updating pills and the open count", async () => {
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([answeredGap(1), sentGap(2, "low")]) });
    renderSection(repList([sentGap(1, "high"), sentGap(2, "low")]));
    const source = FakeGapsEventSource.instances[0]!;
    expect(source.url).toBe(`/api/opportunities/${OPP_ID}/events`);

    await act(async () => source.emit("gaps.changed"));

    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].textContent).toContain("Answered by customer, 12 Oct"),
    );
    expect(screen.getByText("2 Gaps · 1 open · ranked by impact")).toBeTruthy();
    expect(loadGaps).toHaveBeenCalledWith(OPP_ID);
  });

  it("while connected nothing polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([sentGap(1, "high")]) });
    renderSection(repList([sentGap(1, "high")]));
    await act(async () => FakeGapsEventSource.instances[0]!.emit("open"));
    expect(loadGaps).toHaveBeenCalledTimes(1); // the catch-up read on connecting

    await act(async () => vi.advanceTimersByTime(3 * GAPS_FALLBACK_POLL_MS));

    expect(loadGaps).toHaveBeenCalledTimes(1);
  });
});

describe("the polling fallback while the stream is not connected (Story 4.7)", () => {
  it("re-reads the list on a timer, and stops once unmounted", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    loadGaps.mockResolvedValue({ kind: "ok", list: repList([answeredGap(1)]) });
    const view = renderSection(repList([sentGap(1, "high")]));
    expect(loadGaps).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTime(GAPS_FALLBACK_POLL_MS));

    expect(loadGaps).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getAllByRole("row")[0].textContent).toContain("Answered by customer, 12 Oct"),
    );
    view.unmount();
    await act(async () => vi.advanceTimersByTime(3 * GAPS_FALLBACK_POLL_MS));
    expect(loadGaps).toHaveBeenCalledTimes(1);
  });
});
