import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Tests that opt into `@vitest-environment node` have no DOM to patch.
if (typeof window !== "undefined") {
  // jsdom gaps: user-event's radio arrow-key handling needs CSS.escape, and axe-core probes
  // canvas (jsdom logs "not implemented" without the optional canvas package).
  if (typeof globalThis.CSS === "undefined") {
    Object.defineProperty(globalThis, "CSS", { value: {}, configurable: true });
  }
  if (typeof CSS.escape !== "function") {
    // Enough for the ids and names user-event builds selectors from.
    CSS.escape = (value: string) => String(value).replace(/[^\w-]/g, (ch) => "\\" + ch);
  }
  // cmdk scrolls the selected item into view and observes the list size.
  if (typeof Element.prototype.scrollIntoView !== "function") {
    Element.prototype.scrollIntoView = function scrollIntoView() {};
  }
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
}

afterEach(() => {
  cleanup();
});
