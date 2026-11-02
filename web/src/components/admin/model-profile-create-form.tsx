"use client";

import { useEffect, useId, useRef, useState, useTransition, type FormEvent } from "react";

import { createProfile, type ProfileResult } from "@/app/admin/model-profiles/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  DEFAULT_ANTHROPIC_EFFORT,
  DEFAULT_NUM_CTX,
  DEFAULT_TEMPERATURE,
  modelsFor,
  nameError,
  NO_APPROVED_FOR_PROVIDER,
  numCtxError,
  OFF_HOST_WARNING,
  PROVIDERS,
  REASONING_EFFORTS,
  temperatureError,
  type ApprovedModel,
  type ModelProfile,
  type Provider,
  type ReasoningEffort,
} from "@/lib/model-profiles";

const inputClass =
  "h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";
const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const labelClass = "text-label text-muted-foreground";

type Field = "name" | "numCtx" | "temperature";

/** The create form in the right pane: name, provider, an approved model, context size, and a
 * temperature (`ollama`), either a temperature or a reasoning effort (`openai`), or a reasoning
 * effort (`anthropic`, whose requests never send a temperature). Base URLs and keys stay in the
 * environment, so the form has none. The API's sentences show under the form; nothing is saved
 * on error. */
export function ModelProfileCreateForm({
  approved,
  onCreated,
  onCancel,
}: {
  approved: readonly ApprovedModel[];
  onCreated: (profile: ModelProfile) => void;
  onCancel: () => void;
}) {
  const announce = useAnnounce();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<Provider>("ollama");
  const [model, setModel] = useState(() => modelsFor(approved, "ollama")[0] ?? "");
  const [numCtx, setNumCtx] = useState(String(DEFAULT_NUM_CTX));
  const [temperature, setTemperature] = useState(String(DEFAULT_TEMPERATURE));
  const [effort, setEffort] = useState<ReasoningEffort | "">("");
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const id = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const models = modelsFor(approved, provider);
  const usesEffort = provider === "anthropic" || (provider === "openai" && effort !== "");

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function chooseProvider(next: Provider) {
    setProvider(next);
    setModel(modelsFor(approved, next)[0] ?? "");
    setEffort((current) => (next === "anthropic" ? current || DEFAULT_ANTHROPIC_EFFORT : ""));
  }

  function fail(text: string) {
    setMessage(text);
    announce(text);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const found: Partial<Record<Field, string>> = {};
    const nameProblem = nameError(name);
    if (nameProblem) found.name = nameProblem;
    const numCtxProblem = numCtxError(numCtx);
    if (numCtxProblem) found.numCtx = numCtxProblem;
    const temperatureProblem = usesEffort ? null : temperatureError(temperature);
    if (temperatureProblem) found.temperature = temperatureProblem;
    setErrors(found);
    setMessage(null);
    const first = (["name", "numCtx", "temperature"] as const).find((field) => found[field]);
    if (first) {
      document.getElementById(`${id}-${first}`)?.focus();
      announce(found[first] ?? "");
      return;
    }
    if (!model) {
      fail(NO_APPROVED_FOR_PROVIDER);
      return;
    }
    startTransition(async () => {
      let result: ProfileResult;
      try {
        result = await createProfile({
          name: name.trim(),
          provider,
          model,
          num_ctx: Number(numCtx),
          temperature: usesEffort ? null : Number(temperature),
          reasoning_effort: usesEffort ? (effort as ReasoningEffort) : null,
        });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          announce(`Created ${result.profile.name}. Its live test is queued.`);
          onCreated(result.profile);
          return;
        case "conflict":
        case "invalid":
          fail(result.detail);
          return;
        case "forbidden":
          fail("You don't have access to change model profiles.");
          return;
        default:
          fail("The profile could not be created. Try again.");
      }
    });
  }

  return (
    <form
      onSubmit={submit}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        onCancel();
      }}
      noValidate
      aria-labelledby={`${id}-title`}
      aria-busy={pending}
      className="flex flex-col gap-3 p-gutter"
    >
      <h3 id={`${id}-title`} className="text-section">
        New model profile
      </h3>
      <p role="note" className="rounded-lg border border-gap bg-gap-tint p-3 text-meta">
        {OFF_HOST_WARNING}
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-name`} className={labelClass}>
          Name
        </label>
        <input
          id={`${id}-name`}
          ref={nameRef}
          type="text"
          value={name}
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? `${id}-name-error` : undefined}
          onChange={(event) => setName(event.target.value)}
          className={`${inputClass} font-mono`}
        />
        {errors.name ? (
          <p id={`${id}-name-error`} className="text-meta text-destructive">
            {errors.name}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-provider`} className={labelClass}>
          Provider
        </label>
        <select
          id={`${id}-provider`}
          value={provider}
          onChange={(event) => chooseProvider(event.target.value as Provider)}
          className={inputClass}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-model`} className={labelClass}>
          Model ID
        </label>
        <select
          id={`${id}-model`}
          value={model}
          disabled={models.length === 0}
          onChange={(event) => setModel(event.target.value)}
          className={`${inputClass} font-mono`}
        >
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        {models.length === 0 ? (
          <p className="text-meta text-text-secondary">{NO_APPROVED_FOR_PROVIDER}</p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-numCtx`} className={labelClass}>
          Context size
        </label>
        <input
          id={`${id}-numCtx`}
          type="text"
          inputMode="numeric"
          value={numCtx}
          aria-invalid={errors.numCtx ? true : undefined}
          aria-describedby={errors.numCtx ? `${id}-numCtx-error` : undefined}
          onChange={(event) => setNumCtx(event.target.value)}
          className={inputClass}
        />
        {errors.numCtx ? (
          <p id={`${id}-numCtx-error`} className="text-meta text-destructive">
            {errors.numCtx}
          </p>
        ) : null}
      </div>
      {provider !== "ollama" ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-effort`} className={labelClass}>
            Reasoning effort
          </label>
          <select
            id={`${id}-effort`}
            value={effort}
            onChange={(event) => setEffort(event.target.value as ReasoningEffort | "")}
            className={inputClass}
          >
            {provider === "openai" ? <option value="">None (use temperature)</option> : null}
            {REASONING_EFFORTS.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {usesEffort ? null : (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-temperature`} className={labelClass}>
            Temperature
          </label>
          <input
            id={`${id}-temperature`}
            type="text"
            inputMode="decimal"
            value={temperature}
            aria-invalid={errors.temperature ? true : undefined}
            aria-describedby={errors.temperature ? `${id}-temperature-error` : undefined}
            onChange={(event) => setTemperature(event.target.value)}
            className={inputClass}
          />
          {errors.temperature ? (
            <p id={`${id}-temperature-error`} className="text-meta text-destructive">
              {errors.temperature}
            </p>
          ) : null}
        </div>
      )}
      {message ? <p className="text-meta text-destructive">{message}</p> : null}
      <div className="flex gap-2">
        <button type="submit" aria-disabled={pending || undefined} className={buttonClass}>
          Create and test
        </button>
        <button type="button" onClick={onCancel} className={buttonClass}>
          Cancel
        </button>
      </div>
    </form>
  );
}
