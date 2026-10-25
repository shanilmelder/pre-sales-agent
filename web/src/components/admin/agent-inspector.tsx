"use client";

import { useEffect, useId, useRef, useState, useTransition, type ReactNode } from "react";

import { loadAgent, setAgentStatus, type AgentResult } from "@/app/admin/agents/actions";
import { AgentConfigDiff } from "@/components/admin/agent-config-diff";
import { AgentConfigForm } from "@/components/admin/agent-config-form";
import { AgentStatusDialog } from "@/components/admin/agent-status-dialog";
import { AgentStatusPill } from "@/components/admin/agents-table";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import {
  AGENT_STALE,
  agentStatusLabel,
  authorLabel,
  changedSummary,
  configValue,
  effectiveModelLines,
  EVAL_ONLY_NOTE,
  NO_REASON,
  SAME_VERSION,
  toolPermissionsLabel,
  type AgentConfigVersion,
  type RegistryAgent,
} from "@/lib/admin";

const SAVE_FAILED = "The change could not be saved. Try again.";
const NO_ACCESS = "You don't have access to change Agents.";
const GONE = "This Agent no longer exists.";
const RELOAD_FAILED = "The Agent could not be reloaded. Try again.";
const HISTORY_FAILED = "The config history could not be loaded.";

const selectClass =
  "h-8 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** A new version (no source: it starts from the current config) or a restore of `source`. */
type Editing = { source: AgentConfigVersion | null; restoredFrom: number | null };

function formatWhen(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function Detail({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-2">
      <dt className="text-label text-muted-foreground">{term}</dt>
      <dd className="min-w-0 text-meta break-words">{children}</dd>
    </div>
  );
}

/** Two versions picked from the history and the fields that differ between them. */
function Compare({ versions }: { versions: readonly AgentConfigVersion[] }) {
  const id = useId();
  const [from, setFrom] = useState(versions[1]?.version ?? versions[0]?.version ?? 1);
  const [to, setTo] = useState(versions[0]?.version ?? 1);
  if (versions.length < 2) return null;
  const before = versions.find((v) => v.version === from);
  const after = versions.find((v) => v.version === to);
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-2">
      <h4 id={`${id}-title`} className="text-label text-muted-foreground">
        Compare versions
      </h4>
      <div className="grid grid-cols-2 gap-2">
        {(
          [
            ["from", "From", from, setFrom],
            ["to", "To", to, setTo],
          ] as const
        ).map(([key, label, value, set]) => (
          <div key={key} className="flex flex-col gap-1">
            <label htmlFor={`${id}-${key}`} className="text-label text-muted-foreground">
              {label}
            </label>
            <select
              id={`${id}-${key}`}
              value={value}
              onChange={(event) => set(Number(event.target.value))}
              className={selectClass}
            >
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  {`v${v.version} · ${v.semver}`}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      {from === to ? (
        <p className="text-meta text-destructive">{SAME_VERSION}</p>
      ) : before && after ? (
        <AgentConfigDiff before={before} after={after} />
      ) : null}
    </section>
  );
}

/** The selected Agent in the right pane (Story 7.3): its current config, Enable/Disable
 * behind a confirm dialog, a form for a new version (or a restore of an earlier one, which
 * prefills it) with a required reason, the config history newest first and a two-version
 * diff. The history reloads after every change. A 412 shows the concurrent-edit message with
 * Reload, overwrites nothing and keeps the form's input. */
export function AgentInspector({
  agent,
  onChange,
  focusRequest = 0,
}: {
  agent: RegistryAgent;
  /** Called with the Agent as stored after a save or a reload. */
  onChange: (agent: RegistryAgent) => void;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const announce = useAnnounce();
  const headingId = useId();
  const [versions, setVersions] = useState<AgentConfigVersion[] | null>(null);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [historyRequest, setHistoryRequest] = useState(0);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [stale, setStale] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const config = agent.current_config;
  const running = effectiveModelLines(agent);
  const enabled = agent.status === "active";

  // The history of the Agent shown; it is loaded again after every change.
  useEffect(() => {
    let live = true;
    loadAgent(agent.agent_id)
      .then((result) => {
        if (!live) return;
        if (result.kind === "ok") {
          setVersions(result.versions);
          setHistoryFailed(false);
        } else {
          setHistoryFailed(true);
        }
      })
      .catch(() => {
        if (live) setHistoryFailed(true);
      });
    return () => {
      live = false;
    };
  }, [agent.agent_id, agent.row_version, historyRequest]);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  function showStale() {
    setStale(true);
    announce(AGENT_STALE);
  }

  function saved(next: RegistryAgent) {
    setEditing(null);
    setMessage(null);
    onChange(next);
    announce(`Saved ${next.name} version ${next.current_config.version}`);
    headingRef.current?.focus();
  }

  function changeStatus() {
    if (pending || stale) return;
    setMessage(null);
    startTransition(async () => {
      let result: AgentResult;
      try {
        result = await setAgentStatus({
          agentId: agent.agent_id,
          rowVersion: agent.row_version,
          status: enabled ? "disabled" : "active",
        });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          onChange(result.agent);
          announce(`${result.agent.name}: ${agentStatusLabel(result.agent.status)}`);
          return;
        case "stale":
          showStale();
          return;
        case "invalid":
          setMessage(result.detail);
          return;
        case "forbidden":
          setMessage(NO_ACCESS);
          return;
        case "not-found":
          setMessage(GONE);
          return;
        default:
          setMessage(SAVE_FAILED);
      }
    });
  }

  function reload() {
    if (pending) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadAgent>>;
      try {
        result = await loadAgent(agent.agent_id);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        setStale(false);
        setVersions(result.versions);
        setHistoryFailed(false);
        // A restore keeps its source version; a new version starts from the reloaded
        // current config (the form re-prefills from both).
        const restoredFrom = editing?.restoredFrom ?? null;
        if (editing && restoredFrom !== null) {
          const source = result.versions.find((v) => v.version === restoredFrom);
          setEditing({ restoredFrom, source: source ?? editing.source });
        }
        onChange(result.agent);
        announce(`Reloaded ${result.agent.name}`);
        headingRef.current?.focus();
      } else if (result.kind === "not-found") {
        setMessage(GONE);
      } else if (result.kind === "forbidden") {
        setMessage(NO_ACCESS);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce(RELOAD_FAILED);
      }
    });
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
            {agent.name}
          </h3>
          <AgentStatusPill status={agent.status} />
        </div>
        <p className="font-mono text-meta text-muted-foreground">{agent.agent_id}</p>
      </div>

      <section aria-label="Current config">
        <dl className="flex flex-col gap-1.5">
        <Detail term="Agent ID">
          <span className="font-mono">{agent.agent_id}</span>
        </Detail>
        <Detail term="Status">{agentStatusLabel(agent.status)}</Detail>
        <Detail term="Current version">
          <span className="text-numeric">{`v${config.version}`}</span>
        </Detail>
        <Detail term="Semver">
          <span className="text-numeric">{config.semver}</span>
        </Detail>
        <Detail term="Model profile">
          <span className="font-mono">{config.model_profile}</span>
        </Detail>
        <Detail term="Runs with">
          <span className="font-mono">{`${running.model} · ${running.profile}`}</span>
        </Detail>
        <Detail term="Prompt version">{configValue("prompt_version", config)}</Detail>
        <Detail term="Input schema version">{configValue("input_schema_version", config)}</Detail>
        <Detail term="Output schema version">
          {configValue("output_schema_version", config)}
        </Detail>
        <Detail term="Tool permissions">{toolPermissionsLabel(config.tool_permissions)}</Detail>
        <Detail term="Budgets">
          <span className="font-mono">{configValue("budgets", config)}</span>
        </Detail>
        </dl>
      </section>

      {stale ? (
        <InlineAlert
          lead={AGENT_STALE}
          onReload={reload}
          reloading={pending}
          reloadRef={reloadRef}
        />
      ) : null}
      {message ? (
        <p role="alert" className="text-meta text-destructive">
          {message}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {editing === null ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pending}
            onClick={() => setEditing({ source: null, restoredFrom: null })}
          >
            New version
          </Button>
        ) : null}
        {agent.status === "eval_only" ? (
          <p className="text-meta text-muted-foreground">{EVAL_ONLY_NOTE}</p>
        ) : (
          <AgentStatusDialog
            agentName={agent.name}
            enabled={enabled}
            busy={pending || stale}
            onConfirm={changeStatus}
          />
        )}
      </div>

      {editing ? (
        <AgentConfigForm
          key={editing.restoredFrom ?? "new"}
          agent={agent}
          initial={editing.source ?? config}
          restoredFrom={editing.restoredFrom}
          locked={stale}
          onSaved={saved}
          onStale={showStale}
          onCancel={() => {
            setEditing(null);
            headingRef.current?.focus();
          }}
        />
      ) : null}

      <section aria-label="Config history" className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Config history</h4>
        {versions === null && historyFailed ? (
          <div className="flex items-center gap-2">
            <p role="alert" className="text-meta text-destructive">
              {HISTORY_FAILED}
            </p>
            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={() => {
                setHistoryFailed(false);
                setHistoryRequest((n) => n + 1);
              }}
            >
              Retry
            </Button>
          </div>
        ) : versions === null ? (
          <p className="text-meta text-muted-foreground">Loading…</p>
        ) : (
          <ol className="flex flex-col">
            {versions.map((v, index) => {
              const current = v.version === config.version;
              return (
                <li
                  key={v.id}
                  data-version={v.version}
                  className="flex flex-col gap-0.5 border-b border-border py-2"
                >
                  <p className="text-label">
                    <span className="text-numeric">{`v${v.version} · ${v.semver}`}</span>
                    {current ? " (current)" : ""}
                  </p>
                  <p className="text-meta text-muted-foreground">
                    {authorLabel(v)} · {formatWhen(v.created_at)}
                  </p>
                  <p className="text-meta">Reason: {v.reason ?? NO_REASON}</p>
                  <p className="text-meta text-muted-foreground">
                    {changedSummary(v, versions[index + 1] ?? null)}
                  </p>
                  {v.restored_from_version !== null ? (
                    <p className="text-meta">{`Restored from v${v.restored_from_version}`}</p>
                  ) : null}
                  {!current ? (
                    <div>
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
                        disabled={pending}
                        aria-label={`Restore this version (v${v.version})`}
                        onClick={() => setEditing({ source: v, restoredFrom: v.version })}
                      >
                        Restore this version
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {versions && versions.length >= 2 ? (
        <Compare key={versions[0].id} versions={versions} />
      ) : null}
    </section>
  );
}
