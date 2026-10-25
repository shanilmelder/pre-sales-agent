import { beforeEach, describe, expect, it, vi } from "vitest";

import { configVersion, OPTIONS, registryAgent } from "@/test/agent-fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import { createConfigVersion, loadAgent, loadConfigOptions, setAgentStatus } from "./actions";

const V2 = configVersion(2);
const AGENT = registryAgent(1, "PM Agent", V2, { row_version: 4 });
const status = (code: number) => new Response(null, { status: code });
const CONFIG = {
  semver: "0.2.1",
  model_profile: "demo-chat",
  prompt_version: 2,
  input_schema_version: 1,
  output_schema_version: 1,
  tool_permissions: ["gaps.gap.list"],
  budgets: { max_tokens_per_run: 20000 },
};

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
});

describe("loadAgent", () => {
  it("reads the Agent and its versions", async () => {
    api.GET.mockImplementation(async (path: string) =>
      path.endsWith("config-versions")
        ? { data: { items: [V2, configVersion(1)] }, response: status(200) }
        : { data: AGENT, response: status(200) },
    );
    expect(await loadAgent("pm_agent")).toEqual({
      kind: "ok",
      agent: AGENT,
      versions: [V2, configVersion(1)],
    });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/registry/agents/{agent_id}", {
      params: { path: { agent_id: "pm_agent" } },
    });
  });

  it("maps 403 and 404, and refuses a malformed id without calling the API", async () => {
    api.GET.mockResolvedValue({ data: undefined, response: status(403) });
    expect(await loadAgent("pm_agent")).toEqual({ kind: "forbidden" });
    api.GET.mockResolvedValue({ data: undefined, response: status(404) });
    expect(await loadAgent("pm_agent")).toEqual({ kind: "not-found" });
    api.GET.mockReset();
    expect(await loadAgent("../users")).toEqual({ kind: "not-found" });
    expect(api.GET).not.toHaveBeenCalled();
  });
});

describe("loadConfigOptions", () => {
  it("reads the deployed options", async () => {
    api.GET.mockResolvedValue({ data: OPTIONS, response: status(200) });
    expect(await loadConfigOptions("pm_agent")).toEqual({ kind: "ok", options: OPTIONS });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/registry/agents/{agent_id}/config-options", {
      params: { path: { agent_id: "pm_agent" } },
    });
  });

  it("maps 403", async () => {
    api.GET.mockResolvedValue({ data: undefined, response: status(403) });
    expect(await loadConfigOptions("pm_agent")).toEqual({ kind: "forbidden" });
  });
});

describe("createConfigVersion", () => {
  it("posts the config and reason with the row version as If-Match", async () => {
    api.POST.mockResolvedValue({ data: AGENT, response: status(201) });
    const result = await createConfigVersion({
      agentId: "pm_agent",
      rowVersion: 4,
      config: CONFIG,
      reason: "Tighter prompt",
      restoredFromVersion: null,
    });
    expect(result).toEqual({ kind: "ok", agent: AGENT });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/registry/agents/{agent_id}/config-versions", {
      params: { path: { agent_id: "pm_agent" }, header: { "If-Match": '"4"' } },
      body: { ...CONFIG, reason: "Tighter prompt", restored_from_version: null },
    });
  });

  it("sends the restored version", async () => {
    api.POST.mockResolvedValue({ data: AGENT, response: status(201) });
    await createConfigVersion({
      agentId: "pm_agent",
      rowVersion: 4,
      config: CONFIG,
      reason: "Back",
      restoredFromVersion: 1,
    });
    expect(api.POST.mock.calls[0][1].body.restored_from_version).toBe(1);
  });

  it("maps 412 to stale and 422 / 409 to the API's sentence", async () => {
    const input = { agentId: "pm_agent", rowVersion: 4, config: CONFIG, reason: "R" };
    api.POST.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    expect(await createConfigVersion(input)).toEqual({ kind: "stale" });
    const detail = "Not in the deployed manifest for pm_agent: prompt v9.";
    api.POST.mockResolvedValue({
      error: { code: "registry_config_not_deployed", detail },
      response: status(422),
    });
    expect(await createConfigVersion(input)).toEqual({ kind: "invalid", detail });
    api.POST.mockResolvedValue({ error: { detail: "Taken" }, response: status(409) });
    expect(await createConfigVersion(input)).toEqual({ kind: "invalid", detail: "Taken" });
    api.POST.mockResolvedValue({ error: {}, response: status(403) });
    expect(await createConfigVersion(input)).toEqual({ kind: "forbidden" });
  });

  it("rejects malformed input without calling the API", async () => {
    for (const bad of [
      null,
      { agentId: "pm_agent", rowVersion: 4, config: CONFIG },
      { agentId: "x", rowVersion: 4, config: CONFIG, reason: "R" },
      { agentId: "pm_agent", rowVersion: -1, config: CONFIG, reason: "R" },
      { agentId: "pm_agent", rowVersion: 4, config: { ...CONFIG, prompt_version: 0 }, reason: "R" },
      { agentId: "pm_agent", rowVersion: 4, config: { ...CONFIG, budgets: [] }, reason: "R" },
      { agentId: "pm_agent", rowVersion: 4, config: CONFIG, reason: "R", restoredFromVersion: 0 },
    ]) {
      expect(await createConfigVersion(bad)).toEqual({ kind: "error" });
    }
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("setAgentStatus", () => {
  it("posts the status with If-Match", async () => {
    api.POST.mockResolvedValue({ data: AGENT, response: status(200) });
    await setAgentStatus({ agentId: "pm_agent", rowVersion: 4, status: "disabled" });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/registry/agents/{agent_id}/status", {
      params: { path: { agent_id: "pm_agent" }, header: { "If-Match": '"4"' } },
      body: { status: "disabled" },
    });
  });

  it("maps 412 to stale and refuses an unknown status", async () => {
    api.POST.mockResolvedValue({ error: {}, response: status(412) });
    expect(await setAgentStatus({ agentId: "pm_agent", rowVersion: 4, status: "active" })).toEqual({
      kind: "stale",
    });
    api.POST.mockReset();
    expect(await setAgentStatus({ agentId: "pm_agent", rowVersion: 4, status: "off" })).toEqual({
      kind: "error",
    });
    expect(api.POST).not.toHaveBeenCalled();
  });
});
