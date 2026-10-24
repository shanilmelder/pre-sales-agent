"use server";

import type {
  AgentConfigOptions,
  AgentConfigVersion,
  AgentStatus,
  RegistryAgent,
} from "@/lib/admin";
import { createServerApiClient } from "@/lib/api/server";

const AGENT_ID_RE = /^[a-z][a-z0-9_]*_agent$/;
const STATUSES: readonly AgentStatus[] = ["active", "disabled", "eval_only"];

export type AgentResult =
  | { kind: "ok"; agent: RegistryAgent }
  /** 412: another administrator changed the Agent first. Nothing was written. */
  | { kind: "stale" }
  /** 409 or 422, with the API's sentence. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type AgentDetailResult =
  | { kind: "ok"; agent: RegistryAgent; versions: AgentConfigVersion[] }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type OptionsResult =
  | { kind: "ok"; options: AgentConfigOptions }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

function isObject(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null;
}

function isAgentId(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && AGENT_ID_RE.test(value);
}

function isRowVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

function detailOf(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

function codeOf(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | undefined)?.code;
  return typeof code === "string" ? code : undefined;
}

function failed<T extends { kind: "error" }>(what: string, thrown: unknown): T {
  console.error(`${what} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
  return { kind: "error" } as T;
}

/** The Agent and its config versions (newest first). Authorization is decided by the API. */
export async function loadAgent(agentId: unknown): Promise<AgentDetailResult> {
  if (!isAgentId(agentId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const params = { params: { path: { agent_id: agentId } } };
    const [agent, versions] = await Promise.all([
      api.GET("/api/v1/registry/agents/{agent_id}", params),
      api.GET("/api/v1/registry/agents/{agent_id}/config-versions", params),
    ]);
    if (agent.data && versions.data) {
      return { kind: "ok", agent: agent.data, versions: versions.data.items };
    }
    const status = (agent.data ? versions.response : agent.response).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "not-found" };
    console.error(`GET registry agent failed: status=${status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET registry agent", thrown);
  }
}

/** What a new config version of the Agent may reference (the deployed manifest). */
export async function loadConfigOptions(agentId: unknown): Promise<OptionsResult> {
  if (!isAgentId(agentId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/agents/{agent_id}/config-options", {
      params: { path: { agent_id: agentId } },
    });
    if (data) return { kind: "ok", options: data };
    if (response.status === 403) return { kind: "forbidden" };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`GET agent config options failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET agent config options", thrown);
  }
}

type Outcome = { data?: RegistryAgent; error?: unknown; response: Response };

function outcome(result: Outcome, what: string): AgentResult {
  if (result.data) return { kind: "ok", agent: result.data };
  switch (result.response.status) {
    case 412:
      return { kind: "stale" };
    case 409:
    case 422:
      return { kind: "invalid", detail: detailOf(result.error) ?? "This config is not valid." };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(
        `${what} failed: status=${result.response.status} code=${String(codeOf(result.error))}`,
      );
      return { kind: "error" };
  }
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/** `POST …/config-versions` with the Agent's row version as `If-Match`. Never retries or
 * overwrites on 412. `restoredFromVersion` marks a restore of that earlier version. */
export async function createConfigVersion(input: unknown): Promise<AgentResult> {
  if (!isObject(input)) return { kind: "error" };
  const { agentId, rowVersion, config, reason, restoredFromVersion } = input;
  if (!isAgentId(agentId) || !isRowVersion(rowVersion) || typeof reason !== "string") {
    return { kind: "error" };
  }
  const restored = restoredFromVersion ?? null;
  if (restored !== null && !isVersion(restored)) return { kind: "error" };
  if (!isObject(config)) return { kind: "error" };
  const {
    semver,
    model_profile,
    prompt_version,
    input_schema_version,
    output_schema_version,
    tool_permissions,
    budgets,
  } = config;
  if (
    typeof semver !== "string" ||
    typeof model_profile !== "string" ||
    !isVersion(prompt_version) ||
    !isVersion(input_schema_version) ||
    !isVersion(output_schema_version) ||
    !isStringList(tool_permissions) ||
    !isObject(budgets) ||
    Array.isArray(budgets)
  ) {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/registry/agents/{agent_id}/config-versions", {
      params: { path: { agent_id: agentId }, header: { "If-Match": `"${rowVersion}"` } },
      body: {
        semver,
        model_profile,
        prompt_version,
        input_schema_version,
        output_schema_version,
        tool_permissions,
        budgets,
        reason,
        restored_from_version: restored,
      },
    });
    return outcome(result, "create agent config version");
  } catch (thrown) {
    return failed("create agent config version", thrown);
  }
}

/** `POST …/status` (enable or disable) with the Agent's row version as `If-Match`. */
export async function setAgentStatus(input: unknown): Promise<AgentResult> {
  if (!isObject(input)) return { kind: "error" };
  const { agentId, rowVersion, status } = input;
  if (!isAgentId(agentId) || !isRowVersion(rowVersion)) return { kind: "error" };
  if (!STATUSES.includes(status as AgentStatus)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/registry/agents/{agent_id}/status", {
      params: { path: { agent_id: agentId }, header: { "If-Match": `"${rowVersion}"` } },
      body: { status: status as AgentStatus },
    });
    return outcome(result, "set agent status");
  } catch (thrown) {
    return failed("set agent status", thrown);
  }
}
