// @vitest-environment node
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.hoisted(() => vi.fn());
const createServerApiClient = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ createServerApiClient }));

import { GET } from "./route";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const TOKEN = "eyJoIjoiYSJ9.sig";
const TEMPLATE = "/api/v1/opportunities/{opportunity_id}/actuals/template";

function call(id: string) {
  return GET(new Request(`http://web/api/opportunities/${id}/actuals-template`), {
    params: Promise.resolve({ id }),
  });
}

function exported(url: unknown, fileName = "actuals-template-estimate-v3.xlsx") {
  return {
    data: { url, file_name: fileName, expires_at: "2026-10-27T10:00:00Z" },
    error: undefined,
    response: new Response(null, { status: 200 }),
  };
}

function file(body = "PK-bytes") {
  const response = new Response(body, {
    headers: { "Content-Type": "application/octet-stream", "Content-Length": "8" },
  });
  return { data: response.body, error: undefined, response };
}

beforeEach(() => {
  apiGet.mockReset();
  createServerApiClient.mockReset();
  createServerApiClient.mockResolvedValue({ GET: apiGet });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("GET /api/opportunities/{id}/actuals-template", () => {
  it("gets the template link, fetches it server-side and streams the file back", async () => {
    apiGet
      .mockResolvedValueOnce(exported(`/api/v1/downloads/${TOKEN}`))
      .mockResolvedValueOnce(file());

    const resp = await call(OPP_ID);

    expect(apiGet).toHaveBeenNthCalledWith(1, TEMPLATE, {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(apiGet).toHaveBeenNthCalledWith(2, "/api/v1/downloads/{token}", {
      params: { path: { token: TOKEN } },
      parseAs: "stream",
    });
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Content-Type")).toBe(XLSX);
    expect(resp.headers.get("Content-Disposition")).toBe(
      'attachment; filename="actuals-template-estimate-v3.xlsx"',
    );
    expect(resp.headers.get("Cache-Control")).toBe("no-store");
    expect(resp.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(resp.headers.get("Content-Length")).toBe("8");
    expect(await resp.text()).toBe("PK-bytes");
  });

  it("keeps the file name header-safe", async () => {
    apiGet
      .mockResolvedValueOnce(exported(`/api/v1/downloads/${TOKEN}`, 'a"b\r\n.xlsx'))
      .mockResolvedValueOnce(file());

    const resp = await call(OPP_ID);

    expect(resp.headers.get("Content-Disposition")).toBe('attachment; filename="ab.xlsx"');
  });

  it.each([[undefined], ["https://elsewhere.example/file.xlsx"]])(
    "a missing or foreign link (%s) is a 502, fetching nothing",
    async (url) => {
      apiGet.mockResolvedValueOnce(exported(url));

      const resp = await call(OPP_ID);

      expect(resp.status).toBe(502);
      expect(await resp.json()).toMatchObject({ code: "export_failed" });
      expect(apiGet).toHaveBeenCalledTimes(1);
    },
  );

  it("passes a backend 409 on as problem+json, fetching no file", async () => {
    apiGet.mockResolvedValueOnce({
      data: undefined,
      error: { code: "actuals_no_baseline", detail: "Set a Baseline first." },
      response: new Response(null, { status: 409 }),
    });

    const resp = await call(OPP_ID);

    expect(resp.status).toBe(409);
    expect(resp.headers.get("Content-Type")).toBe("application/problem+json");
    expect(await resp.json()).toMatchObject({ status: 409, code: "actuals_no_baseline" });
    expect(apiGet).toHaveBeenCalledTimes(1);
  });

  it("a failed download is passed on", async () => {
    apiGet.mockResolvedValueOnce(exported(`/api/v1/downloads/${TOKEN}`)).mockResolvedValueOnce({
      data: undefined,
      error: { code: "forbidden", detail: "Expired." },
      response: new Response(null, { status: 403 }),
    });

    const resp = await call(OPP_ID);

    expect(resp.status).toBe(403);
    expect(await resp.json()).toMatchObject({ code: "forbidden" });
  });

  it("refuses a bad id without calling the API", async () => {
    const resp = await call("nope");
    expect(resp.status).toBe(422);
    expect(createServerApiClient).not.toHaveBeenCalled();
  });

  it("asks to sign in again without a session", async () => {
    createServerApiClient.mockRejectedValue(new AccessTokenError("missing_session", "No session"));
    const resp = await call(OPP_ID);
    expect(resp.status).toBe(401);
    expect(await resp.json()).toMatchObject({ code: "token_missing" });
  });

  it("a thrown fetch is a 502", async () => {
    apiGet.mockRejectedValue(new TypeError("fetch failed"));
    const resp = await call(OPP_ID);
    expect(resp.status).toBe(502);
    expect(await resp.json()).toMatchObject({ code: "api_unavailable" });
  });
});
