import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_SCRIPT } from "./theme-script";

type Listener = () => void;

function mockOsTheme(initial: "light" | "dark") {
  const listeners: Listener[] = [];
  const media = {
    matches: initial === "dark",
    addEventListener: (_type: string, listener: Listener) => listeners.push(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  return {
    change(theme: "light" | "dark") {
      media.matches = theme === "dark";
      listeners.forEach((listener) => listener());
    },
  };
}

function runScript() {
  // The same source the layout inlines into <head>.
  new Function(THEME_SCRIPT)();
}

const root = () => document.documentElement;
const flushObserver = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("theme script", () => {
  // Every run attaches an observer to the shared <html>; disconnect them between tests.
  const observers: MutationObserver[] = [];
  const RealObserver = globalThis.MutationObserver;

  beforeEach(() => {
    root().className = "";
    vi.stubGlobal(
      "MutationObserver",
      class extends RealObserver {
        constructor(callback: MutationCallback) {
          super(callback);
          observers.push(this);
        }
      },
    );
  });

  afterEach(() => {
    observers.splice(0).forEach((observer) => observer.disconnect());
    vi.unstubAllGlobals();
  });

  it("System + OS dark: .dark before first paint (no cookie)", () => {
    root().setAttribute("data-theme", "system");
    mockOsTheme("dark");
    runScript();
    expect(root().classList.contains("dark")).toBe(true);
  });

  it("System + OS light: no .dark", () => {
    root().setAttribute("data-theme", "system");
    mockOsTheme("light");
    runScript();
    expect(root().classList.contains("dark")).toBe(false);
  });

  it("Light override ignores an OS dark theme, also when the OS changes", () => {
    root().setAttribute("data-theme", "light");
    const os = mockOsTheme("dark");
    runScript();
    expect(root().classList.contains("dark")).toBe(false);
    os.change("dark");
    expect(root().classList.contains("dark")).toBe(false);
  });

  it("Dark override keeps the server's .dark when the OS is light", () => {
    root().setAttribute("data-theme", "dark");
    root().className = "dark";
    const os = mockOsTheme("light");
    runScript();
    os.change("light");
    expect(root().classList.contains("dark")).toBe(true);
  });

  it("System follows OS theme changes live", () => {
    root().setAttribute("data-theme", "system");
    const os = mockOsTheme("light");
    runScript();
    os.change("dark");
    expect(root().classList.contains("dark")).toBe(true);
    os.change("light");
    expect(root().classList.contains("dark")).toBe(false);
  });

  it("Back to System: re-applies the OS theme when React re-renders <html>", async () => {
    root().setAttribute("data-theme", "light");
    mockOsTheme("dark");
    runScript();
    expect(root().classList.contains("dark")).toBe(false);

    // What the layout re-render after saving System does: new data-theme, server className.
    root().setAttribute("data-theme", "system");
    root().className = "font-vars";
    await flushObserver();
    expect(root().classList.contains("dark")).toBe(true);
    expect(root().classList.contains("font-vars")).toBe(true);
  });

  it("System -> Light while the OS is dark removes the script-added .dark", async () => {
    root().setAttribute("data-theme", "system");
    mockOsTheme("dark");
    runScript();
    expect(root().classList.contains("dark")).toBe(true);

    // The server className is "" for both System and Light, so React leaves `class` alone.
    root().setAttribute("data-theme", "light");
    await flushObserver();
    expect(root().classList.contains("dark")).toBe(false);
  });

  it("does nothing (and does not throw) where matchMedia is missing", () => {
    root().setAttribute("data-theme", "system");
    vi.stubGlobal("matchMedia", undefined);
    expect(runScript).not.toThrow();
    expect(root().classList.contains("dark")).toBe(false);
  });
});
