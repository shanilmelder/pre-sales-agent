"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(max-width: 1023.98px)";

function hasMatchMedia() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

function subscribe(onChange: () => void) {
  if (!hasMatchMedia()) return () => {};
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function getSnapshot() {
  return hasMatchMedia() ? window.matchMedia(QUERY).matches : false;
}

/** True below 1024px, where the workbench is read-only (Story 17.2c). The server render
 * treats the viewport as wide. */
export function useNarrowViewport(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
