"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** Screen-reader announcements go out at most once per this interval. */
export const ANNOUNCE_INTERVAL_MS = 5000;
/** The region is emptied this long before a message is written, so a repeat of the same
 * message still changes the DOM and is read again. */
export const ANNOUNCE_CLEAR_MS = 50;

/** Throttles `emit` to one call per `interval`. A message that arrives too early waits for
 * the end of the interval; if several arrive, only the latest is announced. */
export function createThrottledAnnouncer(
  emit: (message: string) => void,
  interval = ANNOUNCE_INTERVAL_MS,
) {
  let lastAt = Number.NEGATIVE_INFINITY;
  let pending: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function send(message: string) {
    lastAt = Date.now();
    emit(message);
  }

  return {
    announce(message: string) {
      const wait = lastAt + interval - Date.now();
      if (wait <= 0 && timer === undefined) {
        send(message);
        return;
      }
      pending = message;
      timer ??= setTimeout(() => {
        timer = undefined;
        const next = pending;
        pending = null;
        if (next !== null) send(next);
      }, wait);
    },
    dispose() {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      pending = null;
    },
  };
}

/** A throttled announcer that empties the region before writing each message. */
function createRegionAnnouncer(setMessage: (message: string) => void) {
  let writeTimer: ReturnType<typeof setTimeout> | undefined;
  const throttled = createThrottledAnnouncer((next) => {
    setMessage("");
    clearTimeout(writeTimer);
    writeTimer = setTimeout(() => setMessage(next), ANNOUNCE_CLEAR_MS);
  });
  return {
    announce: throttled.announce,
    dispose() {
      throttled.dispose();
      clearTimeout(writeTimer);
    },
  };
}

const AnnounceContext = createContext<(message: string) => void>(() => {});

/** `announce(message)` for the shell's one polite live region. */
export function useAnnounce() {
  return useContext(AnnounceContext);
}

/** Mounts the shell's single polite `aria-live` region and provides `announce()`. */
export function LiveRegionProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const announcer = useMemo(() => createRegionAnnouncer(setMessage), []);
  useEffect(() => () => announcer.dispose(), [announcer]);

  return (
    <AnnounceContext.Provider value={announcer.announce}>
      {children}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {message}
      </div>
    </AnnounceContext.Provider>
  );
}
