import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import { changeRole, loadUser, type AdminUser } from "./actions";

const USER_ID = "00000000-0000-7000-8000-000000000001";
const USER: AdminUser = {
  id: USER_ID,
  name: "[TARGET]",
  email: "target@example.invalid",
  roles: ["pm_reviewer"],
  row_version: 4,
  last_changed_by: "[OTHER ADMIN]",
};

const status = (code: number) => new Response(null, { status: code });

beforeEach(() => {
  api.GET.mockReset();
  api.PUT.mockReset();
  api.DELETE.mockReset();
});

describe("changeRole", () => {
  it("assigns with PUT and the row version as If-Match", async () => {
    api.PUT.mockResolvedValue({ data: USER, response: status(200) });
    const result = await changeRole({
      userId: USER_ID,
      role: "pm_reviewer",
      assigned: true,
      rowVersion: 3,
    });
    expect(result).toEqual({ kind: "ok", user: USER });
    expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/users/{user_id}/roles/{role}", {
      params: { path: { user_id: USER_ID, role: "pm_reviewer" }, header: { "If-Match": '"3"' } },
    });
  });

  it("removes with DELETE", async () => {
    api.DELETE.mockResolvedValue({ data: USER, response: status(200) });
    await changeRole({ userId: USER_ID, role: "commercial", assigned: false, rowVersion: 3 });
    expect(api.DELETE).toHaveBeenCalledTimes(1);
    expect(api.PUT).not.toHaveBeenCalled();
  });

  it("on 412 reports who changed the user last and writes nothing else", async () => {
    api.PUT.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue({ data: USER, response: status(200) });
    const result = await changeRole({
      userId: USER_ID,
      role: "commercial",
      assigned: true,
      rowVersion: 3,
    });
    expect(result).toEqual({ kind: "stale", changedBy: "[OTHER ADMIN]" });
    expect(api.PUT).toHaveBeenCalledTimes(1);
  });

  it("on 409 passes the detail through", async () => {
    const detail = "At least one platform administrator is required";
    api.DELETE.mockResolvedValue({
      error: { code: "last_administrator", detail },
      response: status(409),
    });
    const result = await changeRole({
      userId: USER_ID,
      role: "platform_administrator",
      assigned: false,
      rowVersion: 1,
    });
    expect(result).toEqual({ kind: "conflict", detail });
  });

  it.each([
    [403, "forbidden"],
    [404, "not-found"],
  ])("maps %i to %s", async (code, kind) => {
    api.PUT.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    const result = await changeRole({
      userId: USER_ID,
      role: "commercial",
      assigned: true,
      rowVersion: 1,
    });
    expect(result).toEqual({ kind });
  });

  it.each([
    null,
    {},
    { userId: "not-a-uuid", role: "commercial", assigned: true, rowVersion: 1 },
    { userId: USER_ID, role: "superuser", assigned: true, rowVersion: 1 },
    { userId: USER_ID, role: "commercial", assigned: "yes", rowVersion: 1 },
    { userId: USER_ID, role: "commercial", assigned: true, rowVersion: 1.5 },
  ])("rejects %o without calling the API", async (input) => {
    expect(await changeRole(input)).toEqual({ kind: "error" });
    expect(api.PUT).not.toHaveBeenCalled();
    expect(api.DELETE).not.toHaveBeenCalled();
  });
});

describe("loadUser", () => {
  it("returns the user", async () => {
    api.GET.mockResolvedValue({ data: USER, response: status(200) });
    expect(await loadUser(USER_ID)).toEqual({ kind: "ok", user: USER });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/users/{user_id}", {
      params: { path: { user_id: USER_ID } },
    });
  });

  it.each([
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (code, kind) => {
    api.GET.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    expect(await loadUser(USER_ID)).toEqual({ kind });
  });

  it.each([null, 42, "not-a-uuid"])("returns not-found for %o without calling GET", async (id) => {
    expect(await loadUser(id)).toEqual({ kind: "not-found" });
    expect(api.GET).not.toHaveBeenCalled();
  });
});
