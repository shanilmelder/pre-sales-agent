"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { codePointLength } from "@/lib/opportunities";
import { mixSum, REASON_LABEL, REASON_MAX, ROLES, type RoleMix } from "@/lib/estimates";

const buttonClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";
const primaryClass =
  "h-6 shrink-0 rounded-md bg-primary px-2 text-label text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 disabled:cursor-default disabled:opacity-60";
const inputClass =
  "h-6 rounded-md border border-input bg-background px-1.5 text-numeric outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** Esc anywhere in an editor cancels it (and stays inside it: the grid sees nothing). */
function onEscape(cancel: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
  };
}

/** The compact role-mix editor: one whole-number field per role and a live "= {sum}%" check;
 * Save is disabled until the shares are whole numbers adding up to 100. Esc or Cancel
 * closes it unchanged. */
export function RoleMixEditor({
  lineTitle,
  initial,
  onSave,
  onCancel,
}: {
  lineTitle: string;
  initial: RoleMix;
  onSave: (mix: RoleMix) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(ROLES.map((role) => [role.value, String(initial[role.value])])),
  );
  const firstRef = useRef<HTMLInputElement>(null);
  const sumId = useId();
  const ruleId = useId();

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  const parsed = ROLES.map((role) => {
    const text = values[role.value].trim();
    return /^\d{1,3}$/.test(text) ? Number(text) : null;
  });
  const fieldValid = parsed.map((v) => v !== null && v <= 100);
  const whole = parsed.every((v, i): v is number => fieldValid[i]);
  const mix = whole
    ? (Object.fromEntries(ROLES.map((role, i) => [role.value, parsed[i]])) as RoleMix)
    : null;
  const sum = parsed.reduce<number>((total, v) => total + (v ?? 0), 0);
  const valid = mix !== null && mixSum(mix) === 100;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && mix) onSave(mix);
  }

  return (
    <form
      aria-label={`Role mix of ${lineTitle}`}
      onSubmit={submit}
      onKeyDown={onEscape(onCancel)}
      className="flex flex-wrap items-center gap-2"
    >
      {ROLES.map((role, i) => (
        <label key={role.value} className="flex items-center gap-1 text-label">
          <span>{role.label} (%)</span>
          <input
            ref={i === 0 ? firstRef : undefined}
            type="text"
            inputMode="numeric"
            aria-describedby={fieldValid[i] ? sumId : `${sumId} ${ruleId}`}
            aria-invalid={fieldValid[i] ? undefined : true}
            value={values[role.value]}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                [role.value]: event.target.value,
              }))
            }
            className={`${inputClass} w-12 text-right`}
          />
        </label>
      ))}
      <span
        id={sumId}
        aria-live="polite"
        data-valid={valid}
        className={`text-label [font-variant-numeric:tabular-nums] ${valid ? "text-muted-foreground" : "text-destructive"}`}
      >
        {`= ${sum}%`}
      </span>
      {whole ? null : (
        <span id={ruleId} className="text-label text-destructive">
          Whole numbers 0–100
        </span>
      )}
      <button type="submit" disabled={!valid} className={primaryClass}>
        Save
      </button>
      <button type="button" onClick={onCancel} className={buttonClass}>
        Cancel
      </button>
    </form>
  );
}

/** The compact reason prompt shown before a change is saved: prefilled with the user's last
 * reason in this version. Save is disabled while the trimmed reason is empty or longer than
 * 300 characters; Esc or Cancel drops the change. */
export function ReasonPrompt({
  summary,
  initial,
  busy = false,
  onSave,
  onCancel,
}: {
  /** What is about to change, e.g. "Effort 40.0 h → 32.0 h". */
  summary: string;
  initial: string;
  busy?: boolean;
  onSave: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const summaryId = useId();
  const countId = useId();

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const length = codePointLength(reason.trim());
  const valid = length > 0 && length <= REASON_MAX;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && !busy) onSave(reason.trim());
  }

  return (
    <form
      aria-label={REASON_LABEL}
      onSubmit={submit}
      onKeyDown={onEscape(() => {
        if (!busy) onCancel();
      })}
      className="flex flex-wrap items-center gap-2"
    >
      <span id={summaryId} className="text-label text-muted-foreground">
        {summary}
      </span>
      <label htmlFor={inputId} className="text-label">
        {REASON_LABEL}
      </label>
      <input
        id={inputId}
        ref={inputRef}
        type="text"
        value={reason}
        maxLength={REASON_MAX * 2}
        aria-describedby={`${summaryId} ${countId}`}
        disabled={busy}
        onChange={(event) => setReason(event.target.value)}
        className={`${inputClass} min-w-48 flex-1 text-body`}
      />
      <span
        id={countId}
        data-over={length > REASON_MAX || undefined}
        className={`text-meta [font-variant-numeric:tabular-nums] ${length > REASON_MAX ? "text-destructive" : "text-muted-foreground"}`}
      >
        {length > REASON_MAX
          ? `${length}/${REASON_MAX}: shorten the reason to save`
          : `${length}/${REASON_MAX}`}
      </span>
      <button type="submit" disabled={!valid || busy} className={primaryClass}>
        Save
      </button>
      <button type="button" disabled={busy} onClick={onCancel} className={buttonClass}>
        Cancel
      </button>
    </form>
  );
}
