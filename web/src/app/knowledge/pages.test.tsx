import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { checklist, TYPE_ID } from "@/test/checklist-fixtures";
import { source } from "@/test/knowledge-fixtures";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/knowledge/actions", () => ({
  loadSources: async () => ({
    kind: "ok",
    sources: [source(1, { product: "AutoStore" }), source(2, { product: "HubSpot" })],
    staleMonths: 12,
  }),
}));
vi.mock("@/app/knowledge/checklists/actions", () => ({
  loadChecklists: async () => ({
    kind: "ok",
    checklists: [checklist(1, { products: ["AutoStore"] }), checklist(2, { products: ["HubSpot"] })],
  }),
}));
vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/knowledge",
}));

import KnowledgeChecklistsPage from "@/app/knowledge/checklists/page";
import KnowledgePage from "@/app/knowledge/page";
import { ShellProviders } from "@/components/shell/shell-context";

const OTHER_TYPE = "00000000-0000-7000-8000-000000000009";
const query = (values: Record<string, string>) => Promise.resolve(values);

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

const valueOf = (label: string) => (screen.getByLabelText(label) as HTMLSelectElement).value;

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  apiGet.mockResolvedValue({
    data: {
      items: [
        { id: TYPE_ID, kind: "integration_type", name: "SAP IDoc" },
        { id: OTHER_TYPE, kind: "integration_type", name: "REST API" },
      ],
    },
    response: new Response(null, { status: 200 }),
  });
  signedIn(["platform_administrator"]);
});

describe("filter links from Coverage", () => {
  it("seed the Sources filters from ?product=&integration_type=", async () => {
    renderPage(
      await KnowledgePage({
        searchParams: query({ product: "hubspot", integration_type: OTHER_TYPE }),
      }),
    );
    expect(valueOf("Product")).toBe("HubSpot");
    expect(valueOf("Integration Type")).toBe(OTHER_TYPE);
  });

  it("seed the Checklists filters from ?product=&integration_type=", async () => {
    renderPage(
      await KnowledgeChecklistsPage({
        searchParams: query({ product: "AutoStore", integration_type: TYPE_ID }),
      }),
    );
    expect(valueOf("Product")).toBe("AutoStore");
    expect(valueOf("Integration Type")).toBe(TYPE_ID);
  });

  it("follow new params on the same page (the tab remounts)", async () => {
    const first = { product: "AutoStore", integration_type: TYPE_ID };
    const second = { product: "HubSpot", integration_type: OTHER_TYPE };
    const sources = renderPage(await KnowledgePage({ searchParams: query(first) }));
    sources.rerender(
      <ShellProviders singleKeyShortcuts>
        {await KnowledgePage({ searchParams: query(second) })}
      </ShellProviders>,
    );
    expect(valueOf("Product")).toBe("HubSpot");
    expect(valueOf("Integration Type")).toBe(OTHER_TYPE);
    sources.unmount();

    const checklists = renderPage(await KnowledgeChecklistsPage({ searchParams: query(first) }));
    checklists.rerender(
      <ShellProviders singleKeyShortcuts>
        {await KnowledgeChecklistsPage({ searchParams: query(second) })}
      </ShellProviders>,
    );
    expect(valueOf("Product")).toBe("HubSpot");
    expect(valueOf("Integration Type")).toBe(OTHER_TYPE);
  });

  it("leave the filters empty without them", async () => {
    renderPage(await KnowledgePage({ searchParams: query({}) }));
    expect(valueOf("Product")).toBe("");
    expect(valueOf("Integration Type")).toBe("");
  });
});
