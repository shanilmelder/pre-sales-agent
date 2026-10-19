"use client";

import { useId, type Ref } from "react";

import { REASON_MAX } from "@/lib/gaps";
import { codePointLength } from "@/lib/opportunities";

export const reasonFieldClass =
  "w-full rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-[invalid=true]:border-destructive";

/** A labelled textarea with a code-point counter (of the trimmed text) and its error. Shared
 * by the Gaps inspector's reasons (Story 4.4) and a pending Requirement change's rejection
 * (Story 2.7). */
export function ReasonInput({
  label,
  value,
  onChange,
  error,
  disabled,
  inputRef,
  max = REASON_MAX,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  disabled: boolean;
  inputRef?: Ref<HTMLTextAreaElement>;
  /** The most code points the API takes (500). */
  max?: number;
}) {
  const id = useId();
  const countId = useId();
  const errorId = useId();
  const length = codePointLength(value.trim());
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-meta text-muted-foreground">
        {label}
      </label>
      <textarea
        id={id}
        ref={inputRef}
        rows={2}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${countId} ${errorId}` : countId}
        onChange={(event) => onChange(event.target.value)}
        className={`${reasonFieldClass} py-1`}
      />
      <span
        id={countId}
        className={`text-meta [font-variant-numeric:tabular-nums] ${length > max ? "text-destructive" : "text-muted-foreground"}`}
      >
        {`${length}/${max}`}
      </span>
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
