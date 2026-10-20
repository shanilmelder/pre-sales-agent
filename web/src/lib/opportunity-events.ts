// The Opportunity's live event stream (Story 5.2, AD-30): an EventSource on the same-origin
// route `/api/opportunities/{id}/events`, which adds the access token server-side. The
// browser reconnects by itself with `Last-Event-ID`, and the backend replays what was
// missed. Frames carry ids, an event type and a summary of Agent ids and statuses only.
"use client";

import { useEffect, useRef, useState } from "react";

import type { paths } from "@/lib/api/client";

type StreamContent =
  paths["/api/v1/opportunities/{opportunity_id}/events"]["get"]["responses"][200]["content"]["text/event-stream"];

/** The `data` of one progress frame. */
export type ProgressEventData = StreamContent;
export type ProgressEventType = ProgressEventData["event_type"];

export const PROGRESS_EVENTS: readonly ProgressEventType[] = [
  "workflows.run.queued",
  "workflows.task.started",
  "workflows.task.ended",
  "workflows.run.ended",
];

export function eventsUrl(opportunityId: string): string {
  return `/api/opportunities/${encodeURIComponent(opportunityId)}/events`;
}

/** Parses a frame's `data`; null when it isn't a progress event. */
export function parseProgress(
  type: string,
  raw: string,
): ProgressEventData | null {
  if (!(PROGRESS_EVENTS as readonly string[]).includes(type)) return null;
  try {
    const data = JSON.parse(raw) as Partial<ProgressEventData>;
    return data.event_type === type ? (data as ProgressEventData) : null;
  } catch {
    return null;
  }
}

/** Subscribe to the Opportunity's progress events while `enabled`. `onChange` runs for each
 * progress event and whenever the stream (re)connects (so a reader catches up after a gap).
 * Returns whether the stream is connected; while it isn't (unsupported, connecting, dropped
 * or refused), callers fall back to polling. */
export function useOpportunityEvents(
  opportunityId: string,
  onChange: (event: ProgressEventData | null) => void,
  enabled = true,
): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onChange);
  useEffect(() => {
    handler.current = onChange;
  });

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource(eventsUrl(opportunityId));
    const onOpen = () => {
      setConnected(true);
      handler.current(null);
    };
    // The browser retries by itself; a refusal (e.g. 404) closes the source for good.
    const onError = () => setConnected(false);
    const onProgress = (event: Event) => {
      const message = event as MessageEvent<string>;
      const data = parseProgress(message.type, message.data);
      if (data) handler.current(data);
    };
    source.addEventListener("open", onOpen);
    source.addEventListener("error", onError);
    for (const type of PROGRESS_EVENTS)
      source.addEventListener(type, onProgress);
    return () => {
      source.close();
      setConnected(false);
    };
  }, [opportunityId, enabled]);

  return connected;
}

/** Story 4.7: the id-less frame the stream sends when the Opportunity's Gaps, Clarification
 * Questions or answer suggestions change (no content: readers re-read). */
export const GAPS_CHANGED = "gaps.changed";

/** Story 6.2: the id-less frame the stream sends when the Opportunity's Conflicts change (a
 * Conflict raised or resolved by detection, or resolved or escalated by a person). */
export const CONFLICTS_CHANGED = "conflicts.changed";

/** The id-less "re-read" frames a subscriber can follow. */
export type ChangeFrame = typeof GAPS_CHANGED | typeof CONFLICTS_CHANGED;
const CHANGE_FRAMES: readonly ChangeFrame[] = [GAPS_CHANGED, CONFLICTS_CHANGED];

type ChangeSubscriber = {
  frame: ChangeFrame;
  changed: () => void;
  connected: (on: boolean) => void;
};
type SharedSource = { source: EventSource; open: boolean; subscribers: Set<ChangeSubscriber> };

/** One EventSource per Opportunity, shared by every `useGapsEvents` and `useConflictsEvents`
 * subscriber (the tab badges, the Gaps and Conflicts tabs, the Overview) and closed when the
 * last one leaves, so the page doesn't use up the browser's connections to the origin. */
const sharedSources = new Map<string, SharedSource>();

function subscribeChanges(opportunityId: string, subscriber: ChangeSubscriber): () => void {
  let shared = sharedSources.get(opportunityId);
  if (!shared) {
    const source = new EventSource(eventsUrl(opportunityId));
    const created: SharedSource = { source, open: false, subscribers: new Set() };
    source.addEventListener("open", () => {
      created.open = true;
      for (const s of [...created.subscribers]) {
        s.connected(true);
        s.changed();
      }
    });
    // The browser retries by itself; a refusal (e.g. 404) closes the source for good.
    source.addEventListener("error", () => {
      created.open = false;
      for (const s of [...created.subscribers]) s.connected(false);
    });
    for (const frame of CHANGE_FRAMES) {
      source.addEventListener(frame, () => {
        for (const s of [...created.subscribers]) if (s.frame === frame) s.changed();
      });
    }
    sharedSources.set(opportunityId, created);
    shared = created;
  }
  shared.subscribers.add(subscriber);
  if (shared.open) {
    // A late subscriber catches up as if it had just connected.
    subscriber.connected(true);
    subscriber.changed();
  }
  const current = shared;
  return () => {
    current.subscribers.delete(subscriber);
    if (current.subscribers.size === 0) {
      current.source.close();
      if (sharedSources.get(opportunityId) === current) sharedSources.delete(opportunityId);
    }
  };
}

function useChangeEvents(
  frame: ChangeFrame,
  opportunityId: string,
  onChange: () => void,
  enabled: boolean,
): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onChange);
  useEffect(() => {
    handler.current = onChange;
  });

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const unsubscribe = subscribeChanges(opportunityId, {
      frame,
      changed: () => handler.current(),
      connected: setConnected,
    });
    return () => {
      unsubscribe();
      setConnected(false);
    };
  }, [frame, opportunityId, enabled]);

  return connected;
}

/** Subscribe to the Opportunity's `gaps.changed` frames while `enabled`. `onChange` runs for
 * each and whenever the stream (re)connects. Returns whether the stream is connected; while it
 * isn't, callers keep their own polling. Every subscriber of one Opportunity shares a single
 * EventSource. */
export function useGapsEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  return useChangeEvents(GAPS_CHANGED, opportunityId, onChange, enabled);
}

/** Subscribe to the Opportunity's `conflicts.changed` frames while `enabled` (Story 6.2: the
 * Conflicts tab and its badge). `onChange` runs for each and whenever the stream (re)connects.
 * Returns whether the stream is connected. Shares the EventSource with `useGapsEvents`. */
export function useConflictsEvents(
  opportunityId: string,
  onChange: () => void,
  enabled = true,
): boolean {
  return useChangeEvents(CONFLICTS_CHANGED, opportunityId, onChange, enabled);
}
