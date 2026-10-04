import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import type { Opportunity, OpportunitySummary } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("server-only", () => ({}));
vi.mock("@/app/opportunities/actions", () => ({
  createOpportunity: vi.fn(),
  changeCollaborator: vi.fn(),
  updateOpportunity: vi.fn(),
  loadOpportunity: vi.fn(),
  searchUsers: vi.fn(),
  addSource: vi.fn(),
  addTextSource: vi.fn(),
  retryParse: vi.fn(),
  loadSources: vi.fn(),
  loadRequirements: vi.fn(),
  startExtraction: vi.fn(),
  loadGaps: vi.fn(),
  startGapDetection: vi.fn(),
  loadEstimate: vi.fn(),
  startEstimateDraft: vi.fn(),
  loadRedTeam: vi.fn(),
  startRedTeamReview: vi.fn(),
}));
const redirect = vi.hoisted(() =>
  vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT ${href}`);
  }),
);
const notFound = vi.hoisted(() =>
  vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
);
const segment = vi.hoisted(() => ({ current: null as string | null }));
vi.mock("next/navigation", () => ({
  redirect,
  notFound,
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => "/my-opportunities",
  useSelectedLayoutSegment: () => segment.current,
}));

import WorkspaceTabPage from "@/app/opportunities/[id]/[tab]/page";
import OpportunityLayout from "@/app/opportunities/[id]/layout";
import OpportunityPage from "@/app/opportunities/[id]/page";
import NewOpportunityPage from "@/app/opportunities/new/page";
import OpportunitiesPage from "@/app/opportunities/page";
import MyOpportunitiesPage from "@/app/my-opportunities/page";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

const NO_ACCESS =
  "You're signed in, but you don't have access yet. Ask an administrator to assign a role.";
const OPP_ID = "00000000-0000-7000-8000-000000000001";

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: { id: "00000000-0000-7000-8000-000000000000", name: "[USER]", email: "u@x", roles },
  });
}

const SUMMARY: OpportunitySummary = {
  id: OPP_ID,
  title: "[TITLE]",
  customer_name: "[CUSTOMER]",
  status: "intake",
  owner: { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" },
  target_proposal_date: "2026-11-01",
  created_at: "2026-10-04T10:00:00Z",
};

const OPPORTUNITY: Opportunity = {
  ...SUMMARY,
  products: ["AutoStore", "Pick station"],
  industry: "Retail",
  collaborators: [{ id: "00000000-0000-7000-8000-0000000000b2", name: "[MEMBER]" }],
  row_version: 2,
  last_changed_by: null,
  can_manage_collaborators: false,
  can_edit: false,
  can_add_sources: false,
};

const FACETS = {
  owners: [SUMMARY.owner],
  products: ["AutoStore", "Pick station"],
};

function listed(items: OpportunitySummary[], total = items.length, page = 1) {
  apiGet.mockImplementation(async (path: string) => ({
    data:
      path === "/api/v1/opportunities/facets"
        ? FACETS
        : { items, page, page_size: 50, total },
    response: new Response(null, { status: 200 }),
  }));
}

const params = (page?: string) => Promise.resolve(page ? { page } : {});

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  redirect.mockClear();
  notFound.mockClear();
  segment.current = null;
});

const LISTS = [
  ["/my-opportunities", MyOpportunitiesPage, "My Opportunities", "mine"],
  ["/opportunities", OpportunitiesPage, "All Opportunities", "all"],
] as const;

describe.each(LISTS)("%s", (_path, Page, title, scope) => {
  it("lists Opportunities in the shell; New Opportunity for presales engineers", async () => {
    signedIn(["presales_engineer"]);
    listed([SUMMARY]);
    const { container } = renderPage(await Page({ searchParams: params() }));

    expect(screen.getByRole("heading", { level: 1, name: title })).toBeTruthy();
    expect(screen.getByRole("link", { name: "New Opportunity" }).getAttribute("href")).toBe(
      "/opportunities/new",
    );
    expect(await screen.findByRole("link", { name: "[CUSTOMER]" })).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities", {
      params: { query: { scope, page: 1, page_size: 50 } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("hides New Opportunity from other roles", async () => {
    signedIn(["head_of_delivery"]);
    listed([SUMMARY]);
    renderPage(await Page({ searchParams: params() }));
    expect(screen.queryByRole("link", { name: "New Opportunity" })).toBeNull();
  });

  it("empty: the empty-state sentence after the skeleton", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    const { container } = renderPage(await Page({ searchParams: params() }));
    expect(container.querySelector("[data-skeleton-row]")).toBeTruthy();
    expect(await screen.findByText("No Opportunities yet. Press c to create one.")).toBeTruthy();
  });

  it("paginates with Previous and Next, and redirects past the last page", async () => {
    signedIn(["presales_engineer"]);
    listed([SUMMARY], 120, 2);
    renderPage(await Page({ searchParams: params("2") }));
    expect(screen.getByText("51–51 of 120")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Previous" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Next" })).toBeTruthy();
    listed([], 120, 9);
    await expect(Page({ searchParams: params("9") })).rejects.toThrow(
      `NEXT_REDIRECT ${_path}?page=3`,
    );
  });

  it("a page past the end of an empty list redirects to the list itself", async () => {
    signedIn(["presales_engineer"]);
    listed([], 0, 3);
    await expect(Page({ searchParams: params("3") })).rejects.toThrow(`NEXT_REDIRECT ${_path}`);
    expect(redirect).toHaveBeenLastCalledWith(_path);
  });

  it("no roles: only the no-access message", async () => {
    signedIn([]);
    renderPage(await Page({ searchParams: params() }));
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("an unreachable API shows the platform message", async () => {
    signedIn(["presales_engineer"]);
    apiGet.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage(await Page({ searchParams: params() }));
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});

describe("All Opportunities filters", () => {
  const OWNER_ID = SUMMARY.owner.id;
  const query = (values: Record<string, string>) => Promise.resolve(values);

  it("passes the URL's filters to the API and shows them in the filter bar", async () => {
    signedIn(["head_of_delivery"]);
    listed([SUMMARY]);
    const { container } = renderPage(
      await OpportunitiesPage({
        searchParams: query({ owner: OWNER_ID, product: "Pick station", from: "2026-11-01" }),
      }),
    );

    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities", {
      params: {
        query: {
          scope: "all",
          page: 1,
          page_size: 50,
          owner: OWNER_ID,
          product: "Pick station",
          from: "2026-11-01",
        },
      },
    });
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/facets");
    expect((screen.getByLabelText("Owner") as HTMLSelectElement).value).toBe(OWNER_ID);
    expect((screen.getByLabelText("Product") as HTMLSelectElement).value).toBe("Pick station");
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe(
      "/opportunities",
    );
    expect(await screen.findByRole("link", { name: "[CUSTOMER]" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("drops invalid filters and lists unfiltered", async () => {
    signedIn(["head_of_delivery"]);
    listed([SUMMARY]);
    renderPage(
      await OpportunitiesPage({
        searchParams: query({ status: "bogus", owner: "nope", from: "2026-13-40" }),
      }),
    );
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities", {
      params: { query: { scope: "all", page: 1, page_size: 50 } },
    });
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("");
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });

  it("no matches: the filtered empty state with Clear filters, not the create one", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    renderPage(await OpportunitiesPage({ searchParams: query({ status: "closed" }) }));
    expect(await screen.findByText("No Opportunities match these filters.")).toBeTruthy();
    expect(screen.queryByText("No Opportunities yet. Press c to create one.")).toBeNull();
    const clears = screen.getAllByRole("link", { name: "Clear filters" });
    expect(clears.length).toBe(2);
    for (const link of clears) expect(link.getAttribute("href")).toBe("/opportunities");
  });

  it("page links and the past-the-end redirect keep the filters", async () => {
    signedIn(["head_of_delivery"]);
    listed([SUMMARY], 120, 2);
    renderPage(
      await OpportunitiesPage({ searchParams: query({ owner: OWNER_ID, page: "2" }) }),
    );
    expect(screen.getByRole("link", { name: "Previous" }).getAttribute("href")).toBe(
      `/opportunities?owner=${OWNER_ID}`,
    );
    expect(screen.getByRole("link", { name: "Next" }).getAttribute("href")).toBe(
      `/opportunities?owner=${OWNER_ID}&page=3`,
    );
    listed([], 120, 9);
    await expect(
      OpportunitiesPage({ searchParams: query({ owner: OWNER_ID, page: "9" }) }),
    ).rejects.toThrow(`NEXT_REDIRECT /opportunities?owner=${OWNER_ID}&page=3`);
    listed([], 0, 2);
    await expect(
      OpportunitiesPage({ searchParams: query({ owner: OWNER_ID, page: "2" }) }),
    ).rejects.toThrow(`NEXT_REDIRECT /opportunities?owner=${OWNER_ID}`);
    expect(redirect).toHaveBeenLastCalledWith(`/opportunities?owner=${OWNER_ID}`);
  });

  it("My Opportunities has no filter bar and ignores filter params", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    renderPage(
      await MyOpportunitiesPage({ searchParams: query({ status: "closed", owner: OWNER_ID }) }),
    );
    expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities", {
      params: { query: { scope: "mine", page: 1, page_size: 50 } },
    });
    expect(await screen.findByText("No Opportunities yet. Press c to create one.")).toBeTruthy();
  });
});

describe("/opportunities/new", () => {
  it("shows the form to presales engineers", async () => {
    signedIn(["presales_engineer"]);
    const { container } = renderPage(await NewOpportunityPage());
    expect(screen.getByRole("heading", { level: 1, name: "New Opportunity" })).toBeTruthy();
    expect(screen.getByLabelText("Customer name")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tells other roles they can't create", async () => {
    signedIn(["head_of_delivery"]);
    renderPage(await NewOpportunityPage());
    expect(screen.getByText("You don't have access to create Opportunities.")).toBeTruthy();
    expect(screen.queryByLabelText("Customer name")).toBeNull();
  });
});

describe("/opportunities/[id] workspace", () => {
  const PLATFORM_DOWN = "The platform is not reachable right now. Try again in a moment.";
  const NOT_AVAILABLE = "Not available yet.";
  const NO_ACCESS_TO_OPP = "You don't have access to this Opportunity";

  /** Renders the workspace layout around a tab page, as Next.js would for `tab` (none is
   * `/opportunities/{id}`). */
  async function renderWorkspace(tab?: string, id = OPP_ID) {
    segment.current = tab ?? null;
    const page = tab
      ? await WorkspaceTabPage({ params: Promise.resolve({ id, tab }) })
      : await OpportunityPage({ params: Promise.resolve({ id }) });
    return renderPage(
      await OpportunityLayout({ children: page, params: Promise.resolve({ id }) }),
    );
  }

  function found(opportunity: Opportunity = OPPORTUNITY) {
    apiGet.mockResolvedValue({ data: opportunity, response: new Response(null, { status: 200 }) });
  }

  function hidden() {
    apiGet.mockResolvedValue({
      error: { code: "not_found" },
      response: new Response(null, { status: 404 }),
    });
  }

  const selectedTabs = () =>
    screen
      .getAllByRole("tab")
      .filter((t) => t.getAttribute("aria-selected") === "true")
      .map((t) => t.textContent);

  it("Open: header and Overview, tab 1 selected", async () => {
    signedIn(["head_of_delivery"]);
    found();
    const { container } = await renderWorkspace();

    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(9);
    expect(selectedTabs()).toEqual(["1Overview"]);
    const panel = screen.getByRole("tabpanel", { name: "Overview" });
    // Overview: status, owner, collaborators, created date, customer, products, industry.
    expect(within(panel).getByText("Intake")).toBeTruthy();
    expect(within(panel).getByText("[OWNER]")).toBeTruthy();
    expect(within(panel).getByText("[MEMBER]")).toBeTruthy();
    expect(within(panel).getByText("4 Oct 2026")).toBeTruthy();
    expect(within(panel).getByText("[CUSTOMER]")).toBeTruthy();
    expect(within(panel).getByText("Pick station")).toBeTruthy();
    expect(within(panel).getByText("Retail")).toBeTruthy();
    // Header: the target proposal date.
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    // Not the owner: no collaborator or edit controls.
    expect(screen.queryByLabelText("Add collaborator")).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit title" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit target proposal date" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("/overview is the Overview tab too", async () => {
    signedIn(["head_of_delivery"]);
    found();
    await renderWorkspace("overview");
    expect(selectedTabs()).toEqual(["1Overview"]);
    expect(within(screen.getByRole("tabpanel")).getByText("Retail")).toBeTruthy();
  });

  it("Overview keeps the owner's collaborator controls", async () => {
    signedIn(["presales_engineer"]);
    found({ ...OPPORTUNITY, can_manage_collaborators: true });
    await renderWorkspace();
    expect(screen.getByLabelText("Add collaborator")).toBeTruthy();
  });

  it("the owner gets the inline title and date editors in the header", async () => {
    signedIn(["presales_engineer"]);
    found({ ...OPPORTUNITY, can_manage_collaborators: true, can_edit: true });
    const { container } = await renderWorkspace();
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit title" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit target proposal date" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  const SOURCE = {
    id: "00000000-0000-7000-8000-0000000000d4",
    kind: "transcript" as const,
    filename: "call.vtt",
    version: 2,
    version_count: 2,
    size_bytes: 61,
    uploaded_by: { id: "00000000-0000-7000-8000-0000000000b2", name: "[MEMBER]" },
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T12:00:00Z",
    parse: { status: "parsed" as const, error_code: null },
  };

  /** The Opportunity, and its Sources (`null`: the Sources request fails). */
  function foundWithSources(
    opportunity: Opportunity = OPPORTUNITY,
    sources: (typeof SOURCE)[] | null = [SOURCE],
  ) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/sources")
        ? sources
          ? { data: { items: sources }, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: opportunity, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /sources: the list for readers who can't add, without the upload area", async () => {
    signedIn(["head_of_delivery"]);
    foundWithSources();
    const { container } = await renderWorkspace("sources");
    expect(selectedTabs()).toEqual(["2Sources"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Sources" })).toBeTruthy();
    expect(within(panel).getByText("call.vtt")).toBeTruthy();
    expect(within(panel).getByText("v2")).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: "Choose files" })).toBeNull();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/sources", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /sources: owners and collaborators get the upload area", async () => {
    signedIn(["sales_representative"]);
    foundWithSources({ ...OPPORTUNITY, can_add_sources: true }, []);
    const { container } = await renderWorkspace("sources");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("button", { name: "Choose files" })).toBeTruthy();
    expect(within(panel).getByText("No Sources yet.")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /sources: a failed list says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithSources(OPPORTUNITY, null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("sources");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Sources could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  function foundWithRequirements(body: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/requirements")
        ? body
          ? { data: body, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /requirements: the grouped Requirements with Evidence labels", async () => {
    signedIn(["head_of_delivery"]);
    foundWithRequirements({
      items: [
        {
          id: "00000000-0000-7000-8000-0000000000e1",
          text: "[REQUIREMENT]",
          classification: "integration",
          origin: "extracted",
          locked_by_human: false,
          version: 1,
          row_version: 1,
          created_at: "2026-10-04T13:05:00Z",
          evidence: [
            {
              passage_id: "00000000-0000-7000-8000-0000000000f1",
              source_id: "00000000-0000-7000-8000-0000000000b1",
              source_version: 1,
              filename: "call.vtt",
              label: "S1 · call.vtt",
            },
          ],
        },
      ],
      extraction: { status: "succeeded", error_code: null, source_count: 1 },
      can_start_extraction: false,
    });
    const { container } = await renderWorkspace("requirements");
    expect(selectedTabs()).toEqual(["3Requirements"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Requirements" })).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 3, name: "Integration 1" })).toBeTruthy();
    expect(within(panel).getByText("[REQUIREMENT]")).toBeTruthy();
    expect(within(panel).getByText("S1 · call.vtt")).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/requirements", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /requirements: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithRequirements({ items: [], extraction: null, can_start_extraction: true });
    await renderWorkspace("requirements");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "Requirements appear here after Sources are parsed.",
      ),
    ).toBeTruthy();
  });

  it("tab URL /requirements: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithRequirements(null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("requirements");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Requirements could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  function foundWithEstimate(body: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/estimate")
        ? body
          ? { data: body, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /estimate: the grid with its version and server totals", async () => {
    signedIn(["sales_representative"]);
    const totals = {
      effort_hours: 10,
      contingency_hours: 0,
      total_hours: 10,
      role_hours: { engineer: 6, project_manager: 2, qa: 2 },
    };
    foundWithEstimate({
      version: {
        id: "00000000-0000-7000-8000-0000000000d1",
        version: 1,
        status: "draft",
        template_version: "demo-1",
        roles: ["engineer", "project_manager", "qa"],
        uncovered_count: 0,
        dropped_count: 0,
        row_version: 1,
        created_at: "2026-10-05T09:00:00Z",
        sections: [
          {
            section: "integration",
            lines: [
              {
                id: "00000000-0000-7000-8000-0000000000d2",
                position: 1,
                section: "integration",
                title: "[LINE]",
                basis: "[BASIS]",
                role_mix: { engineer: 60, project_manager: 20, qa: 20 },
                effort_hours: 10,
                contingency_hours: 0,
                total_hours: 10,
                role_hours: { engineer: 6, project_manager: 2, qa: 2 },
                requirements: [
                  {
                    id: "00000000-0000-7000-8000-0000000000f1",
                    version: 1,
                    label: "R1",
                    excerpt: "[EXCERPT]",
                  },
                ],
              },
            ],
            subtotal: totals,
          },
        ],
        totals,
        proposal_status: "succeeded",
        assumptions: { conditions: [], contingencies: [], contingency_hours: 0 },
        counts: { total: 0, accepted: 0, not_accepted: 0 },
        unconverted_gaps: [],
        unallocated_contingency_hours: 0,
      },
      draft: { status: "succeeded", error_code: null },
      can_start_draft: false,
      can_accept_assumptions: false,
    });
    const { container } = await renderWorkspace("estimate");
    expect(selectedTabs()).toEqual(["7Estimate"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Estimate" })).toBeTruthy();
    expect(within(panel).getByText("Draft v1")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "[LINE]" })).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/estimate", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /estimate: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithEstimate({
      version: null,
      draft: null,
      can_start_draft: true,
      can_accept_assumptions: true,
    });
    await renderWorkspace("estimate");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Estimate is drafted after Gaps are detected.",
      ),
    ).toBeTruthy();
  });

  it("tab URL /estimate: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithEstimate(null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("estimate");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Estimate could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  function foundWithGaps(body: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/gaps")
        ? body
          ? { data: body, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /gaps: the ranked Gaps with their category and Draft question", async () => {
    signedIn(["sales_representative"]);
    foundWithGaps({
      items: [
        {
          id: "00000000-0000-7000-8000-0000000000e1",
          title: "[GAP]",
          category: "integration_details",
          trigger: { kind: "agent_category", category: "integration_details" },
          why_it_matters: "[WHY]",
          impact: "high",
          impact_basis: "[BASIS]",
          origin: "detected",
          status: "open",
          converted_to: null,
          row_version: 1,
          created_at: "2026-10-05T09:00:00Z",
          requirements: [
            {
              id: "00000000-0000-7000-8000-0000000000f1",
              version: 1,
              label: "R1",
              excerpt: "[EXCERPT]",
            },
          ],
          question: {
            id: "00000000-0000-7000-8000-0000000000f2",
            text: "[QUESTION]",
            topic: "[TOPIC]",
            status: "drafted",
            status_changed_at: "2026-10-05T09:00:00Z",
            row_version: 1,
          },
        },
      ],
      detection: { status: "succeeded", error_code: null },
      can_start_detection: false,
    });
    const { container } = await renderWorkspace("gaps");
    expect(selectedTabs()).toEqual(["4Gaps"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Gaps" })).toBeTruthy();
    expect(within(panel).getByRole("row").textContent).toBe("HighIntegration details[GAP]Draft");
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/gaps", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /gaps: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithGaps({ items: [], detection: null, can_start_detection: true });
    await renderWorkspace("gaps");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "Gaps appear here after Requirements are extracted.",
      ),
    ).toBeTruthy();
  });

  it("tab URL /gaps: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithGaps(null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("gaps");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Gaps could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  function foundWithRedTeam(body: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/red-team")
        ? body
          ? { data: body, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /assessments: the Red Team section with its severity-ranked Findings", async () => {
    signedIn(["sales_representative"]);
    foundWithRedTeam({
      review: {
        id: "00000000-0000-7000-8000-0000000000c1",
        version: 2,
        status: "current",
        estimate_version_id: "00000000-0000-7000-8000-0000000000d1",
        estimate_version: 2,
        dropped_count: 0,
        created_at: "2026-10-05T09:00:00Z",
        counts: { critical: 1, high: 0, medium: 0, low: 0 },
        findings: [
          {
            id: "00000000-0000-7000-8000-0000000000c2",
            position: 1,
            category: "integration_harder",
            severity: "critical",
            title: "[FINDING]",
            argument: "[ARGUMENT]",
            requirements: [
              {
                id: "00000000-0000-7000-8000-0000000000f1",
                version: 1,
                label: "R1",
                excerpt: "[EXCERPT]",
              },
            ],
            lines: [],
          },
        ],
      },
      run: { status: "succeeded", error_code: null },
      can_start: false,
    });
    const { container } = await renderWorkspace("assessments");
    expect(selectedTabs()).toEqual(["5Assessments"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Assessments" })).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 3, name: "Red Team" })).toBeTruthy();
    expect(within(panel).getByText("Red Team v2")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /\[FINDING\]/ })).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/red-team", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /assessments: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithRedTeam({ review: null, run: null, can_start: true });
    await renderWorkspace("assessments");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Red Team reviews the Opportunity after the Estimate is drafted.",
      ),
    ).toBeTruthy();
  });

  it("tab URL /assessments: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithRedTeam(null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("assessments");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Red Team Review could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  it.each([
    ["conflicts", "6Conflicts"],
    ["trace", "8Trace"],
    ["actuals", "9Actuals"],
  ])("tab URL /%s: header, that tab selected, 'Not available yet.'", async (tab, label) => {
    signedIn(["head_of_delivery"]);
    found();
    const { container } = await renderWorkspace(tab);
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(selectedTabs()).toEqual([label]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText(NOT_AVAILABLE)).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 2, name: label.slice(1) })).toBeTruthy();
    expect(screen.queryByText("[CUSTOMER]")).toBeNull();
    if (tab === "conflicts") expect(await axeViolations(container)).toEqual([]);
  });

  it("an unknown slug is the not-found page", async () => {
    signedIn(["head_of_delivery"]);
    found();
    for (const tab of ["bogus", "Gaps", "proposal"]) {
      await expect(
        WorkspaceTabPage({ params: Promise.resolve({ id: OPP_ID, tab }) }),
      ).rejects.toThrow("NEXT_NOT_FOUND");
    }
    expect(notFound).toHaveBeenCalledTimes(3);
  });

  it.each([
    undefined,
    "overview",
    "sources",
    "requirements",
    "gaps",
    "assessments",
    "estimate",
    "actuals",
  ])(
    "no access on %s: the no-access sentence and no tabs",
    async (tab) => {
      signedIn(["sales_representative"]);
      hidden();
      await renderWorkspace(tab);
      expect(screen.getByText(NO_ACCESS_TO_OPP)).toBeTruthy();
      expect(screen.queryByRole("tablist")).toBeNull();
      expect(screen.queryByText(NOT_AVAILABLE)).toBeNull();
      expect(screen.queryByText("[CUSTOMER]")).toBeNull();
    },
  );

  it("a malformed id is no access too, without calling the API", async () => {
    signedIn(["sales_representative"]);
    await renderWorkspace(undefined, "not-a-uuid");
    expect(screen.getByText(NO_ACCESS_TO_OPP)).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
    await waitFor(() => expect(apiGet).not.toHaveBeenCalled());
  });

  it("API down: the platform message and no tabs", async () => {
    signedIn(["head_of_delivery"]);
    apiGet.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace();
    expect(screen.getByText(PLATFORM_DOWN)).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("no roles: only the no-access message on every tab URL", async () => {
    signedIn([]);
    for (const tab of [undefined, "gaps"]) {
      const view = await renderWorkspace(tab);
      expect(screen.getByText(NO_ACCESS)).toBeTruthy();
      expect(screen.queryByRole("tablist")).toBeNull();
      view.unmount();
    }
    expect(apiGet).not.toHaveBeenCalled();
  });
});
