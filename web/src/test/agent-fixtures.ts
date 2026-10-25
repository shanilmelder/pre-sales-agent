import type { AgentConfigOptions, AgentConfigVersion, RegistryAgent } from "@/lib/admin";

export const ADMIN_ID = "00000000-0000-7000-8000-0000000000aa";

/** Config version `n` (1-9) of `agentId`; version 1 is seeded (no author, no reason). */
export function configVersion(
  n: number,
  over: Partial<AgentConfigVersion> = {},
  agentId = "pm_agent",
): AgentConfigVersion {
  const seeded = n === 1;
  return {
    id: `10000000-0000-7000-8000-00000000000${n}`,
    agent_id: agentId,
    version: n,
    semver: `0.${n}.0`,
    model_profile: "demo-chat",
    model_digest: "unpinned",
    prompt_version: 1,
    input_schema_version: 1,
    output_schema_version: 1,
    contract_version: "1",
    tool_permissions: [],
    budgets: {},
    created_by_id: seeded ? null : ADMIN_ID,
    created_by_name: seeded ? null : "[ADMIN]",
    reason: seeded ? null : `Reason ${n}`,
    restored_from_version: null,
    created_at: `2026-10-0${n}T09:00:00Z`,
    ...over,
  };
}

/** A registered Agent at `current`; `n` (1-9) makes its row id distinct. */
export function registryAgent(
  n: number,
  name: string,
  current: AgentConfigVersion,
  over: Partial<RegistryAgent> = {},
): RegistryAgent {
  return {
    id: `00000000-0000-7000-8000-00000000000${n}`,
    agent_id: current.agent_id,
    name,
    status: "active",
    row_version: 1,
    created_at: "2026-10-01T09:00:00Z",
    current_config: current,
    ...over,
  };
}

export const OPTIONS: AgentConfigOptions = {
  model_profiles: ["demo-chat", "local-chat"],
  prompt_versions: [1, 2],
  input_schema_versions: [1],
  output_schema_versions: [1],
  tool_permissions: [
    { action: "gaps.gap.list", category: "read" },
    { action: "intake.requirement.list", category: "read" },
  ],
};
