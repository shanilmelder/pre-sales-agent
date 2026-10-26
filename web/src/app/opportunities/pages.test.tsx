import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { permissionsFor } from "@/test/permissions";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { dueSoonFilters } from "@/app/opportunities/filters";
import { utcToday } from "@/lib/opportunities";
import type { Opportunity, OpportunitySummary } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
const resolveConflict = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("server-only", () => ({}));
// The sidebar's Inbox badge (Story 9.2) reads its count through its own server action.
vi.mock("@/app/inbox/actions", () => ({
  getInboxUnreadCount: async () => ({ kind: "ok", unread: 0 }),
}));
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
  countOpenGaps: vi.fn(async () => null),
  countOpenConflicts: vi.fn(async () => null),
  countBlockingFindings: vi.fn(async () => null),
  loadSubmissionBlockers: vi.fn(async () => null),
  submitEstimateVersion: vi.fn(),
  startGapDetection: vi.fn(),
  loadEstimate: vi.fn(),
  startEstimateDraft: vi.fn(),
  loadRedTeam: vi.fn(),
  startRedTeamReview: vi.fn(),
  resolveConflict,
  escalateConflict: vi.fn(),
  loadReviewPanel: vi.fn(),
  decideReviewRequest: vi.fn(),
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
  usePathname: () => "/opportunities",
  useSelectedLayoutSegment: () => segment.current,
}));

import WorkspaceTabPage from "@/app/opportunities/[id]/[tab]/page";
import OpportunityLayout from "@/app/opportunities/[id]/layout";
import OpportunityPage from "@/app/opportunities/[id]/page";
import NewOpportunityPage from "@/app/opportunities/new/page";
import ReviewPanelPage from "@/app/opportunities/[id]/estimate/reviews/[rid]/page";
import { REVIEW_ID, reviewPanel } from "@/test/review-fixtures";
import OpportunitiesPage from "@/app/opportunities/page";
import MyOpportunitiesPage from "@/app/my-opportunities/page";
import { RightPane } from "@/components/shell/right-pane";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

/** An effort Conflict on R2 as the Conflicts read returns it (Story 6.3 fields included). */
function conflictFixture(overrides: Record<string, unknown> = {}) {
  const requirement = {
    id: "00000000-0000-7000-8000-0000000000e2",
    version: 1,
    label: "R2",
    excerpt: "[EXCERPT]",
  };
  const agent = (n: number, name: string, hours: number) => ({
    position: n,
    source: "assessment",
    agent: name,
    assessment_id: `00000000-0000-7000-8000-0000000000a${n}`,
    assessment_version: 1,
    estimate_version_id: null,
    estimate_version: null,
    summary: `${hours} h`,
    value: hours,
    requirement,
  });
  return {
    id: "00000000-0000-7000-8000-0000000000c2",
    type: "effort",
    severity: "medium",
    status: "open",
    detected_by: "rule",
    summary: "[SUMMARY]",
    run_id: "00000000-0000-7000-8000-0000000000c9",
    previous_conflict_id: null,
    resolution_reason: null,
    resolved_at: null,
    created_at: "2026-10-07T09:00:00Z",
    requirement,
    positions: [agent(1, "engineering_agent", 60), agent(2, "pm_agent", 40)],
    row_version: 1,
    resolved_by_name: null,
    chosen_position: null,
    entered_position: null,
    applied_hours: null,
    not_applied: null,
    previous_decision: null,
    escalated_to: null,
    escalated_by: null,
    escalation_reason: null,
    escalated_at: null,
    can_resolve: false,
    can_escalate: false,
    ...overrides,
  };
}

const NO_ACCESS =
  "You're signed in, but you don't have access yet. Ask an administrator to assign a role.";
const OPP_ID = "00000000-0000-7000-8000-000000000001";

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[USER]",
      email: "u@x",
      roles,
      permissions: permissionsFor(roles),
    },
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
  open_gaps: 3,
  open_conflicts: 2,
  blocker_count: 0,
  estimate: { version: 3, status: "draft", total_hours: 278 },
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
  ["/opportunities?view=mine", { view: "mine" }, "mine"],
  ["/opportunities", {}, "all"],
] as const;

describe.each(LISTS)("%s", (_path, view, scope) => {
  const title = "Opportunities";
  const Page = ({ searchParams }: { searchParams: ReturnType<typeof params> }) =>
    OpportunitiesPage({ searchParams: searchParams.then((values) => ({ ...view, ...values })) });
  const pageHref = (n: number) => `${_path}${_path.includes("?") ? "&" : "?"}page=${n}`;

  it("lists Opportunities in the shell; New Opportunity for presales engineers", async () => {
    signedIn(["presales_engineer"]);
    listed([SUMMARY]);
    const { container } = renderPage(await Page({ searchParams: params() }));

    expect(screen.getByRole("heading", { level: 1, name: title })).toBeTruthy();
    expect(screen.getByRole("link", { name: "New Opportunity" }).getAttribute("href")).toBe(
      "/opportunities/new",
    );
    // The page frame owns the 32px inset: the strips inside it add no outer gutter; the
    // list sits in its card, whose first column pads 20px at the edge.
    const views = screen.getByRole("navigation", { name: "Views" });
    expect(views.closest('[data-testid="page-content"]')).toBeTruthy();
    expect(views.className).not.toContain("gutter");
    const firstHeader = screen.getAllByRole("columnheader")[0]!;
    expect(firstHeader.closest('[data-testid="opportunities-card"]')).toBeTruthy();
    expect(firstHeader.className).toContain("pl-5");
    expect(firstHeader.className).not.toContain("gutter");
    // The header band: subtitle, then New Opportunity, then the pane toggle.
    const header = screen.getByTestId("page-header");
    expect(
      within(header).getByText(
        "Opportunities with their derived status, open items and current Estimate.",
      ),
    ).toBeTruthy();
    const action = within(header).getByRole("link", { name: "New Opportunity" });
    const toggle = within(header).getByRole("button", { name: "Right pane" });
    expect(action.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByRole("link", { name: "[TITLE]" })).toBeTruthy();
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

  it("rows show open items and the Estimate; Pagination sits below the card", async () => {
    signedIn(["presales_engineer"]);
    listed([SUMMARY], 120);
    renderPage(await Page({ searchParams: params() }));
    const link = await screen.findByRole("link", { name: "[TITLE]" });
    const row = link.closest("tr")!;
    expect(row.textContent).toContain("3 gaps · 2 conflicts");
    expect(row.textContent).toContain("278.0 h");
    expect(row.textContent).toContain("Draft v3");
    const card = screen.getByTestId("opportunities-card");
    const pagination = screen.getByRole("navigation", { name: "Pagination" });
    expect(card.contains(pagination)).toBe(false);
    const after = card.compareDocumentPosition(pagination);
    expect(after & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("an unreachable platform says so inside the list card", async () => {
    signedIn(["presales_engineer"]);
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 503 }) });
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage(await Page({ searchParams: params() }));
    quiet.mockRestore();
    const text = screen.getByText(
      "The platform is not reachable right now. Try again in a moment.",
    );
    expect(text.closest('[data-testid="opportunities-card"]')).toBeTruthy();
  });

  it("empty: the empty-state card after the skeleton, with views", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    const { container } = renderPage(await Page({ searchParams: params() }));
    expect(container.querySelector("[data-skeleton-row]")).toBeTruthy();
    expect(await screen.findByText("No Opportunities yet")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "New Opportunity" })).toHaveLength(2);
    const views = screen.getByRole("navigation", { name: "Views" });
    expect(within(views).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "All",
      "Mine",
      "Due in 14 days",
    ]);
    const current = within(views).getByRole("link", { current: "page" });
    expect(current.textContent).toBe(scope === "mine" ? "Mine" : "All");
  });

  it("paginates with Previous and Next, and redirects past the last page", async () => {
    signedIn(["presales_engineer"]);
    listed([SUMMARY], 120, 2);
    renderPage(await Page({ searchParams: params("2") }));
    expect(screen.getByText("51–51 of 120")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Previous" }).getAttribute("href")).toBe(_path);
    expect(screen.getByRole("link", { name: "Next" }).getAttribute("href")).toBe(pageHref(3));
    listed([], 120, 9);
    await expect(Page({ searchParams: params("9") })).rejects.toThrow(
      `NEXT_REDIRECT ${pageHref(3)}`,
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

describe("/my-opportunities", () => {
  it("redirects to the Mine view of Opportunities", () => {
    expect(() => MyOpportunitiesPage()).toThrow("NEXT_REDIRECT /opportunities?view=mine");
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
    const filters = screen.getByRole("group", { name: "Filters" });
    expect(within(filters).getByRole("button", { name: "Owner: [OWNER]" })).toBeTruthy();
    expect(within(filters).getByRole("button", { name: "Product: Pick station" })).toBeTruthy();
    expect(within(filters).getByRole("button", { name: "Proposal date: from 1 Nov" })).toBeTruthy();
    // One toolbar row: the views, then the filter chips.
    const views = screen.getByRole("navigation", { name: "Views" });
    expect(filters.parentElement).toBe(views.parentElement);
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe(
      "/opportunities",
    );
    expect(await screen.findByRole("link", { name: "[TITLE]" })).toBeTruthy();
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
    expect(screen.getByRole("button", { name: "Status" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
  });

  it("no matches: the filtered empty state with Clear filters, not the create one", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    renderPage(await OpportunitiesPage({ searchParams: query({ status: "closed" }) }));
    expect(await screen.findByText("No Opportunities match these filters.")).toBeTruthy();
    expect(screen.queryByText("No Opportunities yet")).toBeNull();
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

  it("the Mine view has no filter bar and ignores filter params", async () => {
    signedIn(["presales_engineer"]);
    listed([]);
    renderPage(
      await OpportunitiesPage({
        searchParams: query({ view: "mine", status: "closed", owner: OWNER_ID }),
      }),
    );
    expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities", {
      params: { query: { scope: "mine", page: 1, page_size: 50 } },
    });
    expect(await screen.findByText("No Opportunities yet")).toBeTruthy();
  });

  it("Due in 14 days is current when the range is today to today plus 14", async () => {
    signedIn(["head_of_delivery"]);
    listed([SUMMARY]);
    const { from, to } = dueSoonFilters(utcToday());
    renderPage(await OpportunitiesPage({ searchParams: query({ from: from!, to: to! }) }));
    const views = screen.getByRole("navigation", { name: "Views" });
    expect(within(views).getByRole("link", { current: "page" }).textContent).toBe("Due in 14 days");
    expect(within(views).getByRole("link", { name: "Due in 14 days" }).getAttribute("href")).toBe(
      `/opportunities?from=${from}&to=${to}`,
    );
  });
});

describe("/opportunities/new", () => {
  it("shows the form to presales engineers", async () => {
    signedIn(["presales_engineer"]);
    const { container } = renderPage(await NewOpportunityPage());
    expect(screen.getByRole("heading", { level: 1, name: "New Opportunity" })).toBeTruthy();
    expect(screen.getByLabelText("Customer name")).toBeTruthy();
    // The header's Create Opportunity submits the form below it.
    const create = within(screen.getByTestId("page-header")).getByRole("button", {
      name: "Create Opportunity",
    });
    expect(create.getAttribute("type")).toBe("submit");
    const form = document.getElementById(create.getAttribute("form")!);
    expect(form?.tagName).toBe("FORM");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tells other roles they can't create", async () => {
    signedIn(["head_of_delivery"]);
    renderPage(await NewOpportunityPage());
    expect(screen.getByText("You don't have access to create Opportunities.")).toBeTruthy();
    expect(screen.queryByLabelText("Customer name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create Opportunity" })).toBeNull();
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

  /** A Story 8.6 blocker of `kind` whose subject id is its title (so its link is checkable). */
  function blocker(kind: string, title: string) {
    const tabs: Record<string, string> = {
      gap: "gaps",
      assumption: "estimate",
      conflict: "conflicts",
      finding: "assessments",
      uncovered_requirement: "requirements",
    };
    const anchor = kind === "uncovered_requirement" ? "requirement" : kind;
    return {
      kind,
      subject_id: title,
      title,
      detail: `${title} detail`,
      href: `/opportunities/${OPP_ID}/${tabs[kind]}#${anchor}-${title}`,
    };
  }

  /** `GET …/submission-blockers` with these blockers, on draft v3 the caller may submit. */
  function blockersView(toSubmit: unknown[], canSubmit: boolean) {
    return {
      to_submit: toSubmit,
      to_baseline: [],
      version: {
        id: "00000000-0000-7000-8000-0000000000e3",
        version: 3,
        status: "draft",
        row_version: 1,
        created_at: "2026-10-04T10:00:00Z",
        submitted_at: null,
      },
      can_submit: canSubmit,
    };
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
    "/conflicts": { conflicts: [], open_count: 0 },
    "/submission-blockers": { to_submit: [], to_baseline: [], version: null, can_submit: false },
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
    expect(selectedTabs()).toEqual(["Overview"]);
    const panel = screen.getByRole("tabpanel", { name: "Overview" });
    // Overview: status, owner, collaborators, created date, customer, products, industry.
    expect(within(panel).getByText("Intake")).toBeTruthy();
    expect(within(panel).getByText("[OWNER]")).toBeTruthy();
    expect(within(panel).getByText("[MEMBER]")).toBeTruthy();
    expect(within(panel).getByText("4 Oct 2026")).toBeTruthy();
    expect(within(panel).getByText("[CUSTOMER]")).toBeTruthy();
    expect(within(panel).getByText("Pick station")).toBeTruthy();
    expect(within(panel).getByText("Retail")).toBeTruthy();
    // The tab's page frame lines up with the 32px header band: 28/32/40.
    const frame = panel.querySelector("fieldset > div")!;
    for (const cls of ["px-page", "pt-7", "pb-10"]) expect(frame.className).toContain(cls);
    expect(frame.className).not.toContain("p-gutter");
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
    expect(selectedTabs()).toEqual(["Overview"]);
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
    const finding = (n: number, severity: string, title: string, requirements: unknown[] = []) => ({
      id: uid(n),
      position: n,
      kind: "risk",
      category: "integration_harder",
      severity,
      title,
      detail: "[DETAIL]",
      argument: "[ARGUMENT]",
      requirements,
      lines: [],
    });
    const assessment = (
      n: number,
      agent: string,
      recommendation: string,
      confidence: string,
      findings: unknown[] = [],
      createdAt = "2026-10-05T09:00:00Z",
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
      created_at: createdAt,
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
    const requirement = (n: number, confirmed: boolean) => ({
      id: uid(n),
      number: n,
      text: "[REQ]",
      classification: "functional",
      confirmed_at: confirmed ? "2026-10-05T09:00:00Z" : null,
    });
    const task = (agent: string, status: string, errorCode: string | null = null) => ({
      agent,
      status,
      error_code: errorCode,
      skip_reason: null,
      started_at: null,
      finished_at: null,
    });
    const run = (status: string, tasks: unknown[] = []) => ({
      id: uid(900),
      status,
      created_at: "2026-10-05T09:31:00Z",
      queued_at: "2026-10-05T09:31:00Z",
      finished_at: null,
      tasks,
    });
    const estimateView = (notAccepted: boolean, uncovered = 1) => ({
      version: {
        id: uid(30),
        version: 3,
        status: "draft",
        uncovered_count: uncovered,
        source: "assessments",
        source_run: 2,
        totals: {
          effort_hours: 250,
          contingency_hours: 28,
          total_hours: 278,
          role_hours: { engineer: 225.4, project_manager: 52.6, qa: 0 },
        },
        counts: notAccepted
          ? { total: 3, accepted: 1, not_accepted: 2 }
          : { total: 1, accepted: 1, not_accepted: 0 },
        assumptions: {
          conditions: [assumption(31, "[COND]", null, true)],
          contingencies: notAccepted
            ? [assumption(32, "[ERP MAPPING]", 80), assumption(33, "[HOSTING]", null)]
            : [],
          contingency_hours: 28,
        },
      },
      draft: null,
      can_start_draft: false,
      can_accept_assumptions: false,
      can_export: false,
    });
    const RUNNING_TASKS = [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "running"),
      task("security_agent", "queued"),
    ];

    /** The matrix's mid-way Opportunity: 6 Sources parsed, 9 of 12 confirmed, 3 open Gaps (2
     * High), 2 open Conflicts, Estimate v3 draft. */
    const MID: Record<string, unknown> = {
      // Story 8.6: the API's one check, as the Overview card and the header read it.
      "/submission-blockers": blockersView(
        [
          ...["[GAP HIGH 1]", "[GAP HIGH 2]", "[GAP MEDIUM]"].map((t) => blocker("gap", t)),
          ...["[ERP MAPPING]", "[CONDITION]"].map((t) => blocker("assumption", t)),
          ...["[CONFLICT 1]", "[CONFLICT 2]"].map((t) => blocker("conflict", t)),
          blocker("uncovered_requirement", "R12 not covered"),
        ],
        true,
      ),
      "/sources": { items: Array.from({ length: 6 }, (_, i) => source(1 + i, "parsed")) },
      "/requirements": {
        items: Array.from({ length: 12 }, (_, i) => requirement(10 + i, i < 9)),
        extraction: { status: "succeeded", error_code: null, source_count: 6 },
        can_start_extraction: false,
        can_edit_requirements: false,
      },
      "/gaps": {
        items: [
          gap(40, "[GAP HIGH 1]", "high"),
          gap(41, "[GAP HIGH 2]", "high"),
          gap(42, "[GAP MEDIUM]", "medium"),
        ],
        detection: { status: "succeeded", error_code: null },
        can_start_detection: false,
        can_edit_questions: false,
      },
      "/estimate": estimateView(true),
      "/assessments": {
        run: run("running", RUNNING_TASKS),
        assessments: [
          {
            agent: "engineering_agent",
            assessment: assessment(50, "engineering_agent", "proceed", "high"),
          },
          {
            agent: "pm_agent",
            assessment: assessment(51, "pm_agent", "proceed_with_conditions", "medium"),
          },
          {
            agent: "security_agent",
            assessment: assessment(
              52,
              "security_agent",
              "do_not_proceed",
              "low",
              [
                finding(53, "high", "[SSO]", [
                  { id: uid(10), version: 1, label: "R10", excerpt: "[E]" },
                ]),
                finding(54, "low", "[LOW FINDING]"),
              ],
              "2026-10-05T10:00:00Z",
            ),
          },
        ],
        can_start: false,
      },
      "/red-team": {
        review: {
          id: uid(60),
          version: 1,
          status: "current",
          counts: { critical: 1, high: 0, medium: 0, low: 0 },
          findings: [finding(61, "critical", "[ERP FIELDS]")],
        },
        run: { status: "succeeded", error_code: null },
        can_start: false,
      },
      "/conflicts": {
        conflicts: [
          conflictFixture(),
          conflictFixture({
            id: uid(70),
            status: "escalated",
            escalated_to: { id: uid(71), name: "Sam" },
          }),
          conflictFixture({ id: uid(72), status: "resolved" }),
        ],
        open_count: 2,
        reviewers: [],
      },
      "/trace": {
        items: Array.from({ length: 6 }, (_, i) => ({
          id: uid(80 + i),
          occurred_at: `2026-10-05T09:0${i}:00Z`,
          event_type: i === 0 ? "estimates.estimate_version.created" : "gaps.gap.raised",
          actor:
            i === 1
              ? { type: "user", id: "u", name: "Sam Delivery" }
              : { type: "agent", id: "a", name: `Red Team ${i}` },
          subject: { type: "gaps.gap", id: uid(90 + i), version: null },
          payload: {},
        })),
        page: 1,
        page_size: 50,
        total: 6,
        options: { subject_types: [], actor_types: [], event_types: [] },
      },
    };
    const FUTURE = { ...OPPORTUNITY, target_proposal_date: "2099-01-01" };

    const card = (name: string) => screen.getByRole("region", { name });
    const href = (tab: string) => `/opportunities/${OPP_ID}/${tab}`;
    const kpi = (name: RegExp) => screen.getByRole("link", { name });
    const stepStates = () =>
      Array.from(card("Submission pipeline").querySelectorAll("li[data-step-state]")).map((li) =>
        li.getAttribute("data-step-state"),
      );

    it("New Opportunity: KPIs '—', every step pending, nothing needs you, no decision or run", async () => {
      signedIn(["presales_engineer"]);
      found();
      const { container } = await renderWorkspace();
      for (const [name, tab] of [
        [/^Requirements confirmed\s*—$/, "requirements"],
        [/^Open Gaps\s*—$/, "gaps"],
        [/^Open Conflicts\s*—$/, "conflicts"],
        [/^Estimate\s*—\s*No Estimate yet\.$/, "estimate"],
      ] as const)
        expect(kpi(name).getAttribute("href")).toBe(href(tab));
      expect(stepStates()).toEqual(Array(8).fill("pending"));
      expect(within(card("Submission pipeline")).getAllByText("Pending")).toHaveLength(8);
      expect(within(card("Submission pipeline")).getByText("0 of 8 steps complete")).toBeTruthy();
      expect(within(card("Needs you")).getByText("Nothing needs attention.")).toBeTruthy();
      expect(within(card("Needs you")).getByText("In your queue").textContent).toBe(
        "In your queue 0",
      );
      expect(within(card("Submission blockers")).getByText("0 blockers")).toBeTruthy();
      expect(within(card("Recent activity")).getByText("No decisions recorded yet.")).toBeTruthy();
      expect(screen.queryByRole("region", { name: "Latest agent decision" })).toBeNull();
      expect(screen.queryByRole("region", { name: "Agent run" })).toBeNull();
      const details = card("Details");
      expect(within(details).getByText("Retail")).toBeTruthy();
      expect(within(details).getByRole("heading", { name: "People" })).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Mid-way: the mockup's numbers, in the mockup's order, each linking to its tab", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, MID);
      const { container } = await renderWorkspace();

      // KPI row.
      expect(
        kpi(/^Requirements confirmed\s*9\s*of 12\s*3 awaiting confirmation$/).getAttribute("href"),
      ).toBe(href("requirements"));
      expect(kpi(/^Open Gaps\s*3\s*2 High\s*1 Medium\s*0 Low$/).getAttribute("href")).toBe(
        href("gaps"),
      );
      expect(
        kpi(/^Open Conflicts\s*2\s*Blocks submit\s*1 escalated$/).getAttribute("href"),
      ).toBe(href("conflicts"));
      expect(
        kpi(
          /^Estimate · v3 draft\s*278\.0\s*h\s*Engineer 225\.4 h · PM 52\.6 h\s*From Assessments run 2$/,
        ).getAttribute("href"),
      ).toBe(href("estimate"));

      // The cards in the mockup's order.
      const regions = screen
        .getAllByRole("region")
        .map((r) => r.querySelector("h3")?.textContent)
        .filter(Boolean);
      expect(regions).toEqual([
        "Submission pipeline",
        "Needs you",
        "Submission blockers",
        "Recent activity",
        "Latest agent decision",
        "Agent run",
        "Details",
      ]);

      // Submission pipeline.
      const pipeline = card("Submission pipeline");
      expect(stepStates()).toEqual([
        "complete",
        "complete",
        "in-progress",
        "blocked",
        "in-progress",
        "blocked",
        "blocked",
        "pending",
      ]);
      expect(within(pipeline).getByText("6 of 6 parsed")).toBeTruthy();
      expect(within(pipeline).getByText("9 of 12")).toBeTruthy();
      expect(within(pipeline).getByText("3 open, 2 High")).toBeTruthy();
      expect(within(pipeline).getByText("2 open")).toBeTruthy();
      expect(within(pipeline).getByText("2 Assumptions not accepted")).toBeTruthy();
      expect(within(pipeline).getByText("Starts when blockers clear")).toBeTruthy();
      expect(within(pipeline).getByText(/^Proposal due in \d+ days$/)).toBeTruthy();
      expect(within(pipeline).getByText("2 of 8 steps complete")).toBeTruthy();
      expect(within(pipeline).getByText("3 steps blocked")).toBeTruthy();
      expect(
        within(pipeline).getByRole("link", { name: "Conflicts resolved" }).getAttribute("href"),
      ).toBe(href("conflicts"));

      // Needs you: ranked, each with a state line and an action to its tab.
      const needs = card("Needs you");
      const rows = within(needs).getAllByRole("listitem");
      expect(rows.map((r) => r.getAttribute("data-kind"))).toEqual([
        "critical-finding",
        "escalated-conflict",
        "high-finding",
        "gap",
        "gap",
        "assumption",
        "assumption",
      ]);
      expect(rows[0].className).toContain("bg-blocker-tint");
      expect(rows[0].textContent).toBe("Red Team: [ERP FIELDS]CriticalReview");
      for (const [name, tab] of [
        ["Review Red Team: [ERP FIELDS]", "assessments"],
        ["Resolve Effort Conflict on R2 escalated to Sam", "conflicts"],
        ["Review Security Agent: [SSO]", "assessments"],
        ["Resolve Open Gap: [GAP HIGH 1]", "gaps"],
        ["Open Unaccepted Assumption: [ERP MAPPING] — 80.0 h", "estimate"],
      ])
        expect(within(needs).getByRole("link", { name }).getAttribute("href")).toBe(href(tab));
      expect(within(needs).getByText("7 items")).toBeTruthy();
      expect(within(needs).getByText("In your queue").textContent).toBe("In your queue 7");

      // Submission blockers: the API's check, one row per kind, each subject a link.
      const blockersCard = card("Submission blockers");
      expect(within(blockersCard).getByText("8 to submit · 0 to Baseline")).toBeTruthy();
      const blockerRows = Array.from(
        blockersCard.querySelectorAll<HTMLElement>("[data-blocker]"),
      );
      expect(blockerRows.map((r) => r.getAttribute("data-blocker"))).toEqual([
        "gap",
        "assumption",
        "conflict",
        "uncovered_requirement",
      ]);
      expect(blockerRows[0].textContent).toContain("3 open Gaps");
      const gapRow = within(blockerRows[0]!);
      expect(gapRow.getByRole("link", { name: "Open Gaps" }).getAttribute("href")).toBe(
        href("gaps"),
      );
      expect(gapRow.getByRole("link", { name: "[GAP HIGH 1]" }).getAttribute("href")).toBe(
        `${href("gaps")}#gap-[GAP HIGH 1]`,
      );
      expect(blockerRows[1].textContent).toContain("2 Assumptions not accepted");
      expect(blockerRows[2].textContent).toContain("2 open Conflicts");
      expect(blockerRows[3].textContent).toContain("1 Requirement not covered");
      expect(within(blockersCard).getByText("No Review Request sent yet")).toBeTruthy();
      expect(within(blockersCard).queryByText(/ready to submit/)).toBeNull();
      // The header: an aria-disabled Submit with its reason, and Resolve 8 blockers.
      const submit = screen.getByRole("button", { name: "Submit" });
      expect(submit.getAttribute("aria-disabled")).toBe("true");
      expect(screen.getAllByText("Resolve 8 blockers to submit").length).toBeGreaterThan(0);
      expect(
        screen.getByRole("link", { name: "Resolve 8 blockers" }).getAttribute("href"),
      ).toBe(`${href("overview")}#overview-blockers`);
      expect(screen.getByTestId("tab-count-estimate").textContent).toBe("8, 8 to submit");

      // Recent activity: 5 newest, initials tiles, actor and time.
      const activity = card("Recent activity");
      const events = within(activity).getAllByRole("listitem");
      expect(events).toHaveLength(5);
      expect(events[0].textContent).toContain("Estimate Version created");
      expect(events[0].textContent).toContain("Red Team 0 · ");
      expect(events[1].getAttribute("data-actor-type")).toBe("user");
      expect(events[1].textContent).toMatch(/^SD/);
      expect(within(activity).getByRole("link", { name: "Open Trace" }).getAttribute("href")).toBe(
        href("trace"),
      );

      // Latest agent decision: the newest Assessment (Security) and its most severe Finding.
      const decision = card("Latest agent decision");
      expect(within(decision).getAllByText("Security Agent").length).toBeGreaterThan(0);
      expect(within(decision).getByText("[SSO]")).toBeTruthy();
      expect(within(decision).getByText("[DETAIL]")).toBeTruthy();
      expect(within(decision).getByText("[BASIS]")).toBeTruthy();
      expect(within(decision).getByText("R10")).toBeTruthy();
      expect(within(decision).getByText("Do not proceed")).toBeTruthy();
      expect(within(decision).getByText("Low confidence")).toBeTruthy();
      expect(
        within(decision).getByRole("link", { name: "Open Assessments" }).getAttribute("href"),
      ).toBe(href("assessments"));

      // The summary is read-only: no Cancel, and Submit only in the header (Story 8.6).
      expect(screen.queryByRole("button", { name: /Cancel run/ })).toBeNull();
      expect(within(blockersCard).queryByRole("button")).toBeNull();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Run in progress: 1 of 3 tasks complete, task pills match", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, MID);
      await renderWorkspace();
      const runCard = card("Agent run");
      expect(runCard.textContent).toContain("1 of 3 tasks complete");
      expect(runCard.textContent).toContain("Assessments · started 5 Oct 2026, 09:31 UTC");
      const tasks = within(runCard).getAllByRole("listitem");
      expect(tasks.map((t) => t.querySelector("[data-task-pill]")?.getAttribute("data-task-pill")))
        .toEqual(["succeeded", "running", "queued"]);
      expect(tasks.map((t) => t.textContent)).toEqual([
        "Engineering AgentDone",
        "PM AgentRunning",
        "Security AgentQueued",
      ]);
      expect(
        within(runCard).getByRole("link", { name: "Open Assessments" }).getAttribute("href"),
      ).toBe(href("assessments"));
    });

    it("Run: a failed task gives its reason", async () => {
      signedIn(["presales_engineer"]);
      const current = MID["/assessments"] as Record<string, unknown>;
      found(FUTURE, {
        ...MID,
        "/assessments": {
          ...current,
          run: run("partially_failed", [
            task("engineering_agent", "succeeded"),
            task("pm_agent", "failed", "model_timeout"),
          ]),
        },
      });
      await renderWorkspace();
      const runCard = card("Agent run");
      expect(runCard.textContent).toContain("1 of 2 tasks complete");
      const failed = within(runCard).getAllByRole("listitem")[1];
      expect(failed.className).toContain("bg-blocker-tint");
      expect(failed.textContent).toMatch(/^PM AgentFailed.+/);
    });

    it("Read fails: the Open Gaps KPI and its step say so; the other cards render", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, { ...MID, "/gaps": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      const { container } = await renderWorkspace();
      const message = "Open Gaps could not be loaded. Try again in a moment.";
      expect(kpi(/^Open Gaps\s*—\s*Open Gaps could not be loaded/).getAttribute("href")).toBe(
        href("gaps"),
      );
      // The step's Blocked comes from the blockers view, not the Gaps read.
      expect(stepStates()[3]).toBe("blocked");
      expect(within(card("Submission pipeline")).getByText("3 open")).toBeTruthy();
      expect(within(card("Submission pipeline")).queryByText(message)).toBeNull();
      // The blockers card reads the API's check, not the Gaps read.
      expect(
        within(card("Submission blockers")).getByText("8 to submit · 0 to Baseline"),
      ).toBeTruthy();
      expect(within(card("Needs you")).getByText(/may be incomplete/)).toBeTruthy();
      expect(kpi(/^Requirements confirmed\s*9\s*of 12/)).toBeTruthy();
      expect(card("Latest agent decision")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Overdue: the pipeline header says so in red", async () => {
      signedIn(["presales_engineer"]);
      found({ ...OPPORTUNITY, target_proposal_date: "2026-01-01" }, MID);
      await renderWorkspace();
      const overdue = within(card("Submission pipeline")).getByText(/^Overdue by \d+ days$/);
      expect(overdue.className).toContain("text-blocker");
    });

    const READY: Record<string, unknown> = {
      ...MID,
      "/gaps": {
        items: [],
        detection: { status: "succeeded", error_code: null },
        can_start_detection: false,
        can_edit_questions: false,
      },
      "/conflicts": {
        conflicts: [conflictFixture({ status: "resolved" })],
        open_count: 0,
        reviewers: [],
      },
      "/estimate": estimateView(false, 0),
      "/submission-blockers": blockersView([], true),
    };

    it("Ready: nothing blocks once the Estimate is accepted and nothing is open", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, READY);
      const { container } = await renderWorkspace();
      const blockersCard = card("Submission blockers");
      expect(within(blockersCard).getByText("0 blockers")).toBeTruthy();
      expect(within(blockersCard).getByText("0 blockers — ready to submit")).toBeTruthy();
      expect(within(blockersCard).queryAllByRole("listitem")).toHaveLength(0);
      // Submit is the header's primary action; Resolve is hidden.
      const submit = screen.getByRole("button", { name: "Submit" });
      expect(submit.getAttribute("aria-disabled")).toBeNull();
      expect(screen.queryByRole("link", { name: /^Resolve/ })).toBeNull();
      expect(stepStates().slice(5)).toEqual(["complete", "complete", "pending"]);
      expect(within(card("Submission pipeline")).getByText("Starts after you submit")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Ready, but the blockers read failed: no ready state and no count pill", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, { ...READY, "/submission-blockers": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      const blockersCard = card("Submission blockers");
      expect(within(blockersCard).queryByText(/ready to submit/)).toBeNull();
      expect(within(blockersCard).queryByText("0 blockers")).toBeNull();
      expect(
        within(blockersCard).getByText(
          "The submission blockers could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    });

    it("Partial failure: Requirements says so on its KPI", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, { ...MID, "/requirements": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(
        kpi(/^Requirements confirmed\s*—\s*Requirements could not be loaded\. Try again in a moment\.$/)
          .getAttribute("href"),
      ).toBe(href("requirements"));
      expect(stepStates().slice(1, 3)).toEqual(["pending", "pending"]);
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
      const needs = card("Needs you");
      expect(within(needs).getAllByRole("listitem")).toHaveLength(8);
      expect(within(needs).getByRole("link", { name: "+4 more" }).getAttribute("href")).toBe(
        href("gaps"),
      );
      expect(within(needs).getByText("12 items")).toBeTruthy();
      expect(await axeViolations(container)).toEqual([]);
    });

    it("Partial failure: the Estimate KPI and step say so; the rest render", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, { ...MID, "/estimate": null });
      const error = vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(kpi(/^Estimate\s*—\s*The Estimate could not be loaded/)).toBeTruthy();
      // The Assumption blockers still block the step (the view decides, not the Estimate read).
      expect(stepStates()[6]).toBe("blocked");
      expect(within(card("Needs you")).getByText(/may be incomplete/)).toBeTruthy();
      expect(within(card("Needs you")).getByText("Red Team: [ERP FIELDS]")).toBeTruthy();
      expect(kpi(/^Open Gaps\s*3/)).toBeTruthy();
      // Logged with the status only.
      expect(error).toHaveBeenCalledWith("GET estimate failed: status=500");
    });

    it("Partial failure: Conflicts, Assessments and Trace each stay in their own card", async () => {
      signedIn(["presales_engineer"]);
      found(FUTURE, { ...MID, "/conflicts": null, "/assessments": null, "/trace": null });
      vi.spyOn(console, "error").mockImplementation(() => {});
      await renderWorkspace();
      expect(kpi(/^Open Conflicts\s*—\s*The Conflicts could not be loaded/)).toBeTruthy();
      expect(
        within(card("Recent activity")).getByText(
          "The recent activity could not be loaded. Try again in a moment.",
        ),
      ).toBeTruthy();
      expect(screen.queryByRole("region", { name: "Latest agent decision" })).toBeNull();
      expect(screen.queryByRole("region", { name: "Agent run" })).toBeNull();
      expect(stepStates()[4]).toBe("pending");
      // The Conflict blockers still block the step.
      expect(stepStates()[5]).toBe("blocked");
      expect(within(card("Needs you")).getByText("Red Team: [ERP FIELDS]")).toBeTruthy();
      expect(kpi(/^Estimate · v3 draft\s*278\.0\s*h/)).toBeTruthy();
    });

    it("Before a step has run: the KPI is '—' with the step's status", async () => {
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
      expect(kpi(/^Requirements confirmed\s*—\s*Extracting…$/)).toBeTruthy();
      expect(kpi(/^Open Gaps\s*—\s*Failed$/)).toBeTruthy();
      expect(stepStates().slice(1, 4)).toEqual(["in-progress", "pending", "in-progress"]);
    });

    it("Who: a sales representative sees the same read-only summary", async () => {
      signedIn(["sales_representative"]);
      found(FUTURE, MID);
      const { container } = await renderWorkspace();
      expect(within(card("Needs you")).getAllByRole("listitem")).toHaveLength(7);
      expect(kpi(/^Estimate · v3 draft\s*278\.0\s*h/)).toBeTruthy();
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
    expect(selectedTabs()).toEqual(["Sources"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("call.vtt")).toBeTruthy();
    expect(within(panel).getByText("Transcript · v2 of 2 · 61 B")).toBeTruthy();
    // Exactly one level-2 heading: the card's.
    expect(within(panel).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Sources 1",
    ]);
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
    expect(within(panel).getAllByRole("button", { name: "Choose files" })[0]).toBeTruthy();
    expect(within(panel).getByText("No Sources yet")).toBeTruthy();
    expect(within(panel).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Sources",
    ]);
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
    expect(selectedTabs()).toEqual(["Requirements"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Requirements" })).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 3, name: "Integration" })).toBeTruthy();
    expect(within(panel).getByRole("region", { name: "Integration 1 · 0 confirmed" })).toBeTruthy();
    expect(within(panel).getByText("[REQUIREMENT]")).toBeTruthy();
    expect(within(panel).getByText("S1 · call.vtt")).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/requirements", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /requirements?untagged=integration: untagged rows and the type picker", async () => {
    signedIn(["presales_engineer"]);
    const requirement = (n: number, classification: string, tagged: boolean) => ({
      id: `00000000-0000-7000-8000-0000000000e${n}`,
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
      integration_types: tagged
        ? [{ id: "00000000-0000-7000-8000-0000000000a1", code: "SAP", name: "SAP", retired: false }]
        : [],
    });
    apiGet.mockImplementation(async (path: string) =>
      path === "/api/v1/catalogue/entries"
        ? {
            data: { items: [{ id: "00000000-0000-7000-8000-0000000000a2", name: "[EDI]" }] },
            response: new Response(null, { status: 200 }),
          }
        : path.endsWith("/requirements")
          ? {
              data: {
                items: [
                  requirement(1, "integration", true),
                  requirement(2, "integration", false),
                  requirement(3, "functional", false),
                ],
                extraction: { status: "succeeded", error_code: null, source_count: 1 },
                can_start_extraction: true,
                can_edit_requirements: true,
                untagged_integration_count: 1,
              },
              response: new Response(null, { status: 200 }),
            }
          : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
    await renderWorkspace("requirements", OPP_ID, { untagged: "integration" });
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByTestId("untagged-filter").textContent).toContain(
      "Showing 1 integration Requirement with no Integration Type",
    );
    expect(within(panel).queryByText("[REQUIREMENT 1]")).toBeNull();
    expect(within(panel).queryByText("[REQUIREMENT 3]")).toBeNull();
    await userEvent.setup().click(within(panel).getByText("[REQUIREMENT 2]"));
    const details = await screen.findByRole("complementary", { name: "Details" });
    expect(within(details).getByRole("checkbox", { name: "[EDI]" })).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/catalogue/entries", {
      params: { query: { kind: "integration_type" } },
    });
  });

  it("tab URL /requirements: the empty state", async () => {
    signedIn(["presales_engineer"]);
    foundWithRequirements({ items: [], extraction: null, can_start_extraction: true });
    await renderWorkspace("requirements");
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "Requirements appear after the first Source is parsed.",
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
                conflicts: [],
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
        risks: [],
        source: "assessments",
        source_run: 1,
      },
      draft: null,
      can_start_draft: false,
      can_accept_assumptions: false,
      can_export: false,
      assessment_running: false,
    });
    const { container } = await renderWorkspace("estimate");
    expect(selectedTabs()).toEqual(["Estimate"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Estimate" })).toBeTruthy();
    expect(within(panel).getByText("v1 · Draft")).toBeTruthy();
    expect(within(panel).getByText("From Assessments (run 1)")).toBeTruthy();
    expect(within(panel).getByRole("region", { name: "Assumptions Register" })).toBeTruthy();
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
      assessment_running: false,
    });
    await renderWorkspace("estimate");
    expect(
      within(screen.getByRole("tabpanel")).getByText("No Estimate yet"),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("tabpanel")).getByRole("link", { name: "Run assessment" }),
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

  /** `context`: the Gaps tab context (Story 4.1); left out, its read fails. */
  function foundWithGaps(body: unknown, context?: unknown) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/gaps/context")
        ? context
          ? { data: context, response: new Response(null, { status: 200 }) }
          : { response: new Response(null, { status: 500 }) }
        : path.endsWith("/gaps")
          ? body
            ? { data: body, response: new Response(null, { status: 200 }) }
            : { response: new Response(null, { status: 500 }) }
          : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("tab URL /gaps: the applicable Checklists and banners under the header", async () => {
    signedIn(["presales_engineer"]);
    foundWithGaps(
      { items: [], detection: null, can_start_detection: true, can_edit_questions: true },
      {
        applicable_checklists: [
          {
            checklist_id: "00000000-0000-7000-8000-0000000000c1",
            version: 2,
            name: "[CHECKLIST]",
            domain: "security",
          },
        ],
        untagged_integration_count: 1,
        uncovered: { products: ["[PRODUCT]"], integration_types: [] },
      },
    );
    await renderWorkspace("gaps");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("button", { name: "[CHECKLIST] · v2" })).toBeTruthy();
    expect(within(panel).getByTestId("untagged-banner").textContent).toContain(
      "1 integration Requirement has no Integration Type",
    );
    expect(within(panel).getByTestId("coverage-banner").textContent).toContain(
      "No documentation for 1 product in scope",
    );
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/gaps/context", {
      params: { path: { opportunity_id: OPP_ID } },
    });
  });

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
          answer: null,
          answer_suggestions: [],
        },
      ],
      detection: { status: "succeeded", error_code: null },
      can_start_detection: false,
      can_edit_questions: false,
    });
    const { container } = await renderWorkspace("gaps");
    // Story 4.7: the Gaps tab badge counts the open Gaps.
    expect(selectedTabs()).toEqual(["Gaps1, 1 open"]);
    expect(screen.getByTestId("tab-count-gaps").textContent).toBe("1, 1 open");
    const panel = screen.getByRole("tabpanel");
    // One "Gaps" heading: the section's header row.
    expect(within(panel).getAllByRole("heading", { level: 2, name: "Gaps" })).toHaveLength(1);
    expect(within(panel).getByText("1 total · 1 open · ranked by impact")).toBeTruthy();
    expect(within(panel).getByRole("row").textContent).toBe(
      "HighOpen [GAP]Integration details·Clarification AgentApproved",
    );
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/gaps", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["a draft version and can_create_risks", { status: "draft" }, true, true],
    ["no version", null, true, false],
    ["a superseded version", { status: "superseded" }, true, false],
    ["can_create_risks false", { status: "draft" }, false, false],
  ])("tab URL /gaps: Convert to Risk with %s (Story 8.5)", async (_, version, may, shown) => {
    signedIn(["presales_engineer"]);
    const gapsBody = {
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
          requirements: [],
          question: null,
          dismissal: null,
          history: [],
          last_changed_by: null,
          answer: null,
          answer_suggestions: [],
        },
      ],
      detection: { status: "succeeded", error_code: null },
      can_start_detection: true,
      can_edit_questions: true,
      can_edit_gaps: true,
      can_send_questions: false,
    };
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/gaps/context")
        ? { response: new Response(null, { status: 500 }) }
        : path.endsWith("/gaps")
          ? { data: gapsBody, response: new Response(null, { status: 200 }) }
          : path.endsWith("/estimate")
            ? {
                data: { version, draft: null, can_create_risks: may },
                response: new Response(null, { status: 200 }),
              }
            : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
    await renderWorkspace("gaps");
    await userEvent.setup().click(screen.getByRole("button", { name: /\[GAP\]/ }));
    const form = screen.queryByRole("form", { name: "Convert to Risk" });
    expect(form !== null).toBe(shown);
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
        "Gaps appear after Requirements are checked against Checklists.",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("tabpanel")).getAllByRole("heading", { level: 2, name: "Gaps" }),
    ).toHaveLength(1);
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
    expect(
      within(screen.getByRole("tabpanel")).getAllByRole("heading", { level: 2, name: "Gaps" }),
    ).toHaveLength(1);
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

  it("tab URL /assessments: the Red Team folded into the tab, its Findings in the table", async () => {
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
    expect(selectedTabs()).toEqual(["Assessments"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Assessments" })).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 3, name: "Agent tasks" })).toBeTruthy();
    expect(within(panel).getByRole("heading", { level: 3, name: "Findings" })).toBeTruthy();
    // No separate Red Team section: a task card, a result card and Findings table rows.
    expect(within(panel).queryByRole("heading", { level: 3, name: "Red Team" })).toBeNull();
    const result = within(panel).getByRole("article", { name: "Red Team" });
    expect(within(result).getByText("v2")).toBeTruthy();
    expect(
      within(within(panel).getByRole("list", { name: "Agent progress" })).getByText("Red Team"),
    ).toBeTruthy();
    const finding = within(panel).getByRole("button", { name: /\[FINDING\]/ });
    expect(finding.textContent).toBe("CriticalIntegration harder[FINDING]OpenRed Team1 Requirement0 Estimate lines");
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

  const RED_TEAM_WITH_FINDING = {
    review: {
      id: "00000000-0000-7000-8000-0000000000c1",
      version: 2,
      status: "current",
      estimate_version_id: null,
      estimate_version: null,
      dropped_count: 0,
      created_at: "2026-10-05T09:00:00Z",
      counts: { critical: 0, high: 1, medium: 0, low: 0 },
      findings: [
        {
          id: "00000000-0000-7000-8000-0000000000c2",
          position: 1,
          category: "integration_harder",
          severity: "high",
          title: "[RED FINDING]",
          argument: "[ARGUMENT]",
          requirements: [],
          lines: [],
        },
      ],
    },
    run: { status: "failed", error_code: "model_timeout" },
    can_start: false,
  };

  it("tab URL /assessments: a failed Red Team read says so beside the specialist content", async () => {
    signedIn(["presales_engineer"]);
    foundWithRedTeam(null, { ...NO_ASSESSMENTS, can_start: true });
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("assessments");
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText("The Red Team Review could not be loaded. Try again in a moment."),
    ).toBeTruthy();
    expect(
      within(panel).getByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Run assessment" })).toBeTruthy();
    expect(
      within(panel).queryByText(
        "The Specialist Assessments could not be loaded. Try again in a moment.",
      ),
    ).toBeNull();
  });

  it("tab URL /assessments: a failed Assessments read still shows the Red Team", async () => {
    signedIn(["presales_engineer"]);
    foundWithRedTeam(RED_TEAM_WITH_FINDING, null);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("assessments");
    const panel = screen.getByRole("tabpanel");
    expect(
      within(panel).getByText(
        "The Specialist Assessments could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
    expect(
      within(panel).queryByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeNull();
    const tasks = within(panel).getByRole("list", { name: "Agent progress" });
    expect(within(tasks).getByText("Red Team")).toBeTruthy();
    expect(within(tasks).getByText("the model took too long to answer")).toBeTruthy();
    expect(within(panel).getByRole("article", { name: "Red Team" })).toBeTruthy();
    expect(
      within(within(panel).getByRole("grid", { name: "Findings" })).getByRole("button", {
        name: /\[RED FINDING\]/,
      }),
    ).toBeTruthy();
    expect(
      within(panel).queryByText("The Red Team Review could not be loaded. Try again in a moment."),
    ).toBeNull();
  });

  describe("tab URL /assessments: Effort comparison", () => {
    const R1_ID = "00000000-0000-7000-8000-0000000000f1";
    const R2_ID = "00000000-0000-7000-8000-0000000000f2";
    const REQUIREMENTS = {
      items: [
        { id: R1_ID, number: 1, text: "[REQ ONE]", classification: "integration", version: 1 },
        { id: R2_ID, number: 2, text: "[REQ TWO]", classification: "security", version: 1 },
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

    it("comes last, after Results so far and Findings, for any reader", async () => {
      signedIn(["sales_representative"]);
      foundWithRedTeam(RED_TEAM, ASSESSMENTS, ESTIMATE, REQUIREMENTS);
      const { container } = await renderWorkspace("assessments");
      const panel = screen.getByRole("tabpanel");
      const headings = within(panel)
        .getAllByRole("heading", { level: 3 })
        .map((h) => h.textContent);
      const at = (name: string) => headings.indexOf(name);
      expect(headings).toEqual(["Results so far", "Findings", "Effort comparison"]);
      expect(at("Effort comparison")).toBe(headings.length - 1);

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
    expect(selectedTabs()).toEqual(["Trace"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Trace" })).toBeTruthy();
    const rows = within(panel).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("RARed Team AgentRed Team Review completed"),
      expect.stringContaining("[OWNER]Opportunity created"),
    ]);
    expect(rows.map((r) => r.getAttribute("data-actor-type"))).toEqual(["agent", "user"]);
    expect(
      within(panel).getByText("Trace rows are append-only and cannot be edited."),
    ).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Actor" })).toBeTruthy();
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
    const actorChip = screen.getByRole("button", { name: "Actor: Agent" });
    expect(actorChip.className).toContain("bg-primary-tint");
    expect(screen.getByRole("link", { name: "Clear filters" })).toBeTruthy();
    fireEvent.click(actorChip);
    await screen.findByRole("dialog", { name: "Actor filter" });
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
    expect(within(panel).getByText("No trace events")).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Open Overview" })).toBeTruthy();
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
    expect(screen.getByRole("heading", { level: 2, name: "Trace" })).toBeTruthy();
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it.each([["actuals", "Actuals"]])(
    "tab URL /%s: header, that tab selected, 'Not available yet.'",
    async (tab, label) => {
      signedIn(["head_of_delivery"]);
      found();
      const { container } = await renderWorkspace(tab);
      expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
      expect(selectedTabs()).toEqual([label]);
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText(NOT_AVAILABLE)).toBeTruthy();
      expect(within(panel).getByRole("heading", { level: 2, name: label })).toBeTruthy();
      expect(screen.queryByText("[CUSTOMER]")).toBeNull();
      expect(await axeViolations(container)).toEqual([]);
    },
  );

  it("tab URL /conflicts: the empty state, no count on the tab", async () => {
    signedIn(["sales_representative"]);
    found();
    const { container } = await renderWorkspace("conflicts");
    expect(selectedTabs()).toEqual(["Conflicts"]);
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("heading", { level: 2, name: "Conflicts" })).toBeTruthy();
    expect(within(panel).getByText("No Conflicts detected")).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Open Assessments" })).toBeTruthy();
    expect(within(panel).queryByText(NOT_AVAILABLE)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/conflicts", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /conflicts: a failed read says so; the header and tabs still render, no count", async () => {
    signedIn(["presales_engineer"]);
    found(OPPORTUNITY, { "/conflicts": null });
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderWorkspace("conflicts");
    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(9);
    expect(selectedTabs()).toEqual(["Conflicts"]);
    expect(screen.getByRole("tab", { name: "Conflicts" })).toBeTruthy();
    expect(screen.queryByTestId("tab-count-conflicts")).toBeNull();
    expect(
      within(screen.getByRole("tabpanel")).getByRole("heading", { level: 2, name: "Conflicts" }),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("tabpanel")).getByText(
        "The Conflicts could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
  });

  it("tab URL /conflicts: the Conflicts read-only, and the open count on the tab", async () => {
    signedIn(["sales_representative"]);
    const requirement = {
      id: "00000000-0000-7000-8000-0000000000e4",
      version: 1,
      label: "R4",
      excerpt: "[EXCERPT]",
    };
    found(OPPORTUNITY, {
      "/conflicts": {
        open_count: 1,
        conflicts: [
          {
            id: "00000000-0000-7000-8000-0000000000c1",
            type: "scope",
            severity: "medium",
            status: "open",
            detected_by: "rule",
            summary: "[SUMMARY]",
            run_id: "00000000-0000-7000-8000-0000000000c9",
            previous_conflict_id: null,
            resolution_reason: null,
            resolved_at: null,
            created_at: "2026-10-07T09:00:00Z",
            requirement,
            positions: [
              {
                position: 1,
                source: "assessment",
                agent: "engineering_agent",
                assessment_id: "00000000-0000-7000-8000-0000000000a1",
                assessment_version: 1,
                estimate_version_id: null,
                estimate_version: null,
                summary: "24 h",
                value: 24,
                requirement,
              },
              {
                position: 2,
                source: "assessment",
                agent: "pm_agent",
                assessment_id: "00000000-0000-7000-8000-0000000000a2",
                assessment_version: 1,
                estimate_version_id: null,
                estimate_version: null,
                summary: "Not sized",
                value: null,
                requirement,
              },
            ],
          },
        ],
      },
    });
    const { container } = await renderWorkspace("conflicts");
    expect(screen.getByRole("tab", { name: "Conflicts, 1 open" })).toBeTruthy();
    const panel = screen.getByRole("tabpanel");
    const grid = within(panel).getByRole("grid", { name: "Open Conflicts" });
    expect(within(grid).getAllByRole("row").map((r) => r.textContent)).toEqual([
      "[SUMMARY]Scope · R4Open",
    ]);
    // The first open Conflict's decision card, inline and read-only for a sales representative.
    const card = within(panel).getByTestId("conflict-decision-card");
    expect(within(card).getByRole("heading", { level: 3, name: "[SUMMARY]" })).toBeTruthy();
    expect(within(card).getAllByRole("listitem")).toHaveLength(2);
    expect(within(panel).queryByRole("form")).toBeNull();
    expect(within(panel).queryByRole("textbox")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab URL /conflicts: the owner resolves from the inspector, for this Opportunity", async () => {
    signedIn(["presales_engineer"]);
    resolveConflict.mockResolvedValue({ kind: "ok", conflict: conflictFixture() });
    found(OPPORTUNITY, {
      "/conflicts": {
        conflicts: [conflictFixture({ can_resolve: true })],
        open_count: 1,
        reviewers: [],
      },
    });
    const page = await WorkspaceTabPage({
      params: Promise.resolve({ id: OPP_ID, tab: "conflicts" }),
      searchParams: Promise.resolve({}),
    });
    segment.current = "conflicts";
    const layout = await OpportunityLayout({ children: page, params: Promise.resolve({ id: OPP_ID }) });
    render(
      <ShellProviders singleKeyShortcuts>
        {layout}
        <RightPane />
      </ShellProviders>,
    );
    const user = userEvent.setup();
    // The first open Conflict is selected on load; its decision card sits under the rows.
    expect(
      screen.getByRole("button", { name: /\[SUMMARY\]/ }).closest("[role=row]")?.getAttribute(
        "aria-selected",
      ),
    ).toBe("true");
    const form = await screen.findByRole("form", { name: "Decide the Conflict" });
    await user.click(within(form).getAllByRole("radio")[0]!);
    await user.type(
      within(form).getByLabelText("Reason (required)"),
      "Matches the interface list.",
    );
    await user.click(within(form).getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(resolveConflict).toHaveBeenCalled());
    expect(resolveConflict.mock.calls[0]![0]).toMatchObject({
      opportunityId: OPP_ID,
      conflictId: conflictFixture().id,
      rowVersion: 1,
      choice: { position: 1 },
    });
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
    "conflicts",
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
      // The header band still carries the right-pane toggle.
      expect(
        within(screen.getByTestId("page-header")).getByRole("button", { name: "Right pane" }),
      ).toBeTruthy();
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

describe("/opportunities/[id]/estimate/reviews/[rid] (Story 9.3, Open in tab)", () => {
  function panelRead(status = 200) {
    apiGet.mockImplementation(async (path: string) =>
      path.endsWith("/panel")
        ? status === 200
          ? { data: reviewPanel(), response: new Response(null, { status }) }
          : { response: new Response(null, { status }) }
        : { data: OPPORTUNITY, response: new Response(null, { status: 200 }) },
    );
  }

  it("renders the review panel full width, without Open in tab", async () => {
    signedIn(["engineering_reviewer"]);
    panelRead();
    const page = await ReviewPanelPage({
      params: Promise.resolve({ id: OPP_ID, rid: REVIEW_ID }),
    });
    const { container } = renderPage(page!);
    expect(
      screen.getByRole("heading", { level: 2, name: "Review request: Estimate v3, [OPPORTUNITY]" }),
    ).toBeTruthy();
    expect(screen.getByRole("group", { name: "Review decision" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open in tab" })).toBeNull();
    expect(screen.getByRole("link", { name: "Back to the Estimate" }).getAttribute("href")).toBe(
      `/opportunities/${OPP_ID}/estimate`,
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when the review can't be read", async () => {
    signedIn(["engineering_reviewer"]);
    panelRead(404);
    const page = await ReviewPanelPage({
      params: Promise.resolve({ id: OPP_ID, rid: REVIEW_ID }),
    });
    renderPage(page!);
    expect(screen.getByText("The review could not be loaded. Try again in a moment.")).toBeTruthy();
  });
});
