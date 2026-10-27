"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
  type ChangeEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import { ActorTile } from "@/components/opportunities/actor-tile";
import { clearFiltersClass, FilterChip } from "@/components/opportunities/filter-bar";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  absoluteTime,
  actorText,
  actorTypeLabel,
  CLEAR_FILTERS,
  eventLabel,
  fieldLabel,
  hasTraceFilters,
  lineEditChange,
  NO_EVENTS_BODY,
  NO_EVENTS_TITLE,
  NO_MATCHES,
  OPEN_OVERVIEW,
  pageCount,
  payloadValue,
  relativeTime,
  removeSubjectLabel,
  subjectChipLabel,
  subjectHref,
  subjectLabel,
  subjectLinkText,
  subjectText,
  TRACE_APPEND_ONLY,
  TRACE_REASONING_NOTE,
  traceHref,
  withTraceFilter,
  type TraceEvent,
  type TraceFilterKey,
  type TraceFilters,
  type TracePage,
} from "@/lib/trace";
import { tabHref } from "@/lib/workspace";

const controlClass =
  "h-8 rounded-md border border-input bg-background px-2 text-body text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-primary";
const labelClass = "flex flex-col gap-1 text-meta text-muted-foreground";
const outlineLink = `${buttonVariants({ variant: "outline", size: "sm" })} text-control`;
const eyebrowClass = "text-eyebrow text-text-secondary uppercase";

/** The trace events in one card, newest first. Each row is a 4-column grid: the time
 * (relative; absolute on hover), the actor (initials tile and name), the event in plain words
 * and the subject as a link to its tab. Below `md` the columns stack: time and actor above the
 * event, the subject on its own line.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row in the inspector. The selected row is
 * `aria-selected` and tinted. */
export function TraceList({
  opportunityId,
  items,
  selectedId = null,
  onOpen,
  now,
}: {
  opportunityId: string;
  items: readonly TraceEvent[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: TraceEvent, viaKeyboard: boolean) => void;
  /** The time relative times count from (default: now). */
  now?: number;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find(
      (id) => id !== null && items.some((i) => i.id === id),
    ) ?? items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down =
      event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up =
      event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>(
        "button[data-trace-row]",
      ) ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    const next =
      index === -1
        ? 0
        : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <Card
      ref={container}
      role="grid"
      aria-label="Decision Trace"
      onKeyDown={onKeyDown}
      className="overflow-hidden"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        const href = subjectHref(opportunityId, item.subject.type);
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={selected}
            data-actor-type={item.actor.type}
            className={`grid grid-cols-1 gap-x-4 border-b px-5 border-border text-[13px] leading-5 last:border-b-0 md:grid-cols-[130px_190px_minmax(0,1fr)_190px] md:items-center ${
              selected ? "bg-primary-tint" : "hover:bg-muted/60"
            }`}
          >
            <div role="gridcell" className="min-w-0 md:col-span-3 md:grid md:grid-cols-subgrid">
              <button
                type="button"
                data-trace-row=""
                data-trace-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                // A keyboard-activated click has no pointer clicks (detail 0).
                onClick={(event) => onOpen?.(item, event.detail === 0)}
                className="flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-1 pt-[calc((var(--row-height)_-_32px)/2_+_2px)] pb-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset md:col-span-3 md:grid md:grid-cols-subgrid md:gap-x-4 md:gap-y-0 md:pb-[calc((var(--row-height)_-_32px)/2_+_2px)]"
              >
                <time
                  dateTime={item.occurred_at}
                  title={absoluteTime(item.occurred_at)}
                  suppressHydrationWarning
                  className="truncate text-text-secondary text-numeric"
                >
                  {relativeTime(item.occurred_at, now)}
                </time>
                <span className="flex min-w-0 items-center gap-2">
                  <ActorTile actor={item.actor} size={22} />
                  <span className="truncate">{item.actor.name}</span>
                </span>
                <span className="min-w-0 basis-full truncate font-medium md:basis-auto">
                  {eventLabel(item.event_type)}
                </span>
              </button>
            </div>
            <div
              role="gridcell"
              className="min-w-0 truncate pb-[calc((var(--row-height)_-_32px)/2_+_2px)] text-label md:pb-0 md:text-right"
            >
              {href ? (
                <Link
                  href={href}
                  tabIndex={-1}
                  className="rounded-sm text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {subjectText(item.subject)}
                </Link>
              ) : (
                <span className="text-text-secondary">{subjectText(item.subject)}</span>
              )}
            </div>
          </div>
        );
      })}
    </Card>
  );
}

/** The selected event in the right pane, read-only, in bordered sections: a header (the
 * absolute time, the event as the focusable heading, the actor with its type, and a link to
 * the subject's tab), the Payload (event, actor, subject and each payload field in catalogue
 * order), the before/after Change of an Estimate line edit, and an append-only note. */
export function TraceInspector({
  opportunityId,
  event,
  focusRequest = 0,
}: {
  opportunityId: string;
  event: TraceEvent;
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  const rows: [string, string][] = [
    ["Event", event.event_type],
    ["Actor", actorText(event.actor)],
    ["Subject", subjectText(event.subject)],
    ["Subject id", event.subject.id],
    ...Object.entries(event.payload ?? {}).map(
      ([name, value]): [string, string] => [fieldLabel(name), payloadValue(name, value)],
    ),
  ];
  const change = lineEditChange(event);
  // The row's subject link is outside the Tab order (the grid is one stop), so the
  // inspector carries a reachable one.
  const href = subjectHref(opportunityId, event.subject.type);
  const linkText = subjectLinkText(event.subject.type);

  return (
    <section aria-labelledby={headingId} className="flex flex-col">
      <div className="flex flex-col items-start border-b border-border p-5">
        <p className="mb-1.5 text-label text-text-secondary text-numeric">
          Trace event · {absoluteTime(event.occurred_at)}
        </p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section [overflow-wrap:anywhere] outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {eventLabel(event.event_type)}
        </h3>
        <p className="mt-2 flex min-w-0 items-center gap-2 text-[13px] leading-5">
          <ActorTile actor={event.actor} size={22} />
          <span className="[overflow-wrap:anywhere]">{actorText(event.actor)}</span>
          <span className="shrink-0 text-text-secondary">
            · {actorTypeLabel(event.actor.type)}
          </span>
        </p>
        {href && linkText ? (
          <Link href={href} className={`${outlineLink} mt-3`}>
            {linkText}
          </Link>
        ) : null}
      </div>

      <div className="border-b border-border p-5">
        <h4 className={`${eyebrowClass} mb-2`}>Payload</h4>
        <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px] leading-5">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-text-secondary">{label}</dt>
              <dd className="[overflow-wrap:anywhere] text-numeric">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {change ? (
        <div className="border-b border-border p-5">
          <h4 className={`${eyebrowClass} mb-2`}>Change</h4>
          <ul className="flex flex-col gap-1 text-[13px] leading-5">
            <li className="flex gap-2.5 rounded-lg bg-blocker-tint px-2.5 py-1.5">
              <b aria-hidden="true" className="w-3 shrink-0 text-blocker">
                −
              </b>
              <span className="sr-only">Before: </span>
              <span className="min-w-0 text-numeric">{change.before}</span>
            </li>
            <li className="flex gap-2.5 rounded-lg bg-resolved-tint px-2.5 py-1.5">
              <b aria-hidden="true" className="w-3 shrink-0 text-resolved">
                +
              </b>
              <span className="sr-only">After: </span>
              <span className="min-w-0 text-numeric">{change.after}</span>
            </li>
          </ul>
        </div>
      ) : null}

      <p className="p-5 text-meta text-text-secondary">{TRACE_REASONING_NOTE}</p>
    </section>
  );
}

/** The Subject, Actor and Event filters as dashed chips, each opening its select in a
 * popover; an applied one reads "Label: value" in the primary tint, and Clear filters follows.
 * Values come from the URL (`filters`) and every change replaces the URL, on page 1, so a
 * filtered view survives reload and sharing. The choices are the values present on this
 * Opportunity's trace; a value from a shared URL that isn't among them is still shown so the
 * control never lies about what is applied. Story 9.9: a `subject_id` filter (**Open in
 * Trace** from a line's lineage) is a visible, removable "Line {title}" chip. */
export function TraceFilterBar({
  opportunityId,
  filters,
  options,
  subjectTitle = null,
}: {
  opportunityId: string;
  filters: TraceFilters;
  options: TracePage["options"];
  /** The `subject_id` filter's line title, when known. */
  subjectTitle?: string | null;
}) {
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();
  const urlKey = traceHref(opportunityId, filters);
  const [shownKey, setShownKey] = useState(urlKey);
  const [values, setValues] = useState<TraceFilters>(filters);
  if (shownKey !== urlKey) {
    setShownKey(urlKey);
    setValues(filters);
  }

  function navigate(next: TraceFilters) {
    setValues(next);
    startTransition(() =>
      router.replace(traceHref(opportunityId, next), { scroll: false }),
    );
  }

  function change(key: TraceFilterKey) {
    return (event: ChangeEvent<HTMLSelectElement>) =>
      navigate(withTraceFilter(values, key, event.target.value));
  }

  function clear(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    navigate({});
  }

  const withCurrent = (
    present: readonly string[],
    current: string | undefined,
  ) =>
    current && !present.includes(current)
      ? [...present, current]
      : [...present];

  const chip = (
    key: TraceFilterKey,
    label: string,
    any: string,
    present: readonly string[],
    text: (value: string) => string,
  ) => {
    const current = values[key];
    return (
      <FilterChip label={label} closeOnChange value={current ? text(current) : undefined}>
        <label className={labelClass} htmlFor={`${id}-${key}`}>
          {label}
          <select
            id={`${id}-${key}`}
            className={controlClass}
            value={current ?? ""}
            onChange={change(key)}
          >
            <option value="">{any}</option>
            {withCurrent(present, current).map((value) => (
              <option key={value} value={value}>
                {text(value)}
              </option>
            ))}
          </select>
        </label>
      </FilterChip>
    );
  };

  return (
    <div
      role="group"
      aria-label="Filters"
      aria-busy={pending || undefined}
      className="flex flex-wrap items-center gap-2"
    >
      {values.subject_id ? (
        <span
          data-subject-id-chip=""
          className="inline-flex items-center gap-1 rounded-md border border-primary-tint bg-primary-tint py-[3px] pr-1 pl-2.5 text-[13px] leading-[1.4] text-primary-text"
        >
          <span className="max-w-60 truncate">{subjectChipLabel(subjectTitle)}</span>
          <button
            type="button"
            aria-label={removeSubjectLabel(subjectTitle)}
            onClick={() => navigate(withTraceFilter(values, "subject_id", ""))}
            className="inline-flex size-5 items-center justify-center rounded-sm outline-none hover:bg-surface/60 focus-visible:ring-2 focus-visible:ring-primary"
          >
            <XIcon aria-hidden="true" className="size-3" />
          </button>
        </span>
      ) : null}
      {chip("subject", "Subject", "Any subject", options.subject_types, subjectLabel)}
      {chip("actor", "Actor", "Any actor", options.actor_types, actorTypeLabel)}
      {chip("event", "Event", "Any event", options.event_types, eventLabel)}
      {hasTraceFilters(values) ? (
        <Link
          href={traceHref(opportunityId, {})}
          onClick={clear}
          className={clearFiltersClass}
        >
          {CLEAR_FILTERS}
        </Link>
      ) : null}
    </div>
  );
}

/** Previous/Next and "Page n of m". No infinite scroll. */
export function TracePagination({
  opportunityId,
  filters,
  page,
}: {
  opportunityId: string;
  filters: TraceFilters;
  page: Pick<TracePage, "page" | "page_size" | "total">;
}) {
  const pages = pageCount(page);
  if (page.total === 0) return null;
  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-2"
    >
      <p className="text-meta text-muted-foreground text-numeric">
        Page {page.page} of {pages}
      </p>
      <div className="flex gap-2">
        {page.page > 1 ? (
          <Link
            className={outlineLink}
            href={traceHref(
              opportunityId,
              filters,
              Math.min(page.page - 1, pages),
            )}
          >
            Previous
          </Link>
        ) : null}
        {page.page < pages ? (
          <Link
            className={outlineLink}
            href={traceHref(opportunityId, filters, page.page + 1)}
          >
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** The Trace tab's content: the title row with the filter chips, the card of events with its
 * append-only footnote, pagination, and the selected event's inspector in the right pane
 * (opened if closed). Read-only for everyone. */
export function TraceSection({
  opportunityId,
  page,
  filters,
  now,
  subjectTitle = null,
}: {
  opportunityId: string;
  page: TracePage;
  filters: TraceFilters;
  now?: number;
  /** Story 9.9: the `subject_id` filter's line title, when known. */
  subjectTitle?: string | null;
}) {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  const selected =
    selectedId === null
      ? null
      : (page.items.find((item) => item.id === selectedId) ?? null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) setFocusRequest(0);
  }

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (
      id &&
      (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)
    ) {
      document.querySelector<HTMLElement>(`[data-trace-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: TraceEvent, viaKeyboard: boolean) {
    setSelectedId(item.id);
    returnFocusTo.current = viaKeyboard ? item.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  const filtered = hasTraceFilters(filters);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex-1 text-section">Trace</h2>
        {page.total > 0 || filtered ? (
          <TraceFilterBar
            opportunityId={opportunityId}
            filters={filters}
            options={page.options}
            subjectTitle={subjectTitle}
          />
        ) : null}
      </div>
      {page.items.length > 0 ? (
        <>
          <TraceList
            opportunityId={opportunityId}
            items={page.items}
            selectedId={selected?.id ?? null}
            onOpen={open}
            now={now}
          />
          <p className="text-meta text-text-secondary">{TRACE_APPEND_ONLY}</p>
        </>
      ) : filtered ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-muted-foreground">{NO_MATCHES}</p>
          <Link href={traceHref(opportunityId, {})} className={outlineLink}>
            {CLEAR_FILTERS}
          </Link>
        </div>
      ) : page.total === 0 ? (
        <EmptyTabCard
          title={NO_EVENTS_TITLE}
          body={NO_EVENTS_BODY}
          actionLabel={OPEN_OVERVIEW}
          href={tabHref(opportunityId, "overview")}
        />
      ) : null}
      <TracePagination
        opportunityId={opportunityId}
        filters={filters}
        page={page}
      />
      {selected ? (
        <RightPaneContent>
          <TraceInspector
            opportunityId={opportunityId}
            key={selected.id}
            event={selected}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
