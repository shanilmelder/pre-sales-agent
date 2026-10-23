"use client";

import type { MouseEvent } from "react";

/** The id of the shell's `<main>`, which the skip link focuses. */
export const MAIN_ID = "main-content";

/** First tab stop on every shell page: hidden above the viewport until focused, then it
 * jumps focus to the main pane. */
export function SkipLink() {
  function skip(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    document.getElementById(MAIN_ID)?.focus();
  }
  return (
    <a
      href={`#${MAIN_ID}`}
      onClick={skip}
      className="fixed left-2 -top-24 z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground text-body-strong outline-none focus:top-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      Skip to main content
    </a>
  );
}
