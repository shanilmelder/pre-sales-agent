"use client";

import { useRouter } from "next/navigation";
import { useRef } from "react";

import { useGapsEvents } from "@/lib/opportunity-events";

/** Re-renders the page from the server when the Opportunity's Gaps change (Story 4.7: the
 * Overview's Gaps counts follow the event stream's `gaps.changed` frames). The first callback,
 * on connecting, is skipped: the page was just rendered. Renders nothing. */
export function GapsLiveRefresh({ opportunityId }: { opportunityId: string }) {
  const router = useRouter();
  const connectedOnce = useRef(false);
  useGapsEvents(opportunityId, () => {
    if (!connectedOnce.current) {
      connectedOnce.current = true;
      return;
    }
    router.refresh();
  });
  return null;
}
