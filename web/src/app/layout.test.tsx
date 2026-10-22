import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useShell } from "@/components/shell/shell-context";
import { THEME_SCRIPT } from "@/components/theme-script";
import type { Preferences } from "@/lib/preferences";

// Names shaped like next/font's generated classes (cn would merge two `font-*` names).
vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "__variable_inter" }),
}));

const preferences = vi.hoisted(() => ({ current: undefined as unknown as Preferences }));
const stored = vi.hoisted(() => ({ current: true }));
vi.mock("@/lib/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/preferences")>()),
  getPreferences: async () => preferences.current,
  hasStoredPreferences: async () => stored.current,
}));

import RootLayout from "./layout";

function FirstRunProbe() {
  const { firstRun } = useShell();
  return <p data-testid="first-run">{String(firstRun)}</p>;
}

async function renderLayout(children: React.ReactNode = <p>content</p>): Promise<Document> {
  const element = await RootLayout({ children } as LayoutProps<"/">);
  return new DOMParser().parseFromString(
    `<!doctype html>${renderToStaticMarkup(element)}`,
    "text/html",
  );
}

describe("RootLayout", () => {
  beforeEach(() => {
    preferences.current = { theme: "system", density: "comfortable", singleKeyShortcuts: false };
    stored.current = true;
  });

  it("Dark + Compact: data attributes and .dark alongside the font variables", async () => {
    preferences.current = { theme: "dark", density: "compact", singleKeyShortcuts: true };
    const html = (await renderLayout()).documentElement;
    expect(html.getAttribute("data-theme")).toBe("dark");
    expect(html.getAttribute("data-density")).toBe("compact");
    expect(html.classList.contains("dark")).toBe(true);
    expect(html.classList.contains("__variable_inter")).toBe(true);
  });

  it("System: no .dark from the server (the theme script decides)", async () => {
    const html = (await renderLayout()).documentElement;
    expect(html.getAttribute("data-theme")).toBe("system");
    expect(html.getAttribute("data-density")).toBe("comfortable");
    expect(html.classList.contains("dark")).toBe(false);
    expect(html.classList.contains("__variable_inter")).toBe(true);
  });

  it.each([
    [false, "true"],
    [true, "false"],
  ])("with stored preferences = %s, firstRun reaches the shell as %s", async (hasStored, expected) => {
    stored.current = hasStored;
    const doc = await renderLayout(<FirstRunProbe />);
    expect(doc.querySelector("[data-testid=first-run]")?.textContent).toBe(expected);
  });

  it("inlines the theme script in <head>", async () => {
    const doc = await renderLayout();
    const scripts = [...doc.head.querySelectorAll("script")].map((s) => s.textContent);
    expect(scripts).toContain(THEME_SCRIPT);
    expect(doc.body.textContent).toContain("content");
  });

  it("mounts the shell providers' single polite live region around the page", async () => {
    const doc = await renderLayout();
    expect(doc.body.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  });
});
