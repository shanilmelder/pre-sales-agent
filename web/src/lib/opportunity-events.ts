// The Opportunity's live event stream (Stories 5.2, 4.7 and 2.3, AD-30): one EventSource per
// Opportunity on the same-origin route `/api/opportunities/{id}/events`, which adds the access
// token server-side. Every subscriber on the page (progress, `gaps.changed`,
// `conflicts.changed`, Source frames and the workspace status bar) shares it, so the page doesn't use up the browser's
// connections to the origin; it closes with the last subscriber.
//
// The browser reconnects by itself with `Last-Event-ID` after a dropped stream, and the
// backend replays what was missed. When the browser gives up instead (`readyState` CLOSED,
// e.g. the route answered 502 or 401), the connection reopens itself after a capped backoff
// (1, 2, 5, then 10 s) with `?last_event_id=` set to the last frame id it saw. Frames carry
// ids, an event type and a summary only, never customer content.
"use client";

import { useEffect, useRef, useState } from "react";

import type { paths } from "@/lib/api/client";
import { FINDING_EVENTS } from "@/lib/findings";

type StreamContent =
  paths["/api/v1/opportunities/{opportunity_id}/events"]["get"]["responses"][200]["content"]["text/event-stream"];

/** The member of the frame union whose `event_type` is a set of literals (not any string). */
type WithLiteralType<U> = U extends { event_type: infer E } ? (string extends E ? never : U) : never;

/** The `data` of one progress frame. */
export type ProgressEventData = WithLiteralType<StreamContent>;
export type ProgressEventType = ProgressEventData["event_type"];
/** The `data` of one trace frame (Story 2.3): `summary` is the event type. */
export type TraceEventData = Exclude<StreamContent, ProgressEventData>;

export const PROGRESS_EVENTS: readonly ProgressEventType[] = [
  "workflows.run.queued",
  "workflows.task.started",
  "workflows.task.ended",
  "workflows.run.ended",
  "workflows.run.waiting_for_human",
];

/** Story 4.7: the id-less frame the stream sends when the Opportunity's Gaps, Clarification
 * Questions or answer suggestions change (no content: readers re-read). */
export const GAPS_CHANGED = "gaps.changed";

/** Story 6.2: the id-less frame the stream sends when the Opportunity's Conflicts change (a
 * Conflict raised or resolved by detection, or resolved or escalated by a person). */
export const CONFLICTS_CHANGED = "conflicts.changed";

/** Story 2.3: the trace frames that change a Source's row (`intake.source.*`). */
export const SOURCE_EVENTS: readonly string[] = [
  "intake.source.added",
  "intake.source.parse_started",
  "intake.source.parsed",
  "intake.source.parse_failed",
  "intake.source.parse_retried",
];

/** How long the stream waits before reopening after the browser gave up, by attempt; the
 * last value repeats. */
export const RECONNECT_DELAYS_MS: readonly number[] = [1000, 2000, 5000, 10000];
/** After this long down, the shell shows the Offline strip ("Offline — edits disabled"). */
export const OFFLINE_AFTER_MS = 60_000;

/** The shared connection's state. `connecting` only before the first open; after a drop it
 * is `reconnecting`, then `offline` once down for `OFFLINE_AFTER_MS`. */
export type StreamStatus = "connecting" | "open" | "reconnecting" | "offline";

export function eventsUrl(opportunityId: string, lastEventId?: string | null): string {
  const base = `/api/opportunities/${encodeURIComponent(opportunityId)}/events`;
  return lastEventId ? `${base}?last_event_id=${encodeURIComponent(lastEventId)}` : base;
}

/** Parses a frame's `data`; null when it isn't a progress event. */
export function parseProgress(type: string, raw: string): ProgressEventData | null {
  if (!(PROGRESS_EVENTS as readonly string[]).includes(type)) return null;
  try {
    const data = JSON.parse(raw) as Partial<ProgressEventData>;
    return data.event_type === type ? (data as ProgressEventData) : null;
  } catch {
    return null;
  }
}

/** One subscriber of the shared connection. */
export type StreamSubscriber = {
  /** The frame types it wants `frame` called for. */
  types: readonly string[];
  frame?: (type: string, data: string) => void;
  /** Runs on every (re)connect, so the subscriber can re-read what it may have missed. */
  connected?: () => void;
  status?: (status: StreamStatus) => void;
};

type Shared = {
  opportunityId: string;
  source: EventSource | null;
  status: StreamStatus;
  lastEventId: string | null;
  attempt: number;
  reopenTimer: ReturnType<typeof setTimeout> | null;
  offlineTimer: ReturnType<typeof setTimeout> | null;
  types: Set<string>;
  subscribers: Set<StreamSubscriber>;
};

const sharedConnections = new Map<string, Shared>();

function setStatus(shared: Shared, status: StreamStatus) {
  if (shared.status === status) return;
  shared.status = status;
  for (const s of [...shared.subscribers]) s.status?.(status);
}

function dispatch(shared: Shared, type: string, event: Event | undefined) {
  const message = event as MessageEvent<string> | undefined;
  if (message?.lastEventId) shared.lastEventId = message.lastEventId;
  for (const s of [...shared.subscribers]) {
    if (s.types.includes(type)) s.frame?.(type, message?.data ?? "");
  }
}

function listen(shared: Shared, type: string) {
  shared.source?.addEventListener(type, (event) => dispatch(shared, type, event));
}

function markDown(shared: Shared) {
  if (shared.status === "open" || shared.status === "connecting") {
    setStatus(shared, "reconnecting");
  }
  shared.offlineTimer ??= setTimeout(() => {
    shared.offlineTimer = null;
    if (shared.status === "reconnecting") setStatus(shared, "offline");
  }, OFFLINE_AFTER_MS);
}

function open(shared: Shared) {
  const source = new EventSource(eventsUrl(shared.opportunityId, shared.lastEventId));
  shared.source = source;
  source.addEventListener("open", () => {
    if (shared.source !== source) return;
    shared.attempt = 0;
    if (shared.offlineTimer) clearTimeout(shared.offlineTimer);
    shared.offlineTimer = null;
    setStatus(shared, "open");
    for (const s of [...shared.subscribers]) s.connected?.();
  });
  source.addEventListener("error", () => {
    if (shared.source !== source) return;
    markDown(shared);
    // CONNECTING: the browser retries by itself (with `Last-Event-ID`). CLOSED: it gave up,
    // so reopen after a backoff.
    if (source.readyState !== 2 || shared.reopenTimer) return;
    source.close();
    const delays = RECONNECT_DELAYS_MS;
    const delay = delays[Math.min(shared.attempt, delays.length - 1)]!;
    shared.attempt += 1;
    shared.reopenTimer = setTimeout(() => {
      shared.reopenTimer = null;
      if (sharedConnections.get(shared.opportunityId) === shared) open(shared);
    }, delay);
  });
  for (const type of shared.types) listen(shared, type);
}

function close(shared: Shared) {
  shared.source?.close();
  shared.source = null;
  if (shared.reopenTimer) clearTimeout(shared.reopenTimer);
  if (shared.offlineTimer) clearTimeout(shared.offlineTimer);
  shared.reopenTimer = null;
  shared.offlineTimer = null;
}

/** Joins the Opportunity's shared connection (opening it if needed). A late subscriber to an
 * open stream catches up at once, as if it had just connected. Returns the unsubscribe. */
export function subscribe(opportunityId: string, subscriber: StreamSubscriber): () => void {
  let shared = sharedConnections.get(opportunityId);
  if (!shared) {
    shared = {
      opportunityId,
      source: null,
      status: "connecting",
      lastEventId: null,
      attempt: 0,
      reopenTimer: null,
      offlineTimer: null,
      types: new Set(),
      subscribers: new Set(),
    };
    sharedConnections.set(opportunityId, shared);
    open(shared);
  }
  const current = shared;
  for (const type of subscriber.types) {
    if (!current.types.has(type)) {
      current.types.add(type);
      listen(current, type);
    }
  }
  current.subscribers.add(subscriber);
  subscriber.status?.(current.status);
  if (current.status === "open") subscriber.connected?.();
  return () => {
    current.subscribers.delete(subscriber);
    if (current.subscribers.size === 0) {
      close(current);
      if (sharedConnections.get(opportunityId) === current) sharedConnections.delete(opportunityId);
    }
  };
}

/** Reopens the Opportunity's stream at once (the Offline strip's Retry): drops a source that
 * is down, cancels the pending backoff, resets it and keeps `lastEventId`. Does nothing when
 * the Opportunity has no shared connection or its stream is already open. */
export function retryEventStream(opportunityId: string): void {
  const shared = sharedConnections.get(opportunityId);
  if (!shared || shared.status === "open") return;
  shared.source?.close();
  if (shared.reopenTimer) clearTimeout(shared.reopenTimer);
  shared.reopenTimer = null;
  shared.attempt = 0;
  open(shared);
}

/** Subscribe while `enabled`; returns the connection's status (`connecting` while disabled
 * or where EventSource isn't available). */
function useStream(
  opportunityId: string,
  types: readonly string[],
  onFrame: ((type: string, data: string) => void) | null,
  onConnected: (() => void) | null,
  enabled: boolean,
): StreamStatus {
  const [status, setStatusState] = useState<StreamStatus>("connecting");
  const frameRef = useRef(onFrame);
  const connectedRef = useRef(onConnected);
  useEffect(() => {
    frameRef.current = onFrame;
    connectedRef.current = onConnected;
  });
  const key = types.join(" ");

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const unsubscribe = subscribe(opportunityId, {
      types: key ? key.split(" ") : [],
      frame: (type, data) => frameRef.current?.(type, data),
      connected: () => connectedRef.current?.(),
      status: setStatusState,
    });
    return () => {
      unsubscribe();
      setStatusState("connecting");
    };
  }, [opportunityId, enabled, key]);

  return status;
}

/** Subscribe to the Opportunity's progress events while `enabled`. `onChange` runs for each
 * progress event (with its data) and whenever the stream (re)connects (with null, so a reader
 * catches up after a gap). Returns whether the stream is connected; while it isn't, callers
 * fall back to polling. */
export function useOpportunityEvents(
  opportunityId: string,
  onChange: (event: ProgressEventData | null) => void,
  enabled = true,
): boolean {
  const status = useStream(
    opportunityId,
    PROGRESS_EVENTS,
    (type, raw) => {
      const data = parseProgress(type, raw);
      if (data) onChange(data);
    },
    () => onChange(null),
    enabled,
  );
  return status === "open";
}

/** Subscribe to the Opportunity's `gaps.changed` frames while `enabled`. `onChange` runs for
 * each and whenever the stream (re)connects. Returns whether the stream is connected; while it
 * isn't, callers keep their own polling. */
export function useGapsEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  const status = useStream(opportunityId, [GAPS_CHANGED], () => onChange(), onChange, enabled);
  return status === "open";
}

/** Subscribe to the Opportunity's `conflicts.changed` frames while `enabled` (Story 6.2: the
 * Conflicts tab and its badge). `onChange` runs for each and whenever the stream (re)connects.
 * Returns whether the stream is connected. */
export function useConflictsEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  const status = useStream(opportunityId, [CONFLICTS_CHANGED], () => onChange(), onChange, enabled);
  return status === "open";
}

/** Story 2.3: subscribe to the Opportunity's `intake.source.*` frames while `enabled`.
 * `onChange` runs for each and whenever the stream (re)connects. Returns whether the stream
 * is connected; while it isn't, the Sources tab polls. */
export function useSourceEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  const status = useStream(opportunityId, SOURCE_EVENTS, () => onChange(), onChange, enabled);
  return status === "open";
}

/** Story 6.6: subscribe to the Opportunity's Finding and Review trace frames
 * (`FINDING_EVENTS`) while `enabled` (the Assessments tab's blocking badge). `onChange` runs for
 * each and whenever the stream (re)connects. Returns whether the stream is connected. */
export function useFindingsEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  const status = useStream(opportunityId, FINDING_EVENTS, () => onChange(), onChange, enabled);
  return status === "open";
}

/** Story 2.3: the shared connection's status, for the workspace status bar. */
export function useEventStreamStatus(opportunityId: string, enabled = true): StreamStatus {
  return useStream(opportunityId, [], null, null, enabled);
}
