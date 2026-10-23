import { BanIcon, CheckIcon, FlaskConicalIcon } from "lucide-react";

import { BODY_ROW, CardTable, FOOTNOTE } from "@/components/admin/card-table";
import { Card } from "@/components/ui/card";
import { Pill, type PillTone } from "@/components/ui/pill";
import {
  AGENTS_FOOTNOTE,
  agentStatusLabel,
  NO_AGENTS,
  toolPermissionsLabel,
  type AgentStatus,
  type RegistryAgent,
} from "@/lib/admin";

const GRID = "grid-cols-[minmax(0,1fr)_90px_170px_120px_minmax(0,1.2fr)]";

const STATUS_STYLE: Record<AgentStatus, { tone: PillTone; Icon: typeof CheckIcon }> = {
  active: { tone: "resolved", Icon: CheckIcon },
  disabled: { tone: "neutral", Icon: BanIcon },
  eval_only: { tone: "neutral", Icon: FlaskConicalIcon },
};

/** The Agent's status: always an icon and a label, never colour alone. */
export function AgentStatusPill({ status }: { status: AgentStatus }) {
  const { tone, Icon } = STATUS_STYLE[status];
  return (
    <Pill data-agent-status={status} tone={tone} icon={<Icon />} className="shrink-0">
      {agentStatusLabel(status)}
    </Pill>
  );
}

/** Admin → Agents: every registered Agent with its current config version, model, status
 * and tool permissions, as a read-only card table, then the footnote. */
export function AgentsTable({ agents }: { agents: readonly RegistryAgent[] }) {
  return (
    <>
      <Card className="overflow-hidden">
        {agents.length === 0 ? (
          <p className="px-5 py-4 text-text-secondary">{NO_AGENTS}</p>
        ) : (
          <CardTable
            scrollable
            label="Agents"
            grid={GRID}
            columns={["Agent", "Version", "Model", "Status", "Tool permissions"]}
          >
            {agents.map((agent) => (
              <div
                key={agent.id}
                role="row"
                data-agent-id={agent.agent_id}
                className={`py-[18px] ${BODY_ROW} ${GRID}`}
              >
                <div role="rowheader" className="min-w-0 truncate text-body-strong">
                  {agent.name}
                </div>
                <div role="cell" className="text-numeric">
                  {agent.current_config.semver}
                </div>
                <div role="cell" className="min-w-0 truncate font-mono text-meta">
                  {agent.current_config.model_profile}
                </div>
                <div role="cell">
                  <AgentStatusPill status={agent.status} />
                </div>
                <div role="cell" className="min-w-0 text-text-secondary">
                  {toolPermissionsLabel(agent.current_config.tool_permissions)}
                </div>
              </div>
            ))}
          </CardTable>
        )}
      </Card>
      <p className={FOOTNOTE}>{AGENTS_FOOTNOTE}</p>
    </>
  );
}
