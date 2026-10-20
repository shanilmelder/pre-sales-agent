"use client";

import { useRouter } from "next/navigation";
import { useRef } from "react";

import { useConflictsEvents } from "@/lib/opportunity-events";

/** Re-renders the Conflicts tab from the server when the Opportunity's Conflicts change (Story
 * 6.2: a semantic Conflict stored by the background job, a rerun, or someone else's
 * decision arrives as a `conflicts.changed` frame). The first callback, on connecting, is
 * skipped: the page was just rendered. If the stream drops, the next navigation shows the
 * change. Renders nothing. */
export function ConflictsLiveRefresh({ opportunityId }: { opportunityId: string }) {
  const router = useRouter();
  const connectedOnce = useRef(false);
  useConflictsEvents(opportunityId, () => {
    if (!connectedOnce.current) {
      connectedOnce.current = true;
      return;
    }
    router.refresh();
  });
  return null;
}
