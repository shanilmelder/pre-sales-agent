"use client";

import { ChevronDownIcon, DiffIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { VersionStatePill } from "@/components/opportunities/version-switcher";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useShell } from "@/components/shell/shell-context";
import { Skeleton } from "@/components/ui/skeleton";
import {
  COMPARE_FAILED,
  comparedWith,
  deltaText,
  diffToggleLabel,
  hours,
  LOADING_COMPARISON,
  NO_ITEM_CHANGES,
  NO_WHY_EVENTS,
  WHY_IT_CHANGED,
  type ItemDiff,
  type VersionComparison,
  type VersionListItem,
} from "@/lib/estimates";
import { absoluteTime, subjectHref, subjectText } from "@/lib/trace";
import { useSkeletonDone } from "@/lib/use-skeleton-done";
import { cn } from "@/lib/utils";

const OPTION_CLASS =
  "flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-label outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

/** Story 9.9: the Estimate toolbar's **Diff vs v{n}** toggle (the mockup's, before Export):
 * `aria-pressed`, a 14px diff icon, 13px/500 text, 6×12 padding, radius 8; pressed it is the
 * primary tint with primary text and a primary border, else the surface with a strong
 * border. A chevron beside it opens a menu of every other version (the Baseline first, with
 * its anchor pill) to compare with. With single-key shortcuts on, `d` toggles it (not while
 * typing, in a dialog or in a menu). */
export function DiffToggle({
  on,
  against,
  targets,
  onToggle,
  onChoose,
}: {
  on: boolean;
  /** The version compared with (the label's number). */
  against: number;
  /** The versions it may compare with, the Baseline first. */
  targets: readonly VersionListItem[];
  onToggle: () => void;
  onChoose: (version: number) => void;
}) {
  const { singleKeyShortcuts, dialog } = useShell();
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef(onToggle);
  useEffect(() => {
    toggle.current = onToggle;
  }, [onToggle]);

  // `d` toggles the diff (single-key shortcuts only; the button is always there).
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "d" || event.isComposing || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!singleKeyShortcuts || dialog || isEditableTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="menu"],[role="dialog"]'))
        return;
      event.preventDefault();
      toggle.current();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [singleKeyShortcuts, dialog]);

  useEffect(() => {
    if (!open) return;
    const items = menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]');
    const checked = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]');
    (checked ?? items?.[0])?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    const items = [
      ...(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? []),
    ];
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      trigger.current?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = at === -1 ? 0 : at + step;
      items[(next + items.length) % items.length]?.focus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  function choose(version: number) {
    setOpen(false);
    trigger.current?.focus();
    onChoose(version);
  }

  return (
    <div ref={root} className="relative flex items-center" data-diff-toggle="">
      <button
        type="button"
        aria-pressed={on}
        aria-keyshortcuts={singleKeyShortcuts ? "d" : undefined}
        onClick={onToggle}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-l-[8px] border px-3 py-1.5 text-[13px] leading-[1.4] font-medium outline-none focus-visible:ring-2 focus-visible:ring-primary",
          on
            ? "border-primary bg-primary-tint text-primary-text"
            : "border-border-strong bg-surface text-foreground hover:bg-muted",
        )}
      >
        <DiffIcon aria-hidden="true" className="size-3.5" />
        {diffToggleLabel(against)}
      </button>
      <button
        ref={trigger}
        type="button"
        aria-label="Compare with another version"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className={cn(
          "-ml-px inline-flex items-center self-stretch rounded-r-[8px] border px-1.5 outline-none focus-visible:ring-2 focus-visible:ring-primary",
          on
            ? "border-primary bg-primary-tint text-primary-text"
            : "border-border-strong bg-surface text-foreground hover:bg-muted",
        )}
      >
        <ChevronDownIcon aria-hidden="true" className="size-3.5" />
      </button>
      {open ? (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label="Compare with"
          onKeyDown={onMenuKey}
          className="absolute top-9 right-0 z-20 flex min-w-44 flex-col gap-0.5 rounded-md border border-border bg-popover p-1 shadow-md"
        >
          {targets.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitemradio"
              aria-checked={item.version === against}
              tabIndex={-1}
              data-diff-target={item.version}
              onClick={() => choose(item.version)}
              className={OPTION_CLASS}
            >
              <span className="text-body-strong">{`v${item.version}`}</span>
              <VersionStatePill item={item} />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Marker({ sign, label, children }: { sign: "−" | "+"; label: string; children: string }) {
  return (
    <p className="flex gap-2 rounded-sm bg-diff-tint px-1.5 py-0.5" data-diff-marker={sign}>
      <span aria-hidden="true" className="shrink-0 text-muted-foreground">
        {sign}
      </span>
      <span className="sr-only">{`${label}: `}</span>
      <span className="min-w-0 text-meta break-words">{children}</span>
    </p>
  );
}

function ItemDiffs({ title, items }: { title: string; items: readonly ItemDiff[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5" data-item-diffs={title}>
      <h5 className="text-eyebrow text-muted-foreground uppercase">{title}</h5>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={`${item.change}-${item.id}`} className="flex flex-col gap-1" data-item-change={item.change}>
            <p className="text-label capitalize text-muted-foreground">{item.change}</p>
            {item.before !== null ? (
              <Marker sign="−" label="Before">
                {item.before}
              </Marker>
            ) : null}
            {item.after !== null ? (
              <Marker sign="+" label="After">
                {item.after}
              </Marker>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Story 9.9: the right pane while the diff is on: "Compared with v{n}" with the total delta,
 * the Assumptions and Risks added, removed or changed (`−`/`+` rows on the diff tint, as the
 * agent config diff), and **Why it changed**: the trace events between the two versions,
 * oldest first (date, event, who, reason and a link to the subject's tab). */
export function ComparePane({
  opportunityId,
  against,
  comparison,
}: {
  opportunityId: string;
  against: number;
  /** null while loading; `failed` when it could not be read. */
  comparison: VersionComparison | null | "failed";
}) {
  const headingId = useId();
  const skeletonDone = useSkeletonDone();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-5 p-gutter" data-compare-pane="">
      <h3 id={headingId} className="text-section">
        {comparedWith(against)}
      </h3>
      {comparison === "failed" ? (
        <p className="text-meta text-muted-foreground">{COMPARE_FAILED}</p>
      ) : comparison === null || !skeletonDone ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <p className="sr-only">{LOADING_COMPARISON}</p>
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : (
        <>
          <p className="text-meta text-muted-foreground text-numeric">
            {`Total ${hours(comparison.total_before)} h → ${hours(comparison.total_after)} h (${deltaText(comparison.total_delta)})`}
          </p>
          {comparison.assumptions.length === 0 && comparison.risks.length === 0 ? (
            <p className="text-meta text-muted-foreground">{NO_ITEM_CHANGES}</p>
          ) : (
            <>
              <ItemDiffs title="Assumptions" items={comparison.assumptions} />
              <ItemDiffs title="Risks" items={comparison.risks} />
            </>
          )}
          <div className="flex flex-col gap-2" data-why="">
            <h4 className="text-eyebrow text-muted-foreground uppercase">{WHY_IT_CHANGED}</h4>
            {comparison.why.length === 0 ? (
              <p className="text-meta text-muted-foreground">{NO_WHY_EVENTS}</p>
            ) : (
              <ol className="flex flex-col gap-2.5">
                {comparison.why.map((event) => {
                  const href = subjectHref(opportunityId, event.subject.type);
                  return (
                    <li key={event.id} className="flex flex-col gap-0.5" data-why-event={event.event_type}>
                      <p className="flex flex-wrap items-baseline gap-x-2">
                        <time dateTime={event.occurred_at} className="text-meta text-muted-foreground text-numeric">
                          {absoluteTime(event.occurred_at)}
                        </time>
                        <span className="text-body-strong">{event.label}</span>
                      </p>
                      <p className="text-meta text-muted-foreground">{event.actor.name}</p>
                      {event.reason ? <p className="text-body break-words">{event.reason}</p> : null}
                      {href ? (
                        <Link
                          href={href}
                          className="w-fit rounded-sm text-label text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          {subjectText(event.subject)}
                        </Link>
                      ) : (
                        <span className="text-label text-muted-foreground">{subjectText(event.subject)}</span>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </>
      )}
    </section>
  );
}
