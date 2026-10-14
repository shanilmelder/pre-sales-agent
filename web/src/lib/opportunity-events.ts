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
