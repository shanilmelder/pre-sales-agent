"use client";

import { CircleAlertIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { ImpactBar } from "@/components/opportunities/impact-bar";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Textarea } from "@/components/ui/textarea";
import {
  originLabel,
  originPrefix,
  REASON_LABEL,
  REASON_MAX,
  SUPERSEDED_ORIGIN,
  type OriginGap,
} from "@/lib/estimates";
import { categoryLabel } from "@/lib/gaps";
import { codePointLength } from "@/lib/opportunities";
import { cn } from "@/lib/utils";

/** Shared by the Assumption and Risk inspectors and their rows (Story 8.5). */

/** A native select or input in an inspector form. */
export const formFieldClass =
  "h-8 rounded-md border border-border-strong bg-surface-alt px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-40 aria-[invalid=true]:border-destructive";

/** An uppercase inspector section label. */
export function PaneLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h4 className={`${cn("text-muted-foreground uppercase", className)} text-eyebrow`}>
      {children}
    </h4>
  );
}

/** The origin chip's text: "from Gap: {title}" (or "from Unknown: …"); a superseded origin has
 * its title struck through and a "superseded" label, never colour alone. */
export function OriginText({
  item,
}: {
  item: {
    origin: Pick<OriginGap, "title">;
    origin_superseded: boolean;
    origin_is_unknown?: boolean;
  };
}) {
  if (!item.origin_superseded) return <span className="text-meta">{originLabel(item)}</span>;
  return (
    <span className="text-meta">
      {originPrefix(item)}
      <s>{item.origin.title}</s>
      <span data-origin-superseded="">{` (${SUPERSEDED_ORIGIN})`}</span>
    </span>
  );
}

/** The origin card in an inspector: the Gap's title, impact, why it matters and status. */
export function OriginCard({
  item,
  onOpenGap,
}: {
  item: { origin: OriginGap; origin_superseded: boolean; origin_is_unknown?: boolean };
  onOpenGap?: () => void;
}) {
  const { origin } = item;
  const status =
    origin.status === "converted" ? "Converted" : origin.status === "open" ? "Open" : "Superseded";
  return (
    <div
      data-origin-card=""
      className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3"
    >
      <p className="text-meta text-muted-foreground">
        {`${item.origin_is_unknown ? "Unknown" : "Gap"} · ${categoryLabel(origin.category)}`}
      </p>
      {onOpenGap ? (
        <button
          type="button"
          data-gap-chip=""
          onClick={onOpenGap}
          className="w-fit rounded-sm text-left text-body-strong text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
        >
          {item.origin_superseded ? <s>{origin.title}</s> : origin.title}
        </button>
      ) : (
        <p className="text-body-strong">
          {item.origin_superseded ? <s>{origin.title}</s> : origin.title}
        </p>
      )}
      {item.origin_superseded ? (
        <p className="flex items-center gap-1 text-meta text-gap" data-origin-superseded="">
          <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
          {`The Gap was ${SUPERSEDED_ORIGIN} since this was made from it.`}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <ImpactBar impact={origin.impact} />
        <span className="text-meta text-muted-foreground">{`Status: ${status}`}</span>
      </div>
      <p className="whitespace-pre-wrap break-words text-body">{origin.why_it_matters}</p>
    </div>
  );
}

/** The required reason, with its code-point counter. */
export function ReasonField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const id = useId();
  const countId = useId();
  const length = codePointLength(value.trim());
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-label">
        {REASON_LABEL}
      </label>
      <Textarea
        id={id}
        value={value}
        required
        rows={2}
        maxLength={REASON_MAX * 2}
        disabled={disabled}
        aria-describedby={countId}
        onChange={(event) => onChange(event.target.value)}
      />
      <span
        id={countId}
        data-over={length > REASON_MAX || undefined}
        className={cn(
          "[font-variant-numeric:tabular-nums]",
          length > REASON_MAX ? "text-destructive" : "text-muted-foreground",
        )}
      >
        <span className="text-meta">
          {length > REASON_MAX
            ? `${length}/${REASON_MAX}: shorten the reason to save`
            : `${length}/${REASON_MAX}`}
        </span>
      </span>
    </div>
  );
}

/** Whether a reason may be saved: 1-300 code points, trimmed. */
export function reasonValid(reason: string): boolean {
  const length = codePointLength(reason.trim());
  return length > 0 && length <= REASON_MAX;
}

/** A failed save: the stale alert with Reload (412, or a replaced version), else a plain
 * alert with the sentence. */
export function FormNotice({
  notice,
  onReload,
}: {
  notice: { message: string; reload: boolean };
  onReload?: () => void;
}) {
  if (notice.reload && onReload) {
    return <InlineAlert lead={notice.message} onReload={onReload} />;
  }
  return (
    <div
      role="alert"
      data-slot="inline-alert"
      className="flex max-w-md items-start gap-2 rounded-lg border border-blocker bg-blocker-tint p-3"
    >
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-3 shrink-0 text-blocker" />
      <p className="text-meta text-foreground">{notice.message}</p>
    </div>
  );
}
