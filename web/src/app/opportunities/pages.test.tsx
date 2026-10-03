import { render, screen, waitFor } from "@testing-library/react";
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
  loadOpportunity: vi.fn(),
  searchUsers: vi.fn(),
}));
const redirect = vi.hoisted(() =>
  vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT ${href}`);
  }),
);
vi.mock("next/navigation", () => ({
  redirect,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/my-opportunities",
}));

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

describe("/opportunities/[id]", () => {
  const idParams = (id = OPP_ID) => Promise.resolve({ id });

  it("shows the fields, status, owner and collaborators", async () => {
    signedIn(["head_of_delivery"]);
    apiGet.mockResolvedValue({ data: OPPORTUNITY, response: new Response(null, { status: 200 }) });
    const { container } = renderPage(await OpportunityPage({ params: idParams() }));

    expect(screen.getByRole("heading", { level: 1, name: "[TITLE]" })).toBeTruthy();
    expect(screen.getByText("Intake")).toBeTruthy();
    expect(screen.getByText("[CUSTOMER]")).toBeTruthy();
    expect(screen.getByText("Pick station")).toBeTruthy();
    expect(screen.getByText("Retail")).toBeTruthy();
    expect(screen.getByText("1 Nov 2026")).toBeTruthy();
    expect(screen.getAllByText("[OWNER]").length).toBeGreaterThan(0);
    expect(screen.getByText("[MEMBER]")).toBeTruthy();
    // Not the owner: no collaborator controls.
    expect(screen.queryByLabelText("Add collaborator")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("404 (hidden or unknown) and a malformed id say 'You don't have access to this Opportunity'", async () => {
    signedIn(["sales_representative"]);
    apiGet.mockResolvedValue({
      error: { code: "not_found" },
      response: new Response(null, { status: 404 }),
    });
    const hidden = renderPage(await OpportunityPage({ params: idParams() }));
    expect(screen.getByText("You don't have access to this Opportunity")).toBeTruthy();
    expect(screen.queryByText("[CUSTOMER]")).toBeNull();
    hidden.unmount();
    apiGet.mockClear();
    renderPage(await OpportunityPage({ params: idParams("not-a-uuid") }));
    expect(screen.getByText("You don't have access to this Opportunity")).toBeTruthy();
    await waitFor(() => expect(apiGet).not.toHaveBeenCalled());
  });
});
