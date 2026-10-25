"use client";

import { BanIcon, CheckIcon, FlaskConicalIcon } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { BODY_ROW, CardTable, FOOTNOTE } from "@/components/admin/card-table";
import { useShell } from "@/components/shell/shell-context";
import { Card } from "@/components/ui/card";
import { Pill, type PillTone } from "@/components/ui/pill";
import {
  AGENTS_FOOTNOTE,
  agentStatusLabel,
  effectiveModelLines,
  NO_AGENTS,
  toolPermissionsLabel,
  type AgentStatus,
  type RegistryAgent,
} from "@/lib/admin";

const GRID = "grid-cols-[minmax(0,1fr)_90px_minmax(0,1fr)_120px_minmax(0,1.2fr)]";

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
 * (what it calls here, after any local profile override) and tool permissions as a card table, then the footnote. Each row's name is a button whose
 * hit area covers the row. The rows are one Tab stop (roving tabindex: the last focused, else
 * the selected, else the first row); j/k (or the arrow keys) move between rows and Enter
 * opens the Agent's inspector (Story 7.3). */
export function AgentsTable({
  agents,
  selectedId = null,
  onOpen,
}: {
  agents: readonly RegistryAgent[];
  /** The selected Agent's `agent_id`. */
  selectedId?: string | null;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen?: (agent: RegistryAgent, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const root = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find(
      (id) => id !== null && agents.some((a) => a.agent_id === id),
    ) ?? agents[0]?.agent_id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      root.current?.querySelectorAll<HTMLButtonElement>("button[data-agent-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === document.activeElement);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <>
      <Card ref={root} onKeyDown={onKeyDown} className="overflow-hidden">
        {agents.length === 0 ? (
          <p className="px-5 py-4 text-text-secondary">{NO_AGENTS}</p>
        ) : (
          <CardTable
            label="Agents"
            grid={GRID}
            columns={["Agent", "Version", "Model", "Status", "Tool permissions"]}
          >
            {agents.map((agent) => {
              const selected = agent.agent_id === selectedId;
              const running = effectiveModelLines(agent);
              return (
                <div
                  key={agent.id}
                  role="row"
                  data-agent-id={agent.agent_id}
                  className={`relative py-[18px] ${BODY_ROW} ${GRID} ${
                    selected ? "bg-primary-tint" : "hover:bg-muted/60"
                  }`}
                >
                  <div role="rowheader" className="min-w-0">
                    <button
                      type="button"
                      data-agent-row=""
                      data-agent-id={agent.agent_id}
                      tabIndex={agent.agent_id === tabStopId ? 0 : -1}
                      aria-current={selected ? "true" : undefined}
                      onFocus={() => setFocusedId(agent.agent_id)}
                      // A keyboard-activated click has no pointer clicks (detail 0).
                      onClick={(event) => onOpen?.(agent, event.detail === 0)}
                      className="block max-w-full truncate text-left text-body-strong outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
                    >
                      {agent.name}
                    </button>
                  </div>
                  <div role="cell" className="text-numeric">
                    {agent.current_config.semver}
                  </div>
                  <div role="cell" className="min-w-0 font-mono text-meta">
                    <div className="truncate" title={running.model}>
                      {running.model}
                    </div>
                    <div className="break-words text-text-secondary">{running.profile}</div>
                  </div>
                  <div role="cell">
                    <AgentStatusPill status={agent.status} />
                  </div>
                  <div role="cell" className="min-w-0 text-text-secondary">
                    {toolPermissionsLabel(agent.current_config.tool_permissions)}
                  </div>
                </div>
              );
            })}
          </CardTable>
        )}
      </Card>
      <p className={FOOTNOTE}>{AGENTS_FOOTNOTE}</p>
    </>
  );
}
