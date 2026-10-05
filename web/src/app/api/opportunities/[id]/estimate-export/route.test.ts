// @vitest-environment node
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.hoisted(() => vi.fn());
const createServerApiClient = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ createServerApiClient }));

import { GET } from "./route";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function call(id: string, format: string | null) {
  const query = format === null ? "" : `?format=${format}`;
  return GET(new Request(`http://web/api/opportunities/${id}/estimate-export${query}`), {
    params: Promise.resolve({ id }),
  });
}

beforeEach(() => {
  apiGet.mockReset();
  createServerApiClient.mockReset();
  createServerApiClient.mockResolvedValue({ GET: apiGet });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("GET /api/opportunities/{id}/estimate-export", () => {
  it("streams the backend's file back with its headers", async () => {
    const backend = new Response("PK-bytes", {
      headers: {
        "Content-Type": XLSX,
        "Content-Disposition": 'attachment; filename="acme-estimate-v2.xlsx"',
      },
    });
    apiGet.mockResolvedValue({ data: backend.body, error: undefined, response: backend });

    const resp = await call(OPP_ID, "xlsx");

    expect(apiGet).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/estimate/export", {
      params: { path: { opportunity_id: OPP_ID }, query: { format: "xlsx" } },
      parseAs: "stream",
    });
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Content-Type")).toBe(XLSX);
    expect(resp.headers.get("Content-Disposition")).toBe(
      'attachment; filename="acme-estimate-v2.xlsx"',
    );
    expect(resp.headers.get("Cache-Control")).toBe("no-store");
    expect(await resp.text()).toBe("PK-bytes");
  });

  it("passes a backend failure on as problem+json", async () => {
    const backend = new Response(null, { status: 403 });
    apiGet.mockResolvedValue({
      data: undefined,
      error: { code: "forbidden", detail: "Not allowed." },
      response: backend,
    });

    const resp = await call(OPP_ID, "docx");

    expect(resp.status).toBe(403);
    expect(resp.headers.get("Content-Type")).toBe("application/problem+json");
    expect(await resp.json()).toMatchObject({ status: 403, code: "forbidden" });
  });

  it("passes a backend 409 on", async () => {
    apiGet.mockResolvedValue({
      data: undefined,
      error: { code: "estimate_not_found", detail: "No Estimate yet." },
      response: new Response(null, { status: 409 }),
    });

    const resp = await call(OPP_ID, "xlsx");

    expect(resp.status).toBe(409);
    expect(await resp.json()).toMatchObject({ status: 409, code: "estimate_not_found" });
  });

  it("falls back to export_failed when the backend's error isn't JSON", async () => {
    apiGet.mockResolvedValue({
      data: undefined,
      error: "Internal Server Error",
      response: new Response("Internal Server Error", { status: 500 }),
    });

    const resp = await call(OPP_ID, "xlsx");

    expect(resp.status).toBe(500);
    expect(await resp.json()).toMatchObject({ status: 500, code: "export_failed" });
  });

  it("answers 502 when the backend's success has no body", async () => {
    apiGet.mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    const resp = await call(OPP_ID, "xlsx");

    expect(resp.status).toBe(502);
    expect(await resp.json()).toMatchObject({ status: 502, code: "export_failed" });
  });

  it("answers 502 when the backend can't be reached", async () => {
    apiGet.mockRejectedValue(new TypeError("fetch failed"));

    const resp = await call(OPP_ID, "xlsx");

    expect(resp.status).toBe(502);
    expect(await resp.json()).toMatchObject({ code: "api_unavailable" });
  });

  it.each([
    [OPP_ID, "pdf"],
    [OPP_ID, null],
    ["not-a-uuid", "xlsx"],
  ])("refuses %s with format %s without calling the backend", async (id, format) => {
    const resp = await call(id, format);

    expect(resp.status).toBe(422);
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("answers 401 without a session", async () => {
    createServerApiClient.mockRejectedValue(new AccessTokenError("missing_session", "No session"));

    const resp = await call(OPP_ID, "xlsx");

    expect(resp.status).toBe(401);
    expect(apiGet).not.toHaveBeenCalled();
  });
});
