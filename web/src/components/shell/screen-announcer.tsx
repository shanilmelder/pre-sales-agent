"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useAnnounce } from "@/components/shell/live-region";

const PRODUCT = "Pre Sales Agent Framework";
/** Next.js applies the new page's metadata just after the route renders. */
export const TITLE_SETTLE_MS = 100;

/** The screen name in a page title: the part before " · Pre Sales Agent Framework".
 * Empty for no title or the bare product name. */
export function screenName(title: string): string {
  const name = title.split(" · ")[0]?.trim() ?? "";
  return name === PRODUCT ? "" : name;
}

/** Announces the screen name through the polite live region when the page loads or the
 * route changes. Renders nothing. */
export function ScreenAnnouncer() {
  const pathname = usePathname();
  const announce = useAnnounce();
  useEffect(() => {
    const timer = setTimeout(() => {
      const name = screenName(document.title);
      if (name) announce(name);
    }, TITLE_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [pathname, announce]);
  return null;
}
