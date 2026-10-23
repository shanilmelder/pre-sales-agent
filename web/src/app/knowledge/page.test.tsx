import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";
import { source } from "@/test/knowledge-fixtures";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
const loadSources = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("./actions", () => ({ loadSources }));
vi.mock("@/app/knowledge/actions", () => ({ loadSources }));
vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/knowledge",
}));

import KnowledgePage from "@/app/knowledge/page";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[USER]",
      email: "user@example.invalid",
      roles,
      permissions: permissionsFor(roles),
    },
  });
}

function loaded() {
  loadSources.mockResolvedValue({
    kind: "ok",
    sources: [source(1, { title: "Guide" })],
    staleMonths: 6,
  });
  apiGet.mockResolvedValue({
    data: { items: [] },
    response: new Response(null, { status: 200 }),
  });
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  loadSources.mockReset();
});

describe("/knowledge", () => {
  it("shows the header, the segmented control and Add source for administrators", async () => {
    signedIn(["platform_administrator"]);
    loaded();
    const { container } = renderPage(await KnowledgePage());

    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeTruthy();
    const current = screen.getByRole("link", { name: "Sources" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("button", { name: "Register Source" })).toBeNull();
    const add = screen.getByRole("button", { name: "Add source" });
    expect(add.getAttribute("aria-keyshortcuts")).toBe("c");
    expect(screen.getByRole("table").closest('[data-slot="card"]')).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Add source opens the register form", async () => {
    signedIn(["platform_administrator"]);
    loaded();
    renderPage(await KnowledgePage());
    await userEvent.setup().click(screen.getByRole("button", { name: "Add source" }));
    expect(await screen.findByText("Register a Knowledge Source")).toBeTruthy();
  });

  it("shows the header without an action for other roles", async () => {
    signedIn(["presales_engineer"]);
    loaded();
    const { container } = renderPage(await KnowledgePage());
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add source" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("keeps the header when the platform is down", async () => {
    signedIn(["platform_administrator"]);
    loadSources.mockResolvedValue({ kind: "error" });
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 500 }) });
    const { container } = renderPage(await KnowledgePage());
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add source" })).toBeNull();
    expect(screen.getByText(/not reachable/)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
