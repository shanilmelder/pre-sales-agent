"use client";

import { useEffect, useId, useRef, useState, useTransition, type FormEvent } from "react";

import { createEntry, type EntryResult } from "@/app/admin/catalogue/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  fieldError,
  KINDS,
  type CatalogueEntry,
  type CatalogueKind,
} from "@/lib/catalogue";

const inputClass =
  "h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";
const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";

type Field = "code" | "name" | "definition";
const LABELS: Record<Field, string> = { code: "Code", name: "Name", definition: "Definition" };

/** The create form in the right pane (`c` opens it): kind, code, name and definition. The
 * API's duplicate and validation sentences show under the form; nothing is saved on error. */
export function CatalogueCreateForm({
  onCreated,
  onCancel,
}: {
  onCreated: (entry: CatalogueEntry) => void;
  /** `viaKey` is true for Esc, so the parent can move focus back. */
  onCancel: (viaKey: boolean) => void;
}) {
  const announce = useAnnounce();
  const [kind, setKind] = useState<CatalogueKind>("integration_type");
  const [values, setValues] = useState<Record<Field, string>>({
    code: "",
    name: "",
    definition: "",
  });
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const id = useId();
  const kindRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    kindRef.current?.focus();
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const found: Partial<Record<Field, string>> = {};
    for (const field of ["code", "name", "definition"] as const) {
      const error = fieldError(field, values[field]);
      if (error) found[field] = error;
    }
    setErrors(found);
    setMessage(null);
    const first = Object.keys(found)[0] as Field | undefined;
    if (first) {
      document.getElementById(`${id}-${first}`)?.focus();
      announce(found[first] ?? "");
      return;
    }
    startTransition(async () => {
      let result: EntryResult;
      try {
        result = await createEntry({ kind, ...values });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          announce(`Created ${result.entry.name}`);
          onCreated(result.entry);
          return;
        case "duplicate":
        case "invalid":
          setMessage(result.detail);
          announce(result.detail);
          return;
        case "forbidden":
          setMessage("You don't have access to change the catalogue.");
          announce("You don't have access to change the catalogue.");
          return;
        default:
          setMessage("The entry could not be created. Try again.");
          announce("The entry could not be created. Try again.");
      }
    });
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onCancel(true);
    }
  }

  return (
    <form
      onSubmit={submit}
      onKeyDown={onKeyDown}
      noValidate
      aria-labelledby={`${id}-title`}
      aria-busy={pending}
      className="flex flex-col gap-3 p-gutter"
    >
      <h3 id={`${id}-title`} className="text-section">
        New catalogue entry
      </h3>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-kind`} className="text-label text-muted-foreground">
          Kind
        </label>
        <select
          id={`${id}-kind`}
          ref={kindRef}
          value={kind}
          onChange={(event) => setKind(event.target.value as CatalogueKind)}
          className={inputClass}
        >
          {KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </div>
      {(["code", "name"] as const).map((field) => (
        <div key={field} className="flex flex-col gap-1">
          <label htmlFor={`${id}-${field}`} className="text-label text-muted-foreground">
            {LABELS[field]}
          </label>
          <input
            id={`${id}-${field}`}
            type="text"
            value={values[field]}
            aria-invalid={errors[field] ? true : undefined}
            aria-describedby={errors[field] ? `${id}-${field}-error` : undefined}
            onChange={(event) => setValues({ ...values, [field]: event.target.value })}
            className={inputClass}
          />
          {errors[field] ? (
            <p id={`${id}-${field}-error`} className="text-meta text-destructive">
              {errors[field]}
            </p>
          ) : null}
        </div>
      ))}
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-definition`} className="text-label text-muted-foreground">
          Definition
        </label>
        <textarea
          id={`${id}-definition`}
          rows={4}
          value={values.definition}
          aria-invalid={errors.definition ? true : undefined}
          aria-describedby={errors.definition ? `${id}-definition-error` : undefined}
          onChange={(event) => setValues({ ...values, definition: event.target.value })}
          className="min-h-24 w-full resize-y rounded-md border border-input bg-transparent px-1.5 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive"
        />
        {errors.definition ? (
          <p id={`${id}-definition-error`} className="text-meta text-destructive">
            {errors.definition}
          </p>
        ) : null}
      </div>
      {message ? <p className="text-meta text-destructive">{message}</p> : null}
      <div className="flex gap-2">
        <button type="submit" aria-disabled={pending || undefined} className={buttonClass}>
          Create
        </button>
        <button type="button" onClick={() => onCancel(false)} className={buttonClass}>
          Cancel
        </button>
      </div>
    </form>
  );
}
