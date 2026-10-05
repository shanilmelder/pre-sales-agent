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
  async function renderWorkspace(tab?: string, id = OPP_ID, search: Record<string, string> = {}) {
    segment.current = tab ?? null;
    const page = tab
      ? await WorkspaceTabPage({
          params: Promise.resolve({ id, tab }),
          searchParams: Promise.resolve(search),
        })
      : await OpportunityPage({ params: Promise.resolve({ id }) });
    return renderPage(
      await OpportunityLayout({ children: page, params: Promise.resolve({ id }) }),
    );
  }

  /** What the Overview's summary reads get for a fresh Opportunity (by path suffix). */
  const EMPTY_READS: Record<string, unknown> = {
    "/sources": { items: [] },
    "/requirements": {
      items: [],
      extraction: null,
      can_start_extraction: false,
      can_edit_requirements: false,
    },
    "/gaps": { items: [], detection: null, can_start_detection: false, can_edit_questions: false },
    "/estimate": {
      version: null,
      draft: null,
      can_start_draft: false,
      can_accept_assumptions: false,
      can_export: false,
    },
    "/assessments": {
      run: null,
      assessments: [
        { agent: "engineering_agent", assessment: null },
        { agent: "pm_agent", assessment: null },
        { agent: "security_agent", assessment: null },
      ],
      can_start: false,
    },
    "/red-team": { review: null, run: null, can_start: false },
    "/trace": {
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
      options: { subject_types: [], actor_types: [], event_types: [] },
    },
  };

  /** The Opportunity, and the summary reads (`null`: that read fails with a 500). */
  function found(opportunity: Opportunity = OPPORTUNITY, reads: Record<string, unknown> = {}) {
    const bodies = { ...EMPTY_READS, ...reads };
    apiGet.mockImplementation(async (path: string) => {
      const suffix = Object.keys(bodies).find((key) => path.endsWith(key));
      if (suffix === undefined) {
        return { data: opportunity, response: new Response(null, { status: 200 }) };
      }
      const body = bodies[suffix];
      return body === null
        ? { response: new Response(null, { status: 500 }) }
        : { data: body, response: new Response(null, { status: 200 }) };
    });
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

  describe("Overview summary", () => {
    const uid = (n: number) => `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`;
    const finding = (n: number, severity: string, title: string) => ({
      id: uid(n),
      position: n,
      kind: "risk",
      category: "integration_harder",
      severity,
      title,
      detail: "[DETAIL]",
      argument: "[ARGUMENT]",
      requirements: [],
      lines: [],
    });
    const assessment = (
      n: number,
      agent: string,
      recommendation: string,
      confidence: string,
      findings: unknown[] = [],
    ) => ({
      id: uid(n),
      agent,
      version: 1,
      status: "current",
      run_id: uid(900),
      recommendation,
      confidence,
      confidence_basis: "[BASIS]",
      dropped_count: 0,
      created_at: "2026-10-05T09:00:00Z",
      counts: { critical: 0, high: 0, medium: 0, low: 0 },
      findings,
      effort: [],
      total_hours: 0,
    });
    const gap = (n: number, title: string, impact: string) => ({
      id: uid(n),
      title,
      category: "data_volumes",
      impact,
      status: "open",
    });
    const assumption = (n: number, wording: string, amount: number | null, accepted = false) => ({
      id: uid(n),
      kind: amount === null ? "condition" : "contingency",
      wording,
      amount_hours: amount,
      accepted_at: accepted ? "2026-10-05T09:00:00Z" : null,
      accepted_by: null,
    });
    const source = (n: number, status: string) => ({
      id: uid(n),
      kind: "document",
      filename: "rfp.pdf",
      version: 1,
      version_count: 1,
      size_bytes: 10,
      uploaded_by: { id: uid(800), name: "[MEMBER]" },
      uploaded_at: "2026-10-04T13:05:00Z",
      created_at: "2026-10-04T12:00:00Z",
      parse: { status, error_code: null },
    });
    const requirement = (n: number, classification: string) => ({
      id: uid(n),
      text: "[REQ]",
      classification,
    });
    const run = (status: string) => ({
      id: uid(900),
      status,
      created_at: "2026-10-05T09:00:00Z",
      queued_at: "2026-10-05T09:00:00Z",
      finished_at: null,
      tasks: [],
    });

    const FULL: Record<string, unknown> = {
      "/sources": { items: [source(1, "parsed"), source(2, "parsed"), source(3, "failed")] },
      "/requirements": {
        items: [
          requirement(10, "functional"),
          requirement(11, "functional"),
          requirement(12, "security"),
        ],
        extraction: { status: "succeeded", error_code: null, source_count: 3 },
        can_start_extraction: false,
        can_edit_requirements: false,
      },
      "/gaps": {
        items: [
          gap(20, "[GAP HIGH 1]", "high"),
          gap(21, "[GAP HIGH 2]", "high"),
          gap(22, "[GAP LOW]", "low"),
        ],
        detection: { status: "succeeded", error_code: null },
        can_start_detection: false,
        can_edit_questions: false,
      },
      "/estimate": {
        version: {
          id: uid(30),
          version: 2,
          status: "draft",
          totals: { effort_hours: 1332, contingency_hours: 120, total_hours: 1452 },
          counts: { total: 3, accepted: 2, not_accepted: 1 },
          assumptions: {
            conditions: [assumption(31, "[COND]", null, true)],
            contingencies: [assumption(32, "[ERP MAPPING]", 80), assumption(33, "[OK]", 40, true)],
            contingency_hours: 120,
          },
        },
        draft: null,
        can_start_draft: false,
        can_accept_assumptions: false,
        can_export: false,
      },
      "/assessments": {
        run: run("succeeded"),
        assessments: [
          {
            agent: "engineering_agent",
            assessment: assessment(40, "engineering_agent", "proceed", "high"),
          },
          {
            agent: "pm_agent",
            assessment: assessment(41, "pm_agent", "proceed_with_conditions", "medium"),
          },
          {
            agent: "security_agent",
            assessment: assessment(42, "security_agent", "do_not_proceed", "low", [
              finding(43, "high", "[SSO]"),
              finding(44, "low", "[LOW FINDING]"),
            ]),
          },
        ],
        can_start: false,
      },
      "/red-team": {
        review: {
          id: uid(50),
          version: 1,
          status: "current",
          counts: { critical: 1, high: 0, medium: 0, low: 0 },
          findings: [finding(51, "critical", "[ERP FIELDS]")],
        },
        run: { status: "succeeded", error_code: null },
        can_start: false,
      },
      "/trace": {
        items: Array.from({ length: 6 }, (_, i) => ({
          id: uid(60 + i),
          occurred_at: `2026-10-05T09:0${i}:00Z`,
          event_type: i === 0 ? "estimates.estimate_version.created" : "gaps.gap.raised",
          actor: { type: "agent", id: "a", name: `[ACTOR ${i}]` },
          subject: { type: "gaps.gap", id: uid(70 + i), version: null },
          payload: {},
        })),
        page: 1,
        page_size: 50,
        total: 6,
        options: { subject_types: [], actor_types: [], event_types: [] },
      },
    };

    const card = (name: string) => screen.getByRole("region", { name });
    const href = (tab: string) => `/opportunities/${OPP_ID}/${tab}`;

    it("Fresh: every card says nothing has happened yet; the fields stay below", async () => {
      signedIn(["presales_engineer"]);
      found();
      const { container } = await renderWorkspace();
      expect(within(card("Needs attention")).getByText("Nothing needs attention.")).toBeTruthy();
      const pipeline = card("Pipeline");
      expect(within(pipeline).getAllByText("—")).toHaveLength(3);
      expect(within(pipeline).getByRole("link", { name: /Sources/ }).getAttribute("href")).toBe(
        href("sources"),
      );
      expect(within(card("Estimate")).getByText("No Estimate yet.")).toBeTruthy();
      expect(within(card("Assessments")).getByText("No assessment yet.")).toBeTruthy();
      expect(within(card("Recent activity")).getByText("No decisions recorded yet.")).toBeTruthy();
      expect(screen.getByText("Retail")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Full: counts, totals, recommendations, ranked attention and links to each tab", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, FULL);
      const { container } = await renderWorkspace();

      const rows = within(card("Needs attention")).getAllByRole("link");
      expect(rows.map((r) => [r.textContent, r.getAttribute("href")])).toEqual([
        ["CriticalRed Team: [ERP FIELDS]Assessments", href("assessments")],
        ["HighSecurity Agent: [SSO]Assessments", href("assessments")],
        ["High impactOpen Gap: [GAP HIGH 1]Gaps", href("gaps")],
        ["High impactOpen Gap: [GAP HIGH 2]Gaps", href("gaps")],
        ["Unaccepted Assumption: [ERP MAPPING] — 80.0 hEstimate", href("estimate")],
      ]);

      const pipeline = card("Pipeline");
      expect(
        within(pipeline).getByRole("link", { name: /Sources\s*3\s*2 of 3 parsed, 1 failed/ }),
      ).toBeTruthy();
      expect(within(card("Needs attention")).getByRole("img", { name: "5 items" })).toBeTruthy();
      expect(
        within(pipeline).getByRole("link", { name: /Requirements\s*3\s*2 Functional · 1 Security/ }),
      ).toBeTruthy();
      const gapsLink = within(pipeline).getByRole("link", { name: /Open Gaps\s*3\s*2 high impact/ });
      expect(gapsLink.getAttribute("href")).toBe(href("gaps"));

      const estimate = card("Estimate v2");
      expect(within(estimate).getByText("Draft")).toBeTruthy();
      expect(within(estimate).getByText("1332.0 h")).toBeTruthy();
      expect(within(estimate).getByText("120.0 h")).toBeTruthy();
      expect(within(estimate).getByText("1452.0 h")).toBeTruthy();
      expect(estimate.textContent).toContain("Assumptions32 accepted · 1 not accepted");
      expect(
        within(estimate).getByRole("link", { name: /Open Estimate/ }).getAttribute("href"),
      ).toBe(href("estimate"));

      const assessments = card("Assessments");
      expect(within(assessments).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        "Engineering AgentProceedHigh confidence",
        "PM AgentProceed with conditionsMedium confidence",
        "Security AgentDo not proceedLow confidence",
        "Red Team1 critical · 0 high",
      ]);
      expect(within(assessments).queryByText("Assessing")).toBeNull();

      const activity = card("Recent activity");
      const events = within(activity).getAllByRole("listitem");
      expect(events).toHaveLength(5);
      expect(events[0].textContent).toContain("[ACTOR 0]");
      expect(events[0].textContent).toContain("Estimate Version created");
      expect(
        within(activity).getByRole("link", { name: /Open Trace/ }).getAttribute("href"),
      ).toBe(href("trace"));
      // Read-only: no Submit.
      expect(screen.queryByRole("button", { name: /Submit/ })).toBeNull();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Cut: 8 rows and '+N more' linking to the tab", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, {
        "/gaps": {
          items: Array.from({ length: 12 }, (_, i) => gap(100 + i, `[G${i}]`, "high")),
          detection: { status: "succeeded", error_code: null },
          can_start_detection: false,
          can_edit_questions: false,
        },
      });
      const { container } = await renderWorkspace();
      const attention = card("Needs attention");
      expect(within(attention).getAllByRole("listitem")).toHaveLength(8);
      expect(within(attention).getByRole("link", { name: "+4 more" }).getAttribute("href")).toBe(
        href("gaps"),
      );
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Partial failure: only the Estimate card says it could not be loaded", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { ...FULL, "/estimate": null });
      const error = vi.spyOn(console, "error").mockImplementation(() => {});
      const { container } = await renderWorkspace();
      expect(
        within(card("Estimate")).getByText(
          "The Estimate could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(within(card("Assessments")).getByText("Proceed")).toBeTruthy();
      expect(within(card("Pipeline")).getByText("2 of 3 parsed, 1 failed")).toBeTruthy();
      const attention = card("Needs attention");
      expect(within(attention).getByText("Red Team: [ERP FIELDS]")).toBeTruthy();
      expect(
        within(attention).getByText(
          "Some items could not be loaded, so this list may be incomplete.",
        ),
      ).toBeTruthy();
      // Logged with the status only.
      expect(error).toHaveBeenCalledWith("GET estimate failed: status=500");
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Partial failure: Sources", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { ...FULL, "/sources": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(
        within(card("Pipeline")).getByText("Sources could not be loaded. Try again in a moment."),
      ).toBeTruthy();
      expect(within(card("Pipeline")).getByText("2 high impact")).toBeTruthy();
      expect(within(card("Estimate v2")).getByText("1452.0 h")).toBeTruthy();
      expect(within(card("Needs attention")).getByText("Red Team: [ERP FIELDS]")).toBeTruthy();
    });

    it("Partial failure: Red Team", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { ...FULL, "/red-team": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      const assessments = card("Assessments");
      expect(
        within(assessments).getByText(
          "The Red Team Review could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(within(assessments).getByText("Do not proceed")).toBeTruthy();
      const attention = card("Needs attention");
      expect(within(attention).queryByText("Red Team: [ERP FIELDS]")).toBeNull();
      expect(within(attention).getByText("Security Agent: [SSO]")).toBeTruthy();
      expect(
        within(attention).getByText(
          "Some items could not be loaded, so this list may be incomplete.",
        ),
      ).toBeTruthy();
      expect(within(card("Estimate v2")).getByText("1452.0 h")).toBeTruthy();
    });

    it("Partial failure: Specialist Assessments and Red Team", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { ...FULL, "/assessments": null, "/red-team": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(
        within(card("Assessments")).getByText(
          "The Assessments could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(within(card("Needs attention")).getByText("Open Gap: [GAP HIGH 1]")).toBeTruthy();
      expect(within(card("Pipeline")).getByText("2 of 3 parsed, 1 failed")).toBeTruthy();
      expect(within(card("Estimate v2")).getByText("1452.0 h")).toBeTruthy();
    });

    it("Partial failure: Trace", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { ...FULL, "/trace": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(
        within(card("Recent activity")).getByText(
          "The recent activity could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(within(card("Assessments")).getByText("Proceed")).toBeTruthy();
      expect(within(card("Estimate v2")).getByText("1452.0 h")).toBeTruthy();
    });

    it("Partial failure: Gaps with nothing else to attend to says the list may be incomplete", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, { "/gaps": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      const attention = card("Needs attention");
      expect(
        within(attention).getByText(
          "Some items could not be loaded, so this list may be incomplete.",
        ),
      ).toBeTruthy();
      expect(within(attention).queryByText("Nothing needs attention.")).toBeNull();
      expect(
        within(card("Pipeline")).getByText("Open Gaps could not be loaded. Try again in a moment."),
      ).toBeTruthy();
      expect(within(card("Estimate")).getByText("No Estimate yet.")).toBeTruthy();
    });

    it("Running: the run status alongside the current results", async () => {
      signedIn(["presales_engineer"]);
      const current = FULL["/assessments"] as Record<string, unknown>;
      found(OPPORTUNITY, { ...FULL, "/assessments": { ...current, run: run("running") } });
      const { container } = await renderWorkspace();
      const assessments = card("Assessments");
      expect(within(assessments).getByText("Assessing")).toBeTruthy();
      expect(within(assessments).getByText("Do not proceed")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Running: a Red Team run says so", async () => {
      signedIn(["presales_engineer"]);
      const current = FULL["/red-team"] as Record<string, unknown>;
      found(OPPORTUNITY, {
        ...FULL,
        "/red-team": { ...current, run: { status: "running", error_code: null } },
      });
      await renderWorkspace();
      const assessments = card("Assessments");
      expect(within(assessments).getByText("Red Team reviewing")).toBeTruthy();
      expect(within(assessments).getByText("1 critical · 0 high")).toBeTruthy();
    });

    it("Pipeline: a first extraction running or a failed detection is not zero", async () => {
      signedIn(["presales_engineer"]);
      found(OPPORTUNITY, {
        "/requirements": {
          items: [],
          extraction: { status: "running", error_code: null, source_count: 1 },
          can_start_extraction: false,
          can_edit_requirements: false,
        },
        "/gaps": {
          items: [],
          detection: { status: "failed", error_code: "model_timeout" },
          can_start_detection: false,
          can_edit_questions: false,
        },
      });
      await renderWorkspace();
      const pipeline = card("Pipeline");
      expect(
        within(pipeline).getByRole("link", { name: /Requirements\s*—\s*Extracting…/ }),
      ).toBeTruthy();
      expect(within(pipeline).getByRole("link", { name: /Open Gaps\s*—\s*Failed/ })).toBeTruthy();
      expect(within(pipeline).queryByText("0")).toBeNull();
    });

    it("Who: a sales representative sees the same read-only summary", async () => {
      signedIn(["sales_representative"]);
      found(OPPORTUNITY, FULL);
      const { container } = await renderWorkspace();
      expect(within(card("Needs attention")).getAllByRole("listitem")).toHaveLength(5);
      expect(within(card("Estimate v2")).getByText("1452.0 h")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Run assessment" })).toBeNull();
      expect(await axeViolations(container)).toEqual([]);
    });
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
      can_export: false,
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
      can_export: true,
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
            status: "approved",
            status_changed_at: "2026-10-05T09:00:00Z",
            row_version: 2,
            approved_by: { id: "00000000-0000-7000-8000-0000000000f3", name: "[OWNER]" },
            approved_at: "2026-10-05T09:00:00Z",
            edited_by_human: false,
            last_changed_by: { id: "00000000-0000-7000-8000-0000000000f3", name: "[OWNER]" },
          },
        },
      ],
      detection: { status: "succeeded", error_code: null },
      can_start_detection: false,
      can_edit_questions: false,
    });
    const { container } = await renderWorkspace("gaps");
    expect(selectedTabs()).toEqual(["4Gaps"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Gaps" })).toBeTruthy();
    expect(within(panel).getByRole("row").textContent).toBe("HighIntegration details[GAP]Approved");
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/gaps", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /gaps: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithGaps({
      items: [],
      detection: null,
      can_start_detection: true,
      can_edit_questions: true,
    });
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

  const NO_ASSESSMENTS = {
    run: null,
    assessments: [
      { agent: "engineering_agent", assessment: null },
      { agent: "pm_agent", assessment: null },
      { agent: "security_agent", assessment: null },
    ],
    can_start: false,
  };

  function reply(body: unknown) {
    return body
      ? { data: body, response: new Response(null, { status: 200 }) }
      : { response: new Response(null, { status: 500 }) };
  }

  function foundWithRedTeam(
    body: unknown,
    assessments: unknown = NO_ASSESSMENTS,
    estimate: unknown = EMPTY_READS["/estimate"],
    requirements: unknown = EMPTY_READS["/requirements"],
  ) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/red-team")
        ? reply(body)
        : path.endsWith("/assessments")
          ? reply(assessments)
          : path.endsWith("/estimate")
            ? reply(estimate)
            : path.endsWith("/requirements")
              ? reply(requirements)
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
    expect(
      within(panel).getByRole("heading", { level: 3, name: "Specialist Assessments" }),
    ).toBeTruthy();
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
    foundWithRedTeam(
      { review: null, run: null, can_start: true },
      { ...NO_ASSESSMENTS, can_start: true },
    );
    await renderWorkspace("assessments");
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("The Red Team reviews the Opportunity after the Estimate is drafted."),
    ).toBeTruthy();
    expect(
      within(panel).getByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Run assessment" })).toBeTruthy();
  });

  it("tab URL /assessments: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithRedTeam(null, null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("assessments");
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("The Red Team Review could not be loaded. Try again in a moment."),
    ).toBeTruthy();
    expect(
      within(panel).getByText(
        "The Specialist Assessments could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
    expect(
      within(panel).getByText("The Effort comparison could not be loaded. Try again in a moment."),
    ).toBeTruthy();
  });

  describe("tab URL /assessments: Effort comparison", () => {
    const R1_ID = "00000000-0000-7000-8000-0000000000f1";
    const R2_ID = "00000000-0000-7000-8000-0000000000f2";
    const REQUIREMENTS = {
      items: [
        { id: R1_ID, text: "[REQ ONE]", classification: "integration", version: 1 },
        { id: R2_ID, text: "[REQ TWO]", classification: "security", version: 1 },
      ],
      extraction: null,
      can_start_extraction: false,
      can_edit_requirements: false,
    };
    const chip = (id: string) => ({ id, version: 1, label: "R1", excerpt: "[EXCERPT]" });
    const assessment = (agent: string, effort: [string, number][]) => ({
      agent,
      assessment: {
        id: `00000000-0000-7000-8000-0000000001${agent.length}0`,
        agent,
        version: 1,
        status: "current",
        run_id: "00000000-0000-7000-8000-0000000000b1",
        recommendation: "proceed",
        confidence: "high",
        confidence_basis: "[BASIS]",
        dropped_count: 0,
        created_at: "2026-10-05T09:00:00Z",
        counts: { critical: 0, high: 0, medium: 0, low: 0 },
        findings: [],
        effort: effort.map(([id, hours]) => ({ requirement: chip(id), hours, basis: "[WHY]" })),
        total_hours: effort.reduce((sum, [, h]) => sum + h, 0),
      },
    });
    const ASSESSMENTS = {
      run: null,
      assessments: [
        assessment("engineering_agent", [[R1_ID, 20]]),
        assessment("pm_agent", [[R1_ID, 10]]),
        assessment("security_agent", [[R1_ID, 4]]),
      ],
      can_start: false,
    };
    const ESTIMATE = {
      version: {
        id: "00000000-0000-7000-8000-0000000000d1",
        version: 1,
        status: "draft",
        sections: [
          {
            section: "functional",
            lines: [
              { id: "l1", effort_hours: 30, requirements: [chip(R1_ID)] },
              { id: "l2", effort_hours: 12, requirements: [] },
            ],
          },
        ],
      },
      draft: null,
      can_start_draft: false,
      can_accept_assumptions: false,
      can_export: false,
    };
    const RED_TEAM = { review: null, run: null, can_start: false };

    it("sits between Specialist Assessments and the Red Team, for any reader", async () => {
      signedIn(["sales_representative"]);
      foundWithRedTeam(RED_TEAM, ASSESSMENTS, ESTIMATE, REQUIREMENTS);
      const { container } = await renderWorkspace("assessments");
      const panel = screen.getByRole("tabpanel");
      const headings = within(panel)
        .getAllByRole("heading", { level: 3 })
        .map((h) => h.textContent);
      const at = (name: string) => headings.indexOf(name);
      expect(at("Specialist Assessments")).toBeGreaterThanOrEqual(0);
      expect(at("Effort comparison")).toBe(at("Specialist Assessments") + 1);
      expect(at("Red Team")).toBe(at("Effort comparison") + 1);

      const table = within(panel).getByRole("table", {
        name: "Effort comparison by Requirement, in hours",
      });
      const r1 = within(table).getByRole("row", { name: /R1 \[REQ ONE\]/ });
      expect(within(r1).getAllByRole("cell").map((c) => c.textContent)).toEqual([
        "20.0",
        "10.0",
        "4.0",
        "34.0",
        "30.0",
        "−4.0",
      ]);
      expect(within(table).getByText("Not linked to a Requirement: 12.0 h")).toBeTruthy();
      expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/estimate", {
        params: { path: { opportunity_id: OPP_ID } },
      });
      expect(apiGet).toHaveBeenCalledWith(
        "/api/v1/opportunities/{opportunity_id}/requirements",
        { params: { path: { opportunity_id: OPP_ID } } },
      );
      expect(await axeViolations(container)).toEqual([]);
    });

    it("a failed Estimate read: the table without the Estimate columns, and it says so", async () => {
      signedIn(["presales_engineer"]);
      foundWithRedTeam(RED_TEAM, ASSESSMENTS, null, REQUIREMENTS);
      const error = vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace("assessments");
      const panel = screen.getByRole("tabpanel");
      expect(
        within(panel).getByText("The Estimate could not be loaded, so its hours are not shown."),
      ).toBeTruthy();
      const table = within(panel).getByRole("table", {
        name: "Effort comparison by Requirement, in hours",
      });
      expect(within(table).queryByRole("columnheader", { name: "Estimate (allocated)" })).toBeNull();
      expect(within(table).queryByRole("columnheader", { name: "Difference" })).toBeNull();
      expect(within(table).getByRole("columnheader", { name: "Agents total" })).toBeTruthy();
      // Logged with the status only.
      expect(error).toHaveBeenCalledWith("GET estimate failed: status=500");
    });

    it("a failed Requirements read says the comparison could not be loaded", async () => {
      signedIn(["presales_engineer"]);
      foundWithRedTeam(RED_TEAM, ASSESSMENTS, ESTIMATE, null);
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace("assessments");
      const panel = screen.getByRole("tabpanel");
      expect(
        within(panel).getByText(
          "The Effort comparison could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(within(panel).queryByRole("table", { name: /Effort comparison/ })).toBeNull();
    });

    it("the empty state", async () => {
      signedIn(["presales_engineer"]);
      foundWithRedTeam(RED_TEAM, NO_ASSESSMENTS, EMPTY_READS["/estimate"], REQUIREMENTS);
      await renderWorkspace("assessments");
      expect(
        within(screen.getByRole("tabpanel")).getByText("No effort to compare yet."),
      ).toBeTruthy();
    });
  });

  const TRACE_PAGE = {
    page: 1,
    page_size: 50,
    total: 2,
    options: {
      subject_types: ["assessments.review", "opportunities.opportunity"],
      actor_types: ["agent", "user"],
      event_types: ["assessments.red_team_review.completed", "opportunities.opportunity.created"],
    },
    items: [
      {
        id: "00000000-0000-7000-8000-0000000000e1",
        occurred_at: "2026-10-05T09:00:00Z",
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
        payload: { version: 1, finding_count: 3 },
      },
      {
        id: "00000000-0000-7000-8000-0000000000e2",
        occurred_at: "2026-10-04T10:00:00Z",
        event_type: "opportunities.opportunity.created",
        actor: { type: "user", id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" },
        subject: { type: "opportunities.opportunity", id: OPP_ID, version: 1 },
        payload: {},
      },
    ],
  };

  function foundWithTrace(body: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/trace")
        ? body
          ? { data: body, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /trace: the Decision Trace newest first, read-only", async () => {
    signedIn(["sales_representative"]);
    foundWithTrace(TRACE_PAGE);
    const { container } = await renderWorkspace("trace");
    expect(selectedTabs()).toEqual(["8Trace"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Trace" })).toBeTruthy();
    const rows = within(panel).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Red Team AgentRed Team Review completed"),
      expect.stringContaining("[OWNER]Opportunity created"),
    ]);
    expect(
      within(panel).getByRole("link", { name: "Red Team Review v1" }).getAttribute("href"),
    ).toBe(`/opportunities/${OPP_ID}/assessments`);
    expect(within(panel).getByText("Page 1 of 1")).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/trace", {
      params: { path: { opportunity_id: OPP_ID }, query: { page: 1, page_size: 50 } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /trace?actor=agent: the filters and page come from the URL", async () => {
    signedIn(["presales_engineer"]);
    foundWithTrace({ ...TRACE_PAGE, page: 2, total: 52, items: TRACE_PAGE.items.slice(0, 1) });
    await renderWorkspace("trace", OPP_ID, { actor: "agent", page: "2" });
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/trace", {
      params: {
        path: { opportunity_id: OPP_ID },
        query: { page: 2, page_size: 50, actor_type: "agent" },
      },
    });
    const actor = screen.getByLabelText("Actor") as HTMLSelectElement;
    expect(actor.value).toBe("agent");
    expect(actor.selectedOptions[0].textContent).toBe("Agent");
    expect(screen.getByText("Page 2 of 2")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Previous" }).getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/trace?actor=agent`,
    );
    expect(screen.queryByRole("link", { name: "Next" })).toBeNull();
  });

  it("tab URL /trace: past the last page goes to the last one", async () => {
    signedIn(["presales_engineer"]);
    foundWithTrace({ ...TRACE_PAGE, page: 9, total: 52, items: [] });
    await expect(renderWorkspace("trace", OPP_ID, { event: "x.y.z", page: "9" })).rejects.toThrow(
      `NEXT_REDIRECT /opportunities/${OPP_ID}/trace?event=x.y.z&page=2`,
    );
  });

  it("tab URL /trace: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithTrace({
      ...TRACE_PAGE,
      total: 0,
      items: [],
      options: { subject_types: [], actor_types: [], event_types: [] },
    });
    await renderWorkspace("trace");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("No decisions recorded yet.")).toBeTruthy();
    expect(within(panel).queryByRole("group", { name: "Filters" })).toBeNull();
  });

  it("tab URL /trace: a failed read says so", async () => {
    signedIn(["head_of_delivery"]);
    foundWithTrace(null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("trace");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Decision Trace could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  it.each([
    ["conflicts", "6Conflicts"],
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
    "trace",
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
