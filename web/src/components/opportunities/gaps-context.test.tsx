import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VersionResult } from "@/app/knowledge/checklists/actions";
import type { ChecklistVersion } from "@/lib/checklists";
import type { GapList, GapsContext } from "@/lib/gaps";
import { axeViolations } from "@/test/axe";

const loadChecklistVersion = vi.hoisted(() =>
  vi.fn<(checklistId: unknown, version: unknown) => Promise<VersionResult>>(),
);
vi.mock("@/app/knowledge/checklists/actions", () => ({ loadChecklistVersion }));
vi.mock("@/app/opportunities/actions", () => ({
  loadGaps: vi.fn(),
  startGapDetection: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/gaps",
}));

import { KeyboardShortcuts } from "../shell/keyboard-shortcuts";
import { RightPane } from "../shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, ShellProviders, useShell } from "../shell/shell-context";
import { GapsContextBar } from "./gaps-context";
import { GapsSection } from "./gaps-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const SECURITY = "00000000-0000-7000-8000-0000000000c1";
const SAP = "00000000-0000-7000-8000-0000000000c2";
const EDI = "00000000-0000-7000-8000-0000000000e1";

function context(over: Partial<GapsContext> = {}): GapsContext {
  return {
    applicable_checklists: [
      { checklist_id: SECURITY, version: 3, name: "Security baseline", domain: "security" },
      { checklist_id: SAP, version: 1, name: "SAP integration", domain: "engineering" },
    ],
    untagged_integration_count: 0,
    uncovered: { products: [], integration_types: [] },
    ...over,
  };
}

const EMPTY: GapList = {
  items: [],
  detection: { status: "succeeded", error_code: null },
  can_start_detection: true,
  can_edit_questions: false,
  can_edit_gaps: false,
  can_send_questions: false,
};

function version(): ChecklistVersion {
  return {
    checklist_id: SECURITY,
    version: 3,
    name: "Security baseline",
    domain: "security",
    products: [],
    industry: null,
    integration_types: [],
    items: [
      {
        id: "00000000-0000-7000-8000-0000000000d1",
        kind: "question",
        text: "Is single sign-on required?",
        why_it_matters: "It shapes the identity design.",
        affected_area: null,
        impact: "high",
        mandatory: true,
      },
      {
        id: "00000000-0000-7000-8000-0000000000d2",
        kind: "risk",
        text: "Audit logs are retained.",
        why_it_matters: "Retention drives storage.",
        affected_area: null,
        impact: "low",
        mandatory: false,
      },
    ],
    published_by: { id: "00000000-0000-7000-8000-0000000000f1", name: "Reviewer Person" },
    published_at: "2026-10-20T09:00:00Z",
  };
}

function renderBar(ctx: GapsContext) {
  return render(
    <GapsContextBar
      opportunityId={OPP_ID}
      context={ctx}
      openChecklistId={null}
      onOpenChecklist={() => {}}
    />,
  );
}

/** Stands in for the shell's right-pane toggle. */
function PaneToggle() {
  const { toggleRightPane } = useShell();
  return (
    <button type="button" id={RIGHT_PANE_TOGGLE_ID} onClick={toggleRightPane}>
      Toggle
    </button>
  );
}

function renderSection(ctx: GapsContext | null) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <KeyboardShortcuts permissions={[]} />
      <PaneToggle />
      <GapsSection opportunityId={OPP_ID} initial={EMPTY} context={ctx} />
      <RightPane />
    </ShellProviders>,
  );
}

beforeEach(() => {
  loadChecklistVersion.mockReset();
});

describe("GapsContextBar", () => {
  it("shows one chip per applicable Checklist and no banners when all is covered", async () => {
    const { container } = renderBar(context());
    const group = screen.getByRole("group", { name: "Applicable Checklists" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Security baseline · v3",
      "SAP integration · v1",
    ]);
    expect(screen.queryByTestId("untagged-banner")).toBeNull();
    expect(screen.queryByTestId("coverage-banner")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says no Checklists apply yet when none match", () => {
    renderBar(context({ applicable_checklists: [] }));
    expect(
      screen.getByText(
        "No Checklists apply yet — tag integration Requirements or set products and industry.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.queryByTestId("untagged-banner")).toBeNull();
    expect(screen.queryByTestId("coverage-banner")).toBeNull();
  });

  it.each([
    [1, "1 integration Requirement has no Integration Type — Checklists may not apply"],
    [2, "2 integration Requirements have no Integration Type — Checklists may not apply"],
  ])("shows the untagged banner for %i, linking to the filtered Requirements", (n, text) => {
    renderBar(context({ untagged_integration_count: n }));
    const banner = screen.getByTestId("untagged-banner");
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.className).toContain("rounded-[10px]");
    expect(banner.className).toContain("bg-gap-tint");
    expect(banner.textContent).toBe(`${text}Show them`);
    expect(within(banner).getByRole("link", { name: "Show them" }).getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/requirements?untagged=integration`,
    );
  });

  it("names uncovered integration types and products and links to the first type", () => {
    renderBar(
      context({
        uncovered: {
          products: ["AutoStore", "Pick station"],
          integration_types: [
            { id: EDI, name: "EDI" },
            { id: SAP, name: "SAP" },
          ],
        },
      }),
    );
    const banner = screen.getByTestId("coverage-banner");
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.className).toContain("bg-primary-tint");
    expect(banner.textContent).toBe(
      "No documentation for 2 integration types and 2 products in scope — Gap detection may " +
        "be incompleteOpen Knowledge Sources",
    );
    expect(
      within(banner).getByRole("link", { name: "Open Knowledge Sources" }).getAttribute("href"),
    ).toBe(`/knowledge?integration_type=${EDI}`);
  });

  it("leaves out a zero part and links to the first uncovered product", () => {
    renderBar(context({ uncovered: { products: ["Pick station"], integration_types: [] } }));
    const banner = screen.getByTestId("coverage-banner");
    expect(banner.textContent).toContain("No documentation for 1 product in scope —");
    expect(within(banner).getByRole("link").getAttribute("href")).toBe(
      "/knowledge?product=Pick%20station",
    );
  });

  it("names a single uncovered integration type", () => {
    renderBar(
      context({ uncovered: { products: [], integration_types: [{ id: EDI, name: "EDI" }] } }),
    );
    expect(screen.getByTestId("coverage-banner").textContent).toContain(
      "No documentation for 1 integration type in scope —",
    );
  });
});

describe("GapsSection with the context", () => {
  it("renders the strip and banners under the header", () => {
    renderSection(context({ untagged_integration_count: 2 }));
    expect(screen.getByTestId("gaps-context")).toBeTruthy();
    expect(screen.getByTestId("untagged-banner")).toBeTruthy();
  });

  it("still renders the Gaps when the context read failed, without strip or banners", () => {
    renderSection(null);
    expect(screen.queryByTestId("gaps-context")).toBeNull();
    expect(screen.queryByText("Applicable Checklists")).toBeNull();
    expect(screen.getByRole("heading", { name: "Gaps" })).toBeTruthy();
  });

  it("opens a Checklist read-only; Esc closes it and focus returns to the chip", async () => {
    loadChecklistVersion.mockResolvedValue({ kind: "ok", version: version() });
    const user = userEvent.setup();
    renderSection(context());
    const chip = screen.getByRole("button", { name: "Security baseline · v3" });

    chip.focus();
    await user.keyboard("{Enter}");

    const pane = await screen.findByTestId("checklist-pane");
    expect(loadChecklistVersion).toHaveBeenCalledWith(SECURITY, 3);
    expect(within(pane).getByRole("heading", { name: "Security baseline" })).toBeTruthy();
    expect(within(pane).getByText("Version 3 · Security")).toBeTruthy();
    await waitFor(() =>
      expect(within(pane).getByText("Is single sign-on required?")).toBeTruthy(),
    );
    expect(within(pane).getByText("Mandatory")).toBeTruthy();
    expect(within(pane).getByText("Optional")).toBeTruthy();
    expect(within(pane).queryByRole("textbox")).toBeNull();
    expect(chip.getAttribute("aria-pressed")).toBe("true");

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByTestId("checklist-pane")).toBeNull());
    expect(document.activeElement).toBe(chip);
  });

  it("says when the Checklist can't be loaded", async () => {
    loadChecklistVersion.mockResolvedValue({ kind: "error" });
    const user = userEvent.setup();
    renderSection(context());
    await user.click(screen.getByRole("button", { name: "SAP integration · v1" }));
    const pane = await screen.findByTestId("checklist-pane");
    await act(async () => {});
    await waitFor(() =>
      expect(within(pane).getByText("The Checklist could not be loaded.")).toBeTruthy(),
    );
  });
});
