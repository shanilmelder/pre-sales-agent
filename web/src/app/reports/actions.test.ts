import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));
vi.mock("server-only", () => ({}));

import { loadFailedAssumptions } from "./actions";

const IT = "0190c000-0000-7000-8000-0000000000a1";
const LIST = { group_by: "product", group_key: "Payments", filters: {}, items: [] };

beforeEach(() => api.GET.mockReset());

describe("loadFailedAssumptions (Story 10.4)", () => {
  it("GETs the group's list with the report's parsed filters", async () => {
    api.GET.mockResolvedValue({ data: LIST, response: new Response(null, { status: 200 }) });

    const result = await loadFailedAssumptions(
      `product=Payments&integration_type_id=${IT.toUpperCase()}&cause=bad_luck`,
      "product",
      "Payments",
    );

    expect(result).toEqual({ kind: "ok", list: LIST });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/reports/failed-assumptions", {
      params: {
        query: {
          group_by: "product",
          group_key: "Payments",
          product: "Payments",
          work_package_id: undefined,
          integration_type_id: IT,
          cause: undefined,
          closed_from: undefined,
          closed_to: undefined,
          include_milestones: false,
        },
      },
    });
  });

  it("maps a 403 to forbidden and other failures to error", async () => {
    api.GET.mockResolvedValue({ response: new Response(null, { status: 403 }) });
    expect(await loadFailedAssumptions("", "integration_type", "none")).toEqual({
      kind: "forbidden",
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadFailedAssumptions("", "integration_type", "none")).toEqual({ kind: "error" });
  });

  it.each([
    ["an unknown grouping", "", "customer", "none"],
    ["an empty group key", "", "integration_type", ""],
    ["an overlong group key", "", "integration_type", "x".repeat(201)],
    ["a non-string search", 42, "integration_type", "none"],
  ])("rejects %s without calling the API", async (_name, search, groupBy, groupKey) => {
    expect(await loadFailedAssumptions(search, groupBy, groupKey)).toEqual({ kind: "error" });
    expect(api.GET).not.toHaveBeenCalled();
  });
});
