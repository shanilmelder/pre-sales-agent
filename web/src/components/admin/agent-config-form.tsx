"use client";

import { useEffect, useId, useRef, useState, useTransition, type FormEvent } from "react";

import {
  createConfigVersion,
  loadConfigOptions,
  type AgentResult,
} from "@/app/admin/agents/actions";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  AGENT_REASON_MAX,
  budgetsText,
  nextPatch,
  parseBudgets,
  reasonError,
  type AgentConfigOptions,
  type AgentConfigVersion,
  type RegistryAgent,
} from "@/lib/admin";

const SAVE_FAILED = "The version could not be saved. Try again.";
const NO_ACCESS = "You don't have access to change Agents.";
const GONE = "This Agent no longer exists.";
const OPTIONS_FAILED = "The deployed options could not be loaded. Try again.";

const inputClass =
  "h-8 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";

/** The deployed choices plus the value the form starts from (a restored version may hold one
 * that is no longer deployed: the API then refuses it with its sentence). */
function withValue<T extends string | number>(choices: readonly T[], value: T): T[] {
  const all = choices.includes(value) ? [...choices] : [...choices, value];
  return all.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/** A new config version of the Agent (Story 7.3), prefilled from `initial` (the current
 * version, or the version being restored) with the next patch semver. The pickers offer only
 * what the deployed manifest holds: model profiles, this Agent's prompt and schema versions
 * and the read-only tools. Budgets are a JSON object. A reason is required; Save stays
 * disabled without one. A 412 is reported to the parent (`onStale`) and the form keeps its
 * input; a 409 or 422 shows the API's sentence. */
export function AgentConfigForm({
  agent,
  initial,
  restoredFrom = null,
  locked = false,
  onSaved,
  onStale,
  onCancel,
}: {
  agent: RegistryAgent;
  initial: AgentConfigVersion;
  /** The version being restored, or null for a new version. */
  restoredFrom?: number | null;
  /** A stale notice is showing: saving is off until the Agent is reloaded. */
  locked?: boolean;
  onSaved: (agent: RegistryAgent) => void;
  onStale: () => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [options, setOptions] = useState<AgentConfigOptions | null>(null);
  const [optionsFailed, setOptionsFailed] = useState(false);
  const [semver, setSemver] = useState(nextPatch(agent.current_config.semver));
  const [profile, setProfile] = useState(initial.model_profile);
  const [prompt, setPrompt] = useState(initial.prompt_version);
  const [inputSchema, setInputSchema] = useState(initial.input_schema_version);
  const [outputSchema, setOutputSchema] = useState(initial.output_schema_version);
  const [permissions, setPermissions] = useState<string[]>(initial.tool_permissions);
  const [budgets, setBudgets] = useState(budgetsText(initial.budgets));
  const [budgetsError, setBudgetsError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const readOnly = restoredFrom !== null;

  // After a Reload the Agent (and so the source config or the current semver) may have
  // changed: prefill the config again from it, keeping the typed reason.
  const prefill = `${initial.id}|${agent.current_config.id}`;
  const [prefilledFrom, setPrefilledFrom] = useState(prefill);
  if (prefill !== prefilledFrom) {
    setPrefilledFrom(prefill);
    setSemver(nextPatch(agent.current_config.semver));
    setProfile(initial.model_profile);
    setPrompt(initial.prompt_version);
    setInputSchema(initial.input_schema_version);
    setOutputSchema(initial.output_schema_version);
    setPermissions(initial.tool_permissions);
    setBudgets(budgetsText(initial.budgets));
    setBudgetsError(null);
    setMessage(null);
  }

  useEffect(() => {
    let live = true;
    loadConfigOptions(agent.agent_id)
      .then((result) => {
        if (!live) return;
        if (result.kind === "ok") setOptions(result.options);
        else setOptionsFailed(true);
      })
      .catch(() => {
        if (live) setOptionsFailed(true);
      });
    return () => {
      live = false;
    };
  }, [agent.agent_id]);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const reasonProblem = reasonError(reason);
  const shownReasonError = reasonTouched ? reasonProblem : null;
  const reasonLength = Array.from(reason.trim()).length;
  const blocked = pending || locked || options === null || reasonProblem !== null;

  function handle(result: AgentResult) {
    switch (result.kind) {
      case "ok":
        onSaved(result.agent);
        return;
      case "stale":
        onStale();
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
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setReasonTouched(true);
    if (blocked) return;
    const parsed = parseBudgets(budgets);
    if (!parsed.ok) {
      setBudgetsError(parsed.error);
      return;
    }
    setBudgetsError(null);
    setMessage(null);
    startTransition(async () => {
      let result: AgentResult;
      try {
        result = await createConfigVersion({
          agentId: agent.agent_id,
          rowVersion: agent.row_version,
          config: {
            semver: semver.trim(),
            model_profile: profile,
            prompt_version: prompt,
            input_schema_version: inputSchema,
            output_schema_version: outputSchema,
            tool_permissions: permissions,
            budgets: parsed.value,
          },
          reason,
          restoredFromVersion: restoredFrom,
        });
      } catch {
        result = { kind: "error" };
      }
      handle(result);
    });
  }

  const title = restoredFrom === null ? "New version" : `Restore version ${restoredFrom}`;
  const tools = options
    ? [...new Set([...options.tool_permissions, ...initial.tool_permissions])].sort()
    : [];

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-labelledby={`${id}-title`}
      aria-busy={pending}
      className="flex flex-col gap-3 rounded-lg border border-border p-3"
    >
      <h4 id={`${id}-title`} ref={titleRef} tabIndex={-1} className="text-body-strong outline-none">
        {title}
      </h4>
      {restoredFrom !== null ? (
        <p className="text-meta text-muted-foreground">
          Copied from version {restoredFrom}; only the semver and the reason can change. Saving
          adds a new version; version {restoredFrom} stays as it is.
        </p>
      ) : null}
      {options === null && !optionsFailed ? (
        <p className="text-meta text-muted-foreground">Loading the deployed options…</p>
      ) : null}
      {optionsFailed ? <p className="text-meta text-destructive">{OPTIONS_FAILED}</p> : null}

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-semver`} className="text-label text-muted-foreground">
          Semver
        </label>
        <input
          id={`${id}-semver`}
          type="text"
          value={semver}
          onChange={(event) => setSemver(event.target.value)}
          className={`${inputClass} font-mono`}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-profile`} className="text-label text-muted-foreground">
          Model profile
        </label>
        <select
          id={`${id}-profile`}
          value={profile}
          disabled={readOnly}
          onChange={(event) => setProfile(event.target.value)}
          className={inputClass}
        >
          {withValue(options?.model_profiles ?? [], profile).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      {(
        [
          ["prompt", "Prompt version", prompt, setPrompt, options?.prompt_versions],
          [
            "input",
            "Input schema version",
            inputSchema,
            setInputSchema,
            options?.input_schema_versions,
          ],
          [
            "output",
            "Output schema version",
            outputSchema,
            setOutputSchema,
            options?.output_schema_versions,
          ],
        ] as const
      ).map(([key, label, value, set, choices]) => (
        <div key={key} className="flex flex-col gap-1">
          <label htmlFor={`${id}-${key}`} className="text-label text-muted-foreground">
            {label}
          </label>
          <select
            id={`${id}-${key}`}
            value={value}
            disabled={readOnly}
            onChange={(event) => set(Number(event.target.value))}
            className={inputClass}
          >
            {withValue(choices ?? [], value).map((v) => (
              <option key={v} value={v}>
                {`v${v}`}
              </option>
            ))}
          </select>
        </div>
      ))}
      <fieldset className="flex flex-col gap-1">
        <legend className="text-label text-muted-foreground">Tool permissions (read only)</legend>
        {tools.length === 0 && options !== null ? (
          <p className="text-meta text-muted-foreground">No read tools are deployed.</p>
        ) : null}
        {tools.map((tool) => (
          <label key={tool} className="flex items-center gap-2 text-meta">
            <input
              type="checkbox"
              checked={permissions.includes(tool)}
              disabled={readOnly}
              onChange={(event) =>
                setPermissions((current) =>
                  event.target.checked ? [...current, tool] : current.filter((p) => p !== tool),
                )
              }
            />
            <span className="font-mono">{tool}</span>
          </label>
        ))}
      </fieldset>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-budgets`} className="text-label text-muted-foreground">
          Budgets (JSON object, at most 20 keys)
        </label>
        <textarea
          id={`${id}-budgets`}
          rows={3}
          value={budgets}
          readOnly={readOnly}
          spellCheck={false}
          aria-invalid={budgetsError ? true : undefined}
          aria-describedby={budgetsError ? `${id}-budgets-error` : undefined}
          onChange={(event) => setBudgets(event.target.value)}
          className="min-h-16 w-full resize-y rounded-md border border-input bg-transparent px-1.5 py-1 font-mono text-meta outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive"
        />
        {budgetsError ? (
          <p id={`${id}-budgets-error`} className="text-meta text-destructive">
            {budgetsError}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-reason`} className="text-label">
          Reason (required)
        </label>
        <Textarea
          id={`${id}-reason`}
          rows={3}
          value={reason}
          aria-invalid={shownReasonError ? true : undefined}
          aria-describedby={
            shownReasonError ? `${id}-reason-count ${id}-reason-error` : `${id}-reason-count`
          }
          onChange={(event) => {
            setReason(event.target.value);
            setReasonTouched(true);
          }}
          onBlur={() => setReasonTouched(true)}
        />
        <span
          id={`${id}-reason-count`}
          className={`self-end text-meta [font-variant-numeric:tabular-nums] ${
            reasonLength > AGENT_REASON_MAX ? "text-destructive" : "text-muted-foreground"
          }`}
        >
          {`${reasonLength}/${AGENT_REASON_MAX}`}
        </span>
        {shownReasonError ? (
          <p id={`${id}-reason-error`} className="text-meta text-destructive">
            {shownReasonError}
          </p>
        ) : null}
      </div>
      {message ? (
        <p role="alert" className="text-meta text-destructive">
          {message}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={blocked}>
          {restoredFrom === null ? "Save version" : "Save restored version"}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
