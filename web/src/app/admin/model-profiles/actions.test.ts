import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import {
  addApprovedModel,
  createProfile,
  loadProfiles,
  removeApprovedModel,
  retestProfile,
  retireProfile,
} from "./actions";

const ID = "00000000-0000-7000-8000-000000000001";
const status = (code: number) => new Response(null, { status: code });
const failure = (code: number, detail = "The API's sentence.") => ({
  data: undefined,
  error: { detail },
  response: status(code),
});
const INPUT = {
  name: "custom",
  provider: "ollama" as const,
  model: "gpt-oss:120b-cloud",
  num_ctx: 32768,
  temperature: 0.1,
  reasoning_effort: null,
};

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.DELETE.mockReset();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("loadProfiles", () => {
  it("maps 200, 403 and anything else", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: status(200) });
    expect(await loadProfiles()).toEqual({ kind: "ok", profiles: [] });
    api.GET.mockResolvedValue({ data: undefined, response: status(403) });
    expect(await loadProfiles()).toEqual({ kind: "forbidden" });
    api.GET.mockResolvedValue({ data: undefined, response: status(500) });
    expect(await loadProfiles()).toEqual({ kind: "error" });
  });
});

describe.each([
  ["createProfile", () => createProfile(INPUT)],
  ["retestProfile", () => retestProfile(ID)],
  ["retireProfile", () => retireProfile(ID)],
])("%s", (_, call) => {
  it("maps 409, 422, 403 and 404", async () => {
    api.POST.mockResolvedValue(failure(409));
    expect(await call()).toEqual({ kind: "conflict", detail: "The API's sentence." });
    api.POST.mockResolvedValue(failure(422));
    expect(await call()).toEqual({ kind: "invalid", detail: "The API's sentence." });
    api.POST.mockResolvedValue(failure(403));
    expect(await call()).toEqual({ kind: "forbidden" });
    api.POST.mockResolvedValue(failure(404));
    expect(await call()).toEqual({ kind: "not-found" });
  });

  it("maps a 500 and a thrown error", async () => {
    api.POST.mockResolvedValue(failure(500));
    expect(await call()).toEqual({ kind: "error" });
    api.POST.mockRejectedValue(new Error("down"));
    expect(await call()).toEqual({ kind: "error" });
  });
});

describe("profile ids", () => {
  it("refuses a malformed id without calling the API", async () => {
    expect(await retestProfile("../x")).toEqual({ kind: "not-found" });
    expect(await retireProfile("../x")).toEqual({ kind: "not-found" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("addApprovedModel", () => {
  it("maps 409, 422 and 403", async () => {
    const input = { provider: "ollama" as const, model: "m" };
    api.POST.mockResolvedValue(failure(409));
    expect(await addApprovedModel(input)).toEqual({
      kind: "conflict",
      detail: "The API's sentence.",
    });
    api.POST.mockResolvedValue(failure(422));
    expect(await addApprovedModel(input)).toEqual({
      kind: "invalid",
      detail: "The API's sentence.",
    });
    api.POST.mockResolvedValue(failure(403));
    expect(await addApprovedModel(input)).toEqual({ kind: "forbidden" });
  });
});

describe("removeApprovedModel", () => {
  it("counts an entry already gone as removed", async () => {
    api.DELETE.mockResolvedValue({ response: status(204) });
    expect(await removeApprovedModel(ID)).toEqual({ kind: "ok" });
    api.DELETE.mockResolvedValue({ response: status(404) });
    expect(await removeApprovedModel(ID)).toEqual({ kind: "ok" });
  });

  it("maps 403 and a malformed id", async () => {
    api.DELETE.mockResolvedValue({ response: status(403) });
    expect(await removeApprovedModel(ID)).toEqual({ kind: "forbidden" });
    api.DELETE.mockReset();
    expect(await removeApprovedModel("../x")).toEqual({ kind: "error" });
    expect(api.DELETE).not.toHaveBeenCalled();
  });
});
