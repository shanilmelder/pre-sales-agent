"use client";

import { cn } from "cn";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { getInbox, markAllInboxRead, markInboxItemRead } from "@/app/inbox/actions";
import { ReviewPanelLoader } from "@/components/opportunities/review-panel";
import { useAnnounce } from "@/components/shell/live-region";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { useShell } from "@/components/shell/shell-context";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Pill } from "@/components/ui/pill";
import { Skeleton } from "@/components/ui/skeleton";
import {
  EMPTY_BODY,
  EMPTY_TITLE,
  INBOX_TITLE,
  LIST_LABEL,
  MARK_ALL_READ,
  NO_SELECTION,
  NOT_REACHABLE,
  OPEN,
  REVIEW_SUBJECT,
  closedStatus,
  groupItems,
  isGreyedReviewItem,
  isReviewKind,
  itemBody,
  itemMeta,
  kindLabel,
  type InboxItem,
  type InboxPage,
} from "@/lib/inbox";
import {
  adjustInboxUnread,
  refreshInboxUnread,
  setInboxUnread,
  useInboxRefresh,
} from "@/lib/use-inbox-count";
import { useSkeletonDone } from "@/lib/use-skeleton-done";

const SKELETON_ROWS = 4;
const linkClass =
  "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

/** `/inbox?page=n`. */
export function inboxHref(page: number): string {
  return page > 1 ? `/inbox?page=${page}` : "/inbox";
}

function Pagination({ page }: { page: InboxPage }) {
  const first = (page.page - 1) * page.page_size + 1;
  const last = first + page.items.length - 1;
  const hasPrevious = page.page > 1;
  const hasNext = last < page.total;
  if (!hasPrevious && !hasNext) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2">
      <p className="text-meta text-muted-foreground text-numeric">
        {page.items.length > 0 ? `${first}–${last} of ${page.total}` : null}
      </p>
      <div className="flex gap-2">
        {hasPrevious ? (
          <Link className={linkClass} href={inboxHref(page.page - 1)}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={inboxHref(page.page + 1)}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

function StatusPill({ item }: { item: InboxItem }) {
  const status = closedStatus(item);
  if (!status) return null;
  const Icon = status.icon;
  return (
    <Pill tone={status.tone} icon={<Icon />} data-testid="inbox-status">
      {status.label}
    </Pill>
  );
}

function Row({
  item,
  selected,
  tabStop,
  onSelect,
  onFocus,
}: {
  item: InboxItem;
  selected: boolean;
  tabStop: boolean;
  onSelect: (item: InboxItem) => void;
  onFocus: (id: string) => void;
}) {
  const review = isReviewKind(item.kind);
  const kind = kindLabel(item.kind);
  return (
    <li className="border-t border-border first:border-t-0">
      <button
        type="button"
        data-inbox-row={item.id}
        tabIndex={tabStop ? 0 : -1}
        aria-current={selected ? "true" : undefined}
        onClick={() => onSelect(item)}
        onFocus={() => onFocus(item.id)}
        className={cn(
          "flex w-full items-start gap-3 px-4 py-3.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset",
          selected ? "bg-primary-tint" : "hover:bg-muted/60",
        )}
      >
        <span
          aria-hidden="true"
          data-testid="unread-dot"
          className={cn(
            "mt-[7px] size-2 shrink-0 rounded-full",
            item.read ? "bg-transparent" : review ? "bg-primary" : "bg-border-strong",
          )}
        />
        <span className="min-w-0 flex-1">
          <span className={cn("block", item.read ? "font-medium" : "font-semibold")}>
            {item.read ? null : <span className="sr-only">Unread: </span>}
            {item.summary}
          </span>
          <span className="block text-meta text-text-secondary">{itemMeta(item)}</span>
        </span>
        <span
          className={cn(
            "text-label whitespace-nowrap",
            review ? "text-primary-text" : "text-text-secondary",
          )}
        >
          {kind}
        </span>
      </button>
    </li>
  );
}

/** The item's own header, sentence, status and **Open** (9.2's detail body). */
function DetailBody({ item }: { item: InboxItem }) {
  return (
    <>
      <div>
        <p className="mb-1 text-meta text-text-secondary">
          {kindLabel(item.kind)} · {itemMeta(item)}
        </p>
        <h2 className="text-[16px] leading-6 font-semibold">{item.summary}</h2>
      </div>
      <p>{itemBody(item)}</p>
      <StatusPill item={item} />
      {item.href ? (
        <div>
          <Link
            href={item.href}
            className={`${buttonVariants({ variant: "default" })} text-body-strong`}
          >
            {OPEN}
          </Link>
        </div>
      ) : null}
    </>
  );
}

function Detail({
  item,
  onDecided,
}: {
  item: InboxItem | null;
  /** After a decision in the review panel: read the Inbox again (the row's status). */
  onDecided?: () => void;
}) {
  if (!item) {
    return (
      <Card aria-label="Inbox item" role="region" className="p-6">
        <p className="text-text-secondary">{NO_SELECTION}</p>
      </Card>
    );
  }
  // Story 9.3: a Review item shows the review panel in place of the body and Open, greyed
  // when its subject is closed; 9.2's body while it loads and when it can't be read (e.g.
  // the reader's access ended with the request). Story 9.4: an author's outcome stays live
  // on a decided request; superseded and cancelled ones are greyed.
  if (item.subject_type === REVIEW_SUBJECT && item.opportunity_id) {
    return (
      <Card aria-label="Inbox item" role="region" className="gap-4 p-6" data-review-detail="">
        <ReviewPanelLoader
          key={item.id}
          opportunityId={item.opportunity_id}
          requestId={item.subject_id}
          layout="inbox"
          live={false}
          dimmed={isGreyedReviewItem(item)}
          fallback={<DetailBody item={item} />}
          onDecided={onDecided}
        />
      </Card>
    );
  }
  return (
    <Card aria-label="Inbox item" role="region" className="gap-4 p-6">
      <DetailBody item={item} />
    </Card>
  );
}

function ListSkeleton() {
  return (
    <Card aria-busy="true" aria-label={`${LIST_LABEL} (loading)`} role="region" className="p-5">
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <Skeleton key={i} className="mb-2.5 h-11 last:mb-0" />
      ))}
    </Card>
  );
}

/** The Inbox (Story 9.2): grouped list and detail side by side, Mark all read, Previous /
 * Next pages. Selecting a row (click, Enter, the arrow keys, or j/k with single-key
 * shortcuts on) shows it and marks it read; the sidebar count follows. It reads again on
 * window focus and every 30 s. */
export function InboxView({
  initial,
  pageNumber,
}: {
  initial: InboxPage | null;
  /** The `?page=` asked for: what a refresh reads, even after a failed first load. */
  pageNumber: number;
}) {
  const { singleKeyShortcuts } = useShell();
  const announce = useAnnounce();
  const skeletonDone = useSkeletonDone();
  const [page, setPage] = useState<InboxPage | null>(initial);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (initial) setInboxUnread(initial.unread);
  }, [initial]);

  const reload = useCallback(async () => {
    const result = await getInbox(pageNumber);
    if (result.kind !== "ok") return;
    setPage(result.page);
    setInboxUnread(result.page.unread);
  }, [pageNumber]);
  useInboxRefresh(() => void reload());

  const items = page?.items ?? [];
  const unread = page?.unread ?? 0;
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const ordered = groupItems(items);
  const flat = ordered.flatMap((section) => section.items);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && flat.some((i) => i.id === id)) ??
    flat[0]?.id;

  // The page as last rendered, for the rollback (a poll may have replaced it meanwhile).
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  });

  /** Replace the item; the page's unread count follows the change in its read state. */
  function patch(next: InboxItem) {
    setPage((current) => {
      if (!current) return current;
      const old = current.items.find((i) => i.id === next.id);
      const delta = old ? Number(!next.read) - Number(!old.read) : 0;
      return {
        ...current,
        unread: Math.max(0, current.unread + delta),
        items: current.items.map((i) => (i.id === next.id ? next : i)),
      };
    });
  }

  async function select(item: InboxItem) {
    setSelectedId(item.id);
    if (item.read) return;
    // Optimistic: the row and the sidebar count drop at once, and come back on a failure.
    patch({ ...item, read: true });
    adjustInboxUnread(-1);
    const result = await markInboxItemRead(item.id);
    if (result.kind === "ok") {
      patch(result.item);
    } else {
      const row = pageRef.current?.items.find((i) => i.id === item.id);
      if (row?.read) {
        patch({ ...row, read: false });
        adjustInboxUnread(1);
      }
    }
    void refreshInboxUnread();
  }

  async function markAll() {
    const result = await markAllInboxRead();
    if (result.kind !== "ok") return;
    setPage((current) =>
      current
        ? {
            ...current,
            unread: result.unread,
            items: current.items.map((i) => ({ ...i, read: true })),
          }
        : current,
    );
    setInboxUnread(result.unread);
    announce("All Inbox items marked read");
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const focused = document.activeElement?.getAttribute("data-inbox-row");
    const index = flat.findIndex((item) => item.id === focused);
    const step = down ? 1 : -1;
    const next = index === -1 ? 0 : Math.min(flat.length - 1, Math.max(0, index + step));
    const target = flat[next];
    if (!target) return;
    event.preventDefault();
    list.current?.querySelector<HTMLButtonElement>(`[data-inbox-row="${target.id}"]`)?.focus();
    void select(target);
  }

  let body;
  if (!skeletonDone) {
    body = <ListSkeleton />;
  } else if (page === null) {
    body = (
      <Card className="px-6 py-14 text-center">
        <p className="text-text-secondary">{NOT_REACHABLE}</p>
      </Card>
    );
  } else if (items.length === 0 && page.total === 0) {
    body = (
      <Card data-testid="inbox-empty" className="px-6 py-16 text-center">
        <p className="text-[16px] leading-6 font-semibold">{EMPTY_TITLE}</p>
        <p className="mt-1 text-text-secondary">{EMPTY_BODY}</p>
      </Card>
    );
  } else {
    body = (
      <>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-start gap-4">
          <Card
            ref={list}
            onKeyDown={onKeyDown}
            role="region"
            aria-label={LIST_LABEL}
            className="overflow-hidden"
          >
            {ordered.map((section) => (
              <section
                key={section.group}
                aria-labelledby={`inbox-group-${section.group}`}
                className="border-t border-border first:border-t-0"
              >
                <h2
                  id={`inbox-group-${section.group}`}
                  className="px-4 pt-3 pb-1 text-label tracking-[.04em] text-text-secondary uppercase"
                >
                  {section.label}
                </h2>
                <ul>
                  {section.items.map((item) => (
                    <Row
                      key={item.id}
                      item={item}
                      selected={item.id === selectedId}
                      tabStop={item.id === tabStopId}
                      onSelect={(i) => void select(i)}
                      onFocus={setFocusedId}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </Card>
          <Detail item={selected} onDecided={() => void reload()} />
        </div>
        <Pagination page={page} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={INBOX_TITLE}
        subtitle={PAGE_SUBTITLES.inbox}
        action={
          <Button variant="outline" disabled={unread === 0} onClick={() => void markAll()}>
            {MARK_ALL_READ}
          </Button>
        }
      />
      <PageContent>{body}</PageContent>
    </>
  );
}
