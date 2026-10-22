"use client";

import { ArrowDownIcon, ArrowUpIcon, TrashIcon } from "lucide-react";
import { useId, useState } from "react";

import type { CatalogueOption } from "@/components/knowledge/checklists-tab";
import { MandatoryLabel } from "@/components/knowledge/mandatory-label";
import { RetiredLabel } from "@/components/knowledge/sources-table";
import {
  IMPACTS,
  ITEM_KINDS,
  ITEM_TEXT_MAX,
  impactLabel,
  itemInput,
  kindLabel,
  type ChecklistItem,
  type DraftItemInput,
} from "@/lib/checklists";

const fieldClass =
  "w-full rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";
const iconButtonClass =
  "inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-border outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";

/** One item of a draft in the item editor. Kind, affected area, impact and Mandatory save
 * when changed; the text and "why it matters" save on blur (only when changed). Mandatory
 * shows the Mandatory label, never colour alone. A retired affected area keeps showing,
 * labelled Retired, but only active entries can be chosen. */
export function ChecklistItemEditor({
  item,
  index,
  count,
  catalogue,
  locked,
  onCommit,
  onMove,
  onRemove,
}: {
  item: ChecklistItem;
  index: number;
  count: number;
  /** The active Integration Types and Work Packages. */
  catalogue: readonly CatalogueOption[];
  locked: boolean;
  /** Called with the fields changed; the inspector applies them to the item by id. */
  onCommit: (change: Partial<DraftItemInput>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const stored = itemInput(item);
  // What is typed; it follows the stored text whenever that changes (a save or a reload).
  const [text, setText] = useState(item.text);
  const [why, setWhy] = useState(item.why_it_matters);
  const [synced, setSynced] = useState({ text: item.text, why: item.why_it_matters });
  if (synced.text !== item.text || synced.why !== item.why_it_matters) {
    setSynced({ text: item.text, why: item.why_it_matters });
    if (synced.text !== item.text) setText(item.text);
    if (synced.why !== item.why_it_matters) setWhy(item.why_it_matters);
  }
  const number = index + 1;

  function commit(change: Partial<DraftItemInput>) {
    if (locked) return;
    onCommit(change);
  }

  function blurText(field: "text" | "why_it_matters", value: string) {
    if (value !== stored[field]) commit({ [field]: value });
  }

  const types = catalogue.filter((c) => c.kind === "integration_type");
  const packages = catalogue.filter((c) => c.kind === "work_package");
  const area = item.affected_area;
  const areaRetired = area !== null && (area.retired || !catalogue.some((c) => c.id === area.id));

  return (
    <li
      data-item-id={item.id}
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-2 rounded-md border border-border p-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h5 id={`${id}-title`} className="flex items-center gap-2 text-label">
          Item {number}: {kindLabel(item.kind)}
          {item.mandatory ? <MandatoryLabel /> : null}
        </h5>
        <span className="flex gap-1">
          <button
            type="button"
            aria-label={`Move item ${number} up`}
            aria-disabled={locked || index === 0 || undefined}
            onClick={() => !locked && index > 0 && onMove(-1)}
            className={iconButtonClass}
          >
            <ArrowUpIcon aria-hidden="true" className="size-3.5" />
          </button>
          <button
            type="button"
            aria-label={`Move item ${number} down`}
            aria-disabled={locked || index === count - 1 || undefined}
            onClick={() => !locked && index < count - 1 && onMove(1)}
            className={iconButtonClass}
          >
            <ArrowDownIcon aria-hidden="true" className="size-3.5" />
          </button>
          <button
            type="button"
            aria-label={`Remove item ${number}`}
            aria-disabled={locked || undefined}
            onClick={() => !locked && onRemove()}
            className={iconButtonClass}
          >
            <TrashIcon aria-hidden="true" className="size-3.5" />
          </button>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 text-meta text-muted-foreground">
          Kind
          <select
            value={item.kind}
            disabled={locked}
            onChange={(event) => commit({ kind: event.target.value as DraftItemInput["kind"] })}
            className={`${fieldClass} h-7`}
          >
            {ITEM_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-meta text-muted-foreground">
          Default impact
          <select
            value={item.impact}
            disabled={locked}
            onChange={(event) =>
              commit({ impact: event.target.value as DraftItemInput["impact"] })
            }
            className={`${fieldClass} h-7`}
          >
            {IMPACTS.map((i) => (
              <option key={i.value} value={i.value}>
                {i.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-meta text-muted-foreground">
        {item.kind === "risk" ? "Risk" : "Question"}
        <textarea
          rows={2}
          value={text}
          maxLength={ITEM_TEXT_MAX * 2}
          readOnly={locked}
          onChange={(event) => setText(event.target.value)}
          onBlur={() => blurText("text", text)}
          className={`${fieldClass} py-1`}
        />
      </label>
      <label className="flex flex-col gap-1 text-meta text-muted-foreground">
        Why it matters
        <textarea
          rows={2}
          value={why}
          maxLength={ITEM_TEXT_MAX * 2}
          readOnly={locked}
          onChange={(event) => setWhy(event.target.value)}
          onBlur={() => blurText("why_it_matters", why)}
          className={`${fieldClass} py-1`}
        />
      </label>

      <label className="flex flex-col gap-1 text-meta text-muted-foreground">
        Affected estimate area
        <select
          value={area?.id ?? ""}
          disabled={locked}
          onChange={(event) => commit({ affected_entry_id: event.target.value || null })}
          className={`${fieldClass} h-7`}
        >
          <option value="">None</option>
          {areaRetired ? <option value={area.id}>{area.name} (retired)</option> : null}
          <optgroup label="Integration Types">
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </optgroup>
          <optgroup label="Work Packages">
            {packages.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </optgroup>
        </select>
      </label>
      {areaRetired ? (
        <p className="flex items-center gap-2 text-meta">
          {area.name} <RetiredLabel />
        </p>
      ) : null}

      <label className="flex items-center gap-2 text-body">
        <input
          type="checkbox"
          checked={item.mandatory}
          disabled={locked}
          onChange={(event) => commit({ mandatory: event.target.checked })}
        />
        Mandatory: always raises a Gap when unanswered
      </label>
    </li>
  );
}

/** One published item, read-only. */
export function ChecklistItemView({ item, index }: { item: ChecklistItem; index: number }) {
  return (
    <li data-item-id={item.id} className="flex flex-col gap-1 border-b border-border py-1.5">
      <p className="flex flex-wrap items-center gap-2 text-label">
        <span>
          {index + 1}. {kindLabel(item.kind)}
        </span>
        {item.mandatory ? <MandatoryLabel /> : null}
        <span className="text-meta text-muted-foreground">
          Impact {impactLabel(item.impact)}
        </span>
      </p>
      <p className="whitespace-pre-wrap text-body">{item.text}</p>
      <p className="whitespace-pre-wrap text-meta text-muted-foreground">{item.why_it_matters}</p>
      {item.affected_area ? (
        <p className="flex items-center gap-2 text-meta">
          Affects {item.affected_area.name}
          {item.affected_area.retired ? <RetiredLabel /> : null}
        </p>
      ) : null}
    </li>
  );
}
