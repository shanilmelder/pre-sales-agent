// The Inbox unread count (Story 9.2): one store the sidebar badge and the Inbox page share, so
// marking an item read on the page drops the badge without a reload. There is no per-user
// stream: readers refresh on window focus, every `INBOX_POLL_MS`, and, inside an Opportunity,
// on its stream's Review Request, Conflict escalation and waiting-run frames.
"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";

import { getInboxUnreadCount } from "@/app/inbox/actions";
import { INBOX_POLL_MS } from "@/lib/inbox";
import { useInboxEvents } from "@/lib/opportunity-events";

let unread: number | null = null;
let inFlight: Promise<void> | null = null;
let again = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of [...listeners]) listener();
}

/** Set the count (e.g. from a mark-read answer). */
export function setInboxUnread(value: number): void {
  if (unread === value) return;
  unread = Math.max(0, value);
  emit();
}

/** Move the count by `delta` (optimistic updates); nothing before the first read. */
export function adjustInboxUnread(delta: number): void {
  if (unread !== null) setInboxUnread(unread + delta);
}

async function readOnce(): Promise<void> {
  try {
    const result = await getInboxUnreadCount();
    if (result.kind === "ok") setInboxUnread(result.unread);
  } catch {
    // keep the last count
  }
}

/** Read the count again from the API. A call while a read is in flight runs one more read
 * after it settles (that read may have started before, e.g., a mark-read), and concurrent
 * calls share it. A failed read keeps the last count. */
export function refreshInboxUnread(): Promise<void> {
  if (inFlight) {
    again = true;
    return inFlight;
  }
  // `let`: the body's `finally` runs after an await, once `run` is set.
  let run: Promise<void> | null = null;
  run = (async () => {
    try {
      do {
        again = false;
        await readOnce();
      } while (again);
    } finally {
      // Cleared here, right after the last check: a later call starts a new read.
      if (inFlight === run) inFlight = null;
    }
  })();
  inFlight = run;
  return run;
}

/** For tests: forget the count. */
export function resetInboxUnread(): void {
  unread = null;
  inFlight = null;
  again = false;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Run `refresh` on window focus, every `INBOX_POLL_MS`, and on the Opportunity's Inbox frames
 * when `opportunityId` is set. */
export function useInboxRefresh(refresh: () => void, opportunityId: string | null = null): void {
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    const run = () => latest.current();
    const timer = window.setInterval(run, INBOX_POLL_MS);
    window.addEventListener("focus", run);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", run);
    };
  }, []);
  useInboxEvents(opportunityId ?? "", () => latest.current(), opportunityId !== null);
}

/** The caller's unread count (null until first read), kept fresh as `useInboxRefresh`
 * describes. */
export function useInboxUnread(opportunityId: string | null = null): number | null {
  const count = useSyncExternalStore(
    subscribe,
    () => unread,
    () => null,
  );
  useEffect(() => {
    void refreshInboxUnread();
  }, []);
  useInboxRefresh(() => void refreshInboxUnread(), opportunityId);
  return count;
}
