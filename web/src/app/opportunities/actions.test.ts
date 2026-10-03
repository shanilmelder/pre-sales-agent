import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));
vi.mock("server-only", () => ({}));

import { changeCollaborator, createOpportunity, searchUsers } from "./actions";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const USER_ID = "00000000-0000-7000-8000-000000000002";
const OPPORTUNITY: Opportunity = {
  id: OPP_ID,
  title: "[TITLE]",
  customer_name: "[CUSTOMER]",
  products: ["AutoStore"],
  industry: "Retail",
  target_proposal_date: "2026-11-01",
  status: "intake",
  owner: { id: USER_ID, name: "[OWNER]" },
  collaborators: [],
  row_version: 4,
  created_at: "2026-10-04T10:00:00Z",
  last_changed_by: "[OTHER]",
  can_manage_collaborators: true,
};
const INPUT = {
  title: "  ",
  customer_name: "[CUSTOMER]",
  products: ["AutoStore"],
  industry: "Retail",
  target_proposal_date: "2026-11-01",
};

const status = (code: number) => new Response(null, { status: code });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("createOpportunity", () => {
  it("posts the fields (blank title as null) and returns the new id", async () => {
    api.POST.mockResolvedValue({ data: OPPORTUNITY, response: status(201) });
    expect(await createOpportunity(INPUT)).toEqual({ kind: "ok", id: OPP_ID });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities", {
      body: { ...INPUT, title: null },
    });
  });

  it("maps a 422 to the fields the API named", async () => {
    api.POST.mockResolvedValue({
      error: {
        code: "validation_error",
        detail: "Invalid fields: body.products, body.target_proposal_date",
      },
      response: status(422),
    });
    expect(await createOpportunity(INPUT)).toEqual({
      kind: "invalid",
      fields: ["products", "target_proposal_date"],
    });
  });

  it("403 is forbidden; bad input and failures are errors", async () => {
    api.POST.mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) });
    expect(await createOpportunity(INPUT)).toEqual({ kind: "forbidden" });
    expect(await createOpportunity({ ...INPUT, products: "AutoStore" })).toEqual({
      kind: "error",
    });
    api.POST.mockRejectedValueOnce(new Error("network"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await createOpportunity(INPUT)).toEqual({ kind: "error" });
  });
});

describe("changeCollaborator", () => {
  const input = { opportunityId: OPP_ID, userId: USER_ID, add: true, rowVersion: 3 };
  const path = "/api/v1/opportunities/{opportunity_id}/collaborators/{user_id}";
  const init = {
    params: {
      path: { opportunity_id: OPP_ID, user_id: USER_ID },
      header: { "If-Match": '"3"' },
    },
  };

  it("adds with PUT and removes with DELETE, sending the row version as If-Match", async () => {
    api.PUT.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    api.DELETE.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await changeCollaborator(input)).toEqual({ kind: "ok", opportunity: OPPORTUNITY });
    expect(api.PUT).toHaveBeenCalledWith(path, init);
    await changeCollaborator({ ...input, add: false });
    expect(api.DELETE).toHaveBeenCalledWith(path, init);
  });

  it("on 412 reports who changed it last and does not retry", async () => {
    api.PUT.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await changeCollaborator(input)).toEqual({ kind: "stale", changedBy: "[OTHER]" });
    expect(api.PUT).toHaveBeenCalledTimes(1);
  });

  it("maps 422, 403 and 404", async () => {
    api.PUT.mockResolvedValueOnce({
      error: { code: "invalid_collaborator", detail: "The owner can't be added." },
      response: status(422),
    });
    expect(await changeCollaborator(input)).toEqual({
      kind: "invalid",
      detail: "The owner can't be added.",
    });
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(403) });
    expect(await changeCollaborator(input)).toEqual({ kind: "forbidden" });
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(404) });
    expect(await changeCollaborator(input)).toEqual({ kind: "not-found" });
  });

  it("rejects malformed input without calling the API", async () => {
    expect(await changeCollaborator({ ...input, userId: "x" })).toEqual({ kind: "error" });
    expect(await changeCollaborator({ ...input, rowVersion: -1 })).toEqual({ kind: "error" });
    expect(api.PUT).not.toHaveBeenCalled();
  });
});

describe("searchUsers", () => {
  it("skips queries shorter than two code points and cuts long ones by code point", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: status(200) });
    expect(await searchUsers(" a ")).toEqual({ kind: "ok", users: [] });
    expect(await searchUsers("😀")).toEqual({ kind: "ok", users: [] });
    expect(api.GET).not.toHaveBeenCalled();
    await searchUsers("😀".repeat(101));
    const sent: string = api.GET.mock.calls[0][1].params.query.q;
    expect(Array.from(sent)).toHaveLength(100);
    expect(sent).toBe("😀".repeat(100)); // no half surrogate pair at the end
  });

  it("searches by the trimmed query and skips blank ones", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: status(200) });
    expect(await searchUsers("  ")).toEqual({ kind: "ok", users: [] });
    expect(api.GET).not.toHaveBeenCalled();
    await searchUsers(" ann ");
    expect(api.GET).toHaveBeenCalledWith("/api/v1/users/search", {
      params: { query: { q: "ann", limit: 10 } },
    });
  });
});
