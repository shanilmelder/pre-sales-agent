"use client";

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
  fieldValue,
  hasTraceFilters,
  NO_EVENTS,
  NO_MATCHES,
  pageCount,
  relativeTime,
  subjectHref,
  subjectLabel,
  subjectLinkText,
  subjectText,
  traceHref,
  withTraceFilter,
  type TraceEvent,
  type TraceFilterKey,
  type TraceFilters,
  type TracePage,
} from "@/lib/trace";

const controlClass =
  "h-8 rounded-md border border-input bg-background px-2 text-body text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-primary";
const labelClass = "flex flex-col gap-1 text-meta text-muted-foreground";
const linkButtonClass =
  "inline-flex h-8 items-center rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

/** The trace events as dense 32px rows, newest first: the time (relative; absolute on
 * hover), the actor, the event in plain words and the subject as a link to its tab.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row in the inspector. The selected row is
 * `aria-selected`. */
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
    <div
      ref={container}
      role="grid"
      aria-label="Decision Trace"
      onKeyDown={onKeyDown}
      className="flex flex-col"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        const href = subjectHref(opportunityId, item.subject.type);
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={selected}
            className={`flex items-center gap-2 border-b border-border ${
              selected ? "bg-muted" : "hover:bg-muted/60"
            }`}
          >
            <div role="gridcell" className="min-w-0 flex-1">
              <button
                type="button"
                data-trace-row=""
                data-trace-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                // A keyboard-activated click has no pointer clicks (detail 0).
                onClick={(event) => onOpen?.(item, event.detail === 0)}
                className="flex min-h-row w-full items-center gap-3 rounded-sm px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <time
                  dateTime={item.occurred_at}
                  title={absoluteTime(item.occurred_at)}
                  suppressHydrationWarning
                  className="w-24 shrink-0 truncate text-meta text-muted-foreground text-numeric"
                >
                  {relativeTime(item.occurred_at, now)}
                </time>
                <span className="w-40 shrink-0 truncate text-meta text-muted-foreground">
                  {item.actor.name}
                </span>
                <span className="min-w-0 flex-1 truncate text-body">
                  {eventLabel(item.event_type)}
                </span>
              </button>
            </div>
            <div
              role="gridcell"
              className="w-48 shrink-0 truncate pr-1 text-right text-meta"
            >
              {href ? (
                <Link
                  href={href}
                  tabIndex={-1}
                  className="rounded-sm text-primary underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {subjectText(item.subject)}
                </Link>
              ) : (
                <span className="text-muted-foreground">
                  {subjectText(item.subject)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The selected event in the right pane, read-only: its label, the absolute time (UTC), the
 * actor (with an agent's version), the subject's type, id and version, then each payload
 * field as a label/value row in catalogue order. */
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
    ["When", absoluteTime(event.occurred_at)],
    ["Actor", actorText(event.actor)],
    ["Subject type", subjectLabel(event.subject.type)],
    ["Subject id", event.subject.id],
    ["Subject version", fieldValue(event.subject.version)],
  ];
  const payload = Object.entries(event.payload ?? {});
  // The row's subject link is outside the Tab order (the grid is one stop), so the
  // inspector carries a reachable one.
  const href = subjectHref(opportunityId, event.subject.type);
  const linkText = subjectLinkText(event.subject.type);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 p-gutter"
    >
      <div className="flex flex-col gap-1">
        <p className="font-mono text-meta text-muted-foreground">
          {event.event_type}
        </p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {eventLabel(event.event_type)}
        </h3>
      </div>
      {href && linkText ? (
        <Link href={href} className={`${linkButtonClass} self-start`}>
          {linkText}
        </Link>
      ) : null}
      <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-label text-muted-foreground">{label}</dt>
            <dd className="break-words text-body text-numeric">{value}</dd>
          </div>
        ))}
      </dl>
      {payload.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Details</h4>
          <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5">
            {payload.map(([name, value]) => (
              <div key={name} className="contents">
                <dt className="text-label text-muted-foreground">
                  {fieldLabel(name)}
                </dt>
                <dd className="break-words text-body text-numeric">
                  {fieldValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </section>
  );
}

/** The Subject, Actor and Event filters. Values come from the URL (`filters`) and every
 * change replaces the URL, on page 1, so a filtered view survives reload and sharing. The
 * choices are the values present on this Opportunity's trace; a value from a shared URL
 * that isn't among them is still shown so the control never lies about what is applied. */
export function TraceFilterBar({
  opportunityId,
  filters,
  options,
}: {
  opportunityId: string;
  filters: TraceFilters;
  options: TracePage["options"];
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

  const select = (
    key: TraceFilterKey,
    label: string,
    any: string,
    present: readonly string[],
    text: (value: string) => string,
  ) => (
    <label className={labelClass} htmlFor={`${id}-${key}`}>
      {label}
      <select
        id={`${id}-${key}`}
        className={controlClass}
        value={values[key] ?? ""}
        onChange={change(key)}
      >
        <option value="">{any}</option>
        {withCurrent(present, values[key]).map((value) => (
          <option key={value} value={value}>
            {text(value)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div
      role="group"
      aria-label="Filters"
      aria-busy={pending || undefined}
      className="flex flex-wrap items-end gap-3"
    >
      {select(
        "subject",
        "Subject",
        "Any subject",
        options.subject_types,
        subjectLabel,
      )}
      {select(
        "actor",
        "Actor",
        "Any actor",
        options.actor_types,
        actorTypeLabel,
      )}
      {select("event", "Event", "Any event", options.event_types, eventLabel)}
      {hasTraceFilters(values) ? (
        <Link
          href={traceHref(opportunityId, {})}
          onClick={clear}
          className={linkButtonClass}
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
            className={linkButtonClass}
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
            className={linkButtonClass}
            href={traceHref(opportunityId, filters, page.page + 1)}
          >
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** The Trace tab's content: the filters, the page of events in the main pane, pagination,
 * and the selected event's inspector in the right pane (opened if closed). Read-only for
 * everyone. */
export function TraceSection({
  opportunityId,
  page,
  filters,
  now,
}: {
  opportunityId: string;
  page: TracePage;
  filters: TraceFilters;
  now?: number;
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
      {page.total > 0 || filtered ? (
        <TraceFilterBar
          opportunityId={opportunityId}
          filters={filters}
          options={page.options}
        />
      ) : null}
      {page.items.length > 0 ? (
        <TraceList
          opportunityId={opportunityId}
          items={page.items}
          selectedId={selected?.id ?? null}
          onOpen={open}
          now={now}
        />
      ) : filtered ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-muted-foreground">{NO_MATCHES}</p>
          <Link href={traceHref(opportunityId, {})} className={linkButtonClass}>
            {CLEAR_FILTERS}
          </Link>
        </div>
      ) : page.total === 0 ? (
        <p className="text-muted-foreground">{NO_EVENTS}</p>
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
