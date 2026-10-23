import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PassageResult,
  RequirementTagInput,
  RequirementWriteResult,
} from "@/app/opportunities/actions";
import type { OutdatedAssessmentsResult, RequirementsResult } from "@/app/opportunities/data";
import type { Classification, Requirement, RequirementList } from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const tagRequirementIntegrationTypes = vi.hoisted(() =>
  vi.fn<(input: RequirementTagInput) => Promise<RequirementWriteResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
const getPassage = vi.hoisted(() =>
  vi.fn<(opportunityId: string, passageId: string) => Promise<PassageResult>>(),
);
const loadOutdatedAssessments = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<OutdatedAssessmentsResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  tagRequirementIntegrationTypes,
  loadOutdatedAssessments,
  loadRequirements,
  getPassage,
  startExtraction: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/requirements",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const SAP = { id: "00000000-0000-7000-8000-0000000000a1", name: "SAP" };
const EDI = { id: "00000000-0000-7000-8000-0000000000a2", name: "EDI" };
const OLD = {
  id: "00000000-0000-7000-8000-0000000000a3",
  code: "OLD",
  name: "Old FTP",
  retired: true,
};
const TYPES = [SAP, EDI];

function requirement(
  n: number,
  classification: Classification = "integration",
  extra: Partial<Requirement> = {},
): Requirement {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    number: n,
    text: `[REQUIREMENT ${n}]`,
    classification,
    origin: "extracted",
    locked_by_human: false,
    version: 1,
    row_version: 1,
    created_at: "2026-10-04T13:05:00Z",
    confirmed_at: null,
    confirmed_by: null,
    last_changed_by: null,
    pending_change: null,
    evidence: [],
    integration_types: [],
    ...extra,
  };
}

function list(items: Requirement[], canEdit = true): RequirementList {
  return {
    items,
    extraction: { status: "succeeded", error_code: null, source_count: 1 },
    can_start_extraction: true,
    can_edit_requirements: canEdit,
    untagged_integration_count: 0,
  };
}

function renderSection(initial: RequirementList, untaggedOnly = false) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <RequirementsSection
        opportunityId={OPP_ID}
        initial={initial}
        integrationTypes={TYPES}
        untaggedOnly={untaggedOnly}
      />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: `[REQUIREMENT ${n}]` });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  tagRequirementIntegrationTypes.mockReset();
  loadRequirements.mockReset();
  getPassage.mockReset();
  loadOutdatedAssessments.mockReset();
  loadOutdatedAssessments.mockResolvedValue({ kind: "ok", items: [] });
});

describe("the Requirement inspector's Integration Types", () => {
  it("editors tick a type and it saves the whole set at once with the row version", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, "integration", {
      row_version: 4,
      integration_types: [{ ...SAP, code: "SAP", retired: false }],
    });
    renderSection(list([r1]));
    tagRequirementIntegrationTypes.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        row_version: 5,
        integration_types: [
          { ...SAP, code: "SAP", retired: false },
          { ...EDI, code: "EDI", retired: false },
        ],
      },
    });

    await user.click(row(1));
    const group = within(pane()).getByRole("group", { name: "Integration Types" });
    expect(
      (within(group).getByRole("checkbox", { name: "SAP" }) as HTMLInputElement).checked,
    ).toBe(true);
    await user.click(within(group).getByRole("checkbox", { name: "EDI" }));

    expect(tagRequirementIntegrationTypes).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requirementId: r1.id,
      rowVersion: 4,
      integrationTypeIds: [SAP.id, EDI.id],
    });
    await waitFor(() =>
      expect(
        (within(group).getByRole("checkbox", { name: "EDI" }) as HTMLInputElement).checked,
      ).toBe(true),
    );
  });

  it("keeps a stored retired type listed with its Retired label, and can remove it", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1, "integration", { integration_types: [OLD] });
    renderSection(list([r1]));
    tagRequirementIntegrationTypes.mockResolvedValue({
      kind: "ok",
      requirement: { ...r1, row_version: 2, integration_types: [] },
    });

    await user.click(row(1));
    const group = within(pane()).getByRole("group", { name: "Integration Types" });
    const old = within(group).getByRole("checkbox", { name: /Old FTP/ });
    expect(within(group).getByText("Retired")).toBeTruthy();
    await user.click(old);

    expect(tagRequirementIntegrationTypes.mock.calls[0]![0].integrationTypeIds).toEqual([]);
    expect(await axeViolations(pane())).toEqual([]);
  });

  it("a 412 shows the stale notice with Reload", async () => {
    const user = userEvent.setup();
    renderSection(list([requirement(1)]));
    tagRequirementIntegrationTypes.mockResolvedValue({ kind: "stale", changedBy: "[COLLEAGUE]" });

    await user.click(row(1));
    await user.click(within(pane()).getByRole("checkbox", { name: "SAP" }));

    await waitFor(() =>
      expect(screen.getByText("Changed by [COLLEAGUE] since you opened it.")).toBeTruthy(),
    );
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    // Nothing more is saved until the Requirements are reloaded.
    expect(within(pane()).getByRole("checkbox", { name: "SAP" }).matches(":disabled")).toBe(true);
  });

  it("viewers see the tags read-only, or None", async () => {
    const user = userEvent.setup();
    renderSection(
      list(
        [
          requirement(1, "integration", { integration_types: [OLD] }),
          requirement(2, "integration"),
        ],
        false,
      ),
    );

    await user.click(row(1));
    expect(within(pane()).queryByRole("checkbox")).toBeNull();
    expect(within(pane()).getByText("Old FTP")).toBeTruthy();
    expect(within(pane()).getByText("Retired")).toBeTruthy();
    await user.click(row(2));
    const section = within(pane()).getByRole("region", { name: "Integration Types" });
    expect(within(section).getByText("None")).toBeTruthy();
  });
});

describe("?untagged=integration", () => {
  it("lists only integration Requirements with no Integration Type, with a status bar", () => {
    const tagged = requirement(1, "integration", {
      integration_types: [{ ...SAP, code: "SAP", retired: false }],
    });
    renderSection(
      list([tagged, requirement(2), requirement(3), requirement(4, "functional")]),
      true,
    );

    const bar = screen.getByTestId("untagged-filter");
    expect(bar.getAttribute("role")).toBe("status");
    expect(bar.textContent).toBe(
      "Showing 2 integration Requirements with no Integration TypeShow all",
    );
    expect(within(bar).getByRole("link", { name: "Show all" }).getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/requirements`,
    );
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 1]" })).toBeNull();
    expect(screen.queryByRole("button", { name: "[REQUIREMENT 4]" })).toBeNull();
    expect(row(2)).toBeTruthy();
    expect(row(3)).toBeTruthy();
  });

  it("keeps the open Requirement listed after tagging it, while the count drops", async () => {
    const user = userEvent.setup();
    const r1 = requirement(1);
    renderSection(list([r1, requirement(2)]), true);
    tagRequirementIntegrationTypes.mockResolvedValue({
      kind: "ok",
      requirement: {
        ...r1,
        row_version: 2,
        integration_types: [{ ...SAP, code: "SAP", retired: false }],
      },
    });

    await user.click(row(1));
    await user.click(within(pane()).getByRole("checkbox", { name: "SAP" }));

    await waitFor(() =>
      expect(screen.getByTestId("untagged-filter").textContent).toContain(
        "Showing 1 integration Requirement with no Integration Type",
      ),
    );
    expect(row(1)).toBeTruthy();
    expect(row(2)).toBeTruthy();
  });

  it("says one Requirement in the singular", () => {
    renderSection(list([requirement(1)]), true);
    expect(screen.getByTestId("untagged-filter").textContent).toContain(
      "Showing 1 integration Requirement with no Integration Type",
    );
  });

  it("without the parameter lists every Requirement and no status bar", () => {
    renderSection(list([requirement(1), requirement(2, "functional")]));
    expect(screen.queryByTestId("untagged-filter")).toBeNull();
    expect(row(1)).toBeTruthy();
    expect(row(2)).toBeTruthy();
  });
});
