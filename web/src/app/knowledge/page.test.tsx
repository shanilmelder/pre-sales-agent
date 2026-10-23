import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { KnowledgeSource } from "@/lib/knowledge-sources";
import { source } from "@/test/knowledge-fixtures";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
const loadSources = vi.hoisted(() =>
  vi.fn<() => Promise<{ kind: "ok"; sources: KnowledgeSource[]; staleMonths: number }>>(),
);
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/knowledge/actions", () => ({ loadSources }));
vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/knowledge",
}));

import KnowledgePage from "@/app/knowledge/page";
import { ShellProviders } from "@/components/shell/shell-context";

const EDI = { id: "00000000-0000-7000-8000-0000000000e1", code: "EDI", name: "EDI" };

beforeEach(() => {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[USER]",
      email: "user@example.invalid",
      roles: ["presales_engineer"],
      permissions: permissionsFor(["presales_engineer"]),
    },
  });
  apiGet.mockResolvedValue({
    data: { items: [{ ...EDI, kind: "integration_type" }] },
    response: new Response(null, { status: 200 }),
  });
  loadSources.mockResolvedValue({
    kind: "ok",
    staleMonths: 12,
    sources: [
      source(1, { title: "AutoStore guide" }),
      source(2, {
        title: "EDI guide",
        product: "Pick station",
        integration_types: [{ ...EDI, retired: false }],
      }),
    ],
  });
});

describe("/knowledge links (Story 4.1)", () => {
  it("presets the Integration Type filter from ?integration_type=", async () => {
    const page = await KnowledgePage({
      searchParams: Promise.resolve({ integration_type: EDI.id }),
    });
    render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);

    expect(
      (screen.getByRole("combobox", { name: "Integration Type" }) as HTMLSelectElement).value,
    ).toBe(EDI.id);
    expect(screen.getByText("EDI guide")).toBeTruthy();
    expect(screen.queryByText("AutoStore guide")).toBeNull();
  });

  it("presets the product filter from ?product=", async () => {
    const page = await KnowledgePage({ searchParams: Promise.resolve({ product: "pick station" }) });
    render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);

    expect((screen.getByRole("combobox", { name: "Product" }) as HTMLSelectElement).value).toBe(
      "Pick station",
    );
    expect(screen.queryByText("AutoStore guide")).toBeNull();
  });
});
