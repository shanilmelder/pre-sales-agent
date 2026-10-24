"use client";

import { useEffect, useRef, useState } from "react";

import { AgentInspector } from "@/components/admin/agent-inspector";
import { AgentsTable } from "@/components/admin/agents-table";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import type { RegistryAgent } from "@/lib/admin";

/** Admin → Agents (Story 7.3): the Agent table in the main pane and the selected Agent's
 * inspector in the right pane. A saved version or status change updates the row in place;
 * new server data replaces the rows. */
export function AgentsAdmin({ initialAgents }: { initialAgents: readonly RegistryAgent[] }) {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [agents, setAgents] = useState<readonly RegistryAgent[]>(initialAgents);
  const [syncedFrom, setSyncedFrom] = useState(initialAgents);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  // A server refresh (e.g. revisiting the page) brings new rows.
  if (initialAgents !== syncedFrom) {
    setSyncedFrom(initialAgents);
    setAgents(initialAgents);
  }

  const selected = agents.find((agent) => agent.agent_id === selectedId) ?? null;

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`button[data-agent-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(agent: RegistryAgent, viaKeyboard: boolean) {
    setSelectedId(agent.agent_id);
    returnFocusTo.current = viaKeyboard ? agent.agent_id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: RegistryAgent) {
    setAgents((current) => current.map((a) => (a.agent_id === next.agent_id ? next : a)));
  }

  return (
    <>
      <AgentsTable agents={agents} selectedId={selectedId} onOpen={open} />
      {selected ? (
        <RightPaneContent>
          <AgentInspector
            key={selected.agent_id}
            agent={selected}
            onChange={replace}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}
