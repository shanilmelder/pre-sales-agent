"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";

import {
  useBlockersEvents,
  useConflictsEvents,
  useGapsEvents,
  useOpportunityEvents,
  useReviewEvents,
  useSourceEvents,
} from "@/lib/opportunity-events";

/** How long the Overview waits after the last frame before re-rendering. */
export const OVERVIEW_REFRESH_DEBOUNCE_MS = 300;

/** A callback that skips its first call (the hook's connect callback: the page was just
 * rendered) and runs `run` for every later one. */
function useAfterFirst(run: () => void): () => void {
  const seen = useRef(false);
  return useCallback(() => {
    if (!seen.current) {
      seen.current = true;
      return;
    }
    run();
  }, [run]);
}

/** Re-renders the Overview from the server when the Opportunity changes (Story 8.9, AD-30):
 * on progress events, `gaps.changed`, `conflicts.changed`, blocker frames, Source frames and
 * Review frames. A burst of frames causes one `router.refresh()` about 300 ms after the last;
 * each hook's first callback, on connecting, is skipped. Renders nothing. */
export function OverviewLiveRefresh({ opportunityId }: { opportunityId: string }) {
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );
  const schedule = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      router.refresh();
    }, OVERVIEW_REFRESH_DEBOUNCE_MS);
  }, [router]);

  useOpportunityEvents(opportunityId, useAfterFirst(schedule));
  useGapsEvents(opportunityId, useAfterFirst(schedule));
  useConflictsEvents(opportunityId, useAfterFirst(schedule));
  useBlockersEvents(opportunityId, useAfterFirst(schedule));
  useSourceEvents(opportunityId, useAfterFirst(schedule));
  useReviewEvents(opportunityId, useAfterFirst(schedule));
  return null;
}
