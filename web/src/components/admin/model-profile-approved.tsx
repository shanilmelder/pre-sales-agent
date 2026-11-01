"use client";

import { useId, useState, useTransition, type FormEvent } from "react";

import {
  addApprovedModel,
  removeApprovedModel,
  type ApprovedResult,
} from "@/app/admin/model-profiles/actions";
import { BODY_ROW, CardTable, FOOTNOTE } from "@/components/admin/card-table";
import { useAnnounce } from "@/components/shell/live-region";
import { Card } from "@/components/ui/card";
import {
  NO_APPROVED_MODELS,
  PROVIDERS,
  type ApprovedModel,
  type Provider,
} from "@/lib/model-profiles";

const inputClass =
  "h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";
const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const GRID = "grid-cols-[120px_minmax(0,1fr)_100px]";
const COLUMNS = ["Provider", "Model ID", "Actions"] as const;

function sorted(models: readonly ApprovedModel[]): ApprovedModel[] {
  return [...models].sort(
    (a, b) => a.provider.localeCompare(b.provider) || a.model.localeCompare(b.model),
  );
}

/** Admin → Model profiles → Approved models: the models a profile may name. Removing one
 * leaves the profiles that already name it alone. */
export function ModelProfileApproved({
  initialModels,
}: {
  initialModels: readonly ApprovedModel[];
}) {
  const announce = useAnnounce();
  const [models, setModels] = useState<readonly ApprovedModel[]>(initialModels);
  const [provider, setProvider] = useState<Provider>("ollama");
  const [model, setModel] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const id = useId();

  function fail(text: string) {
    setMessage(text);
    announce(text);
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setMessage(null);
    if (!model.trim()) {
      fail("The model ID is required.");
      return;
    }
    startTransition(async () => {
      let result: ApprovedResult;
      try {
        result = await addApprovedModel({ provider, model: model.trim() });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok": {
          const added = result.model;
          setModels((current) => sorted([...current, added]));
          setModel("");
          announce(`Approved ${added.model}`);
          return;
        }
        case "conflict":
        case "invalid":
          fail(result.detail);
          return;
        case "forbidden":
          fail("You don't have access to change approved models.");
          return;
        default:
          fail("The model could not be added. Try again.");
      }
    });
  }

  function remove(entry: ApprovedModel) {
    if (pending) return;
    setMessage(null);
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof removeApprovedModel>>;
      try {
        result = await removeApprovedModel(entry.id);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        setModels((current) => current.filter((m) => m.id !== entry.id));
        announce(`Removed ${entry.model}`);
        return;
      }
      fail(
        result.kind === "forbidden"
          ? "You don't have access to change approved models."
          : "The model could not be removed. Try again.",
      );
    });
  }

  return (
    <>
      <Card className="overflow-hidden">
        <div className="px-5 py-[18px]">
          <h2 className="text-section">Approved models</h2>
          <p className="text-meta text-text-secondary">
            A model profile can only name a model on this list
          </p>
        </div>
        <form onSubmit={add} noValidate className="flex flex-wrap items-end gap-2 px-5 pb-4">
          <div className="flex w-32 flex-col gap-1">
            <label htmlFor={`${id}-provider`} className="text-label text-muted-foreground">
              Provider
            </label>
            <select
              id={`${id}-provider`}
              value={provider}
              onChange={(event) => setProvider(event.target.value as Provider)}
              className={inputClass}
            >
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="flex min-w-48 flex-1 flex-col gap-1">
            <label htmlFor={`${id}-model`} className="text-label text-muted-foreground">
              Model ID
            </label>
            <input
              id={`${id}-model`}
              type="text"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className={`${inputClass} font-mono`}
            />
          </div>
          <button type="submit" aria-disabled={pending || undefined} className={buttonClass}>
            Approve model
          </button>
        </form>
        {message ? <p className="px-5 pb-4 text-meta text-destructive">{message}</p> : null}
        {models.length === 0 ? (
          <p className="border-t border-border px-5 py-4 text-text-secondary">
            {NO_APPROVED_MODELS}
          </p>
        ) : (
          <CardTable label="Approved models" grid={GRID} columns={COLUMNS}>
            {models.map((entry) => (
              <div key={entry.id} role="row" className={`${BODY_ROW} ${GRID} py-2.5`}>
                <span role="cell">{entry.provider}</span>
                <span role="cell" className="min-w-0 truncate font-mono text-body">
                  {entry.model}
                </span>
                <span role="cell">
                  <button
                    type="button"
                    aria-disabled={pending || undefined}
                    aria-label={`Remove ${entry.model}`}
                    onClick={() => remove(entry)}
                    className={buttonClass}
                  >
                    Remove
                  </button>
                </span>
              </div>
            ))}
          </CardTable>
        )}
      </Card>
      <p className={FOOTNOTE}>Removing a model doesn&apos;t change profiles that already use it.</p>
    </>
  );
}
