"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAnnounce } from "@/components/shell/live-region";
import { useBlockersEvents } from "@/lib/opportunity-events";
import { blockersAnnouncement, type SubmissionBlockersView } from "@/lib/submission";

/** Reads the blockers again: the view, or null when they could not be read. */
export type LoadBlockers = (opportunityId: string) => Promise<SubmissionBlockersView | null>;

type SubmissionState = {
  opportunityId: string;
  /** The API's blockers and current version; null when they could not be read. */
  view: SubmissionBlockersView | null;
  /** Read them again now (e.g. after a refused submission). */
  refresh: () => Promise<void>;
};

const SubmissionContext = createContext<SubmissionState | null>(null);

/** The workspace's submission blockers, if a `SubmissionProvider` is above. */
export function useSubmission(): SubmissionState | null {
  return useContext(SubmissionContext);
}

/** Holds the Opportunity's submission blockers (`GET …/submission-blockers`, the one check)
 * for the header, the tab badge, the Overview card and the Estimate tab. They are read again
 * on every blocker frame of the event stream (`useBlockersEvents`) and on reconnect; when the
 * count changes the polite live region says "3 blockers before you can submit" or "0 blockers
 * — ready to submit". A newer server value (a navigation) replaces the live one. */
export function SubmissionProvider({
  opportunityId,
  initial,
  load,
  children,
}: {
  opportunityId: string;
  initial: SubmissionBlockersView | null;
  /** Reads the blockers again (a server action); left out, they stay as given. */
  load?: LoadBlockers;
  children: ReactNode;
}) {
  const announce = useAnnounce();
  const [view, setView] = useState(initial);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const reads = useRef(0);
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
  }
  // A read started before a newer server value must not overwrite it.
  useEffect(() => {
    reads.current += 1;
  }, [initial]);
  const last = useRef<number | null>(initial ? initial.to_submit.length : null);

  const refresh = useCallback(async () => {
    if (!load) return;
    const started = ++reads.current;
    let next: SubmissionBlockersView | null;
    try {
      next = await load(opportunityId);
    } catch {
      return; // the next frame reads them again
    }
    if (next === null || started !== reads.current) return;
    setView(next);
  }, [opportunityId, load]);

  const count = view ? view.to_submit.length : null;
  useEffect(() => {
    if (count === null) return;
    const before = last.current;
    last.current = count;
    if (before !== null && before !== count) announce(blockersAnnouncement(count));
  }, [count, announce]);

  useBlockersEvents(opportunityId, () => void refresh(), load !== undefined);

  return (
    <SubmissionContext.Provider value={{ opportunityId, view, refresh }}>
      {children}
    </SubmissionContext.Provider>
  );
}

