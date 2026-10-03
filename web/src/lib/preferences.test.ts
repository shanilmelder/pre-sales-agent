import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, it, vi } from "vitest";

const cookieStore = vi.hoisted(() => ({ value: undefined as string | undefined }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "psa_prefs" && cookieStore.value !== undefined
        ? { name, value: cookieStore.value }
        : undefined,
  }),
}));

import {
  DEFAULT_PREFERENCES,
  PREFERENCES_COOKIE,
  getPreferences,
  htmlPreferenceAttributes,
  isPreferences,
  parsePreferences,
  serializePreferences,
  type Preferences,
} from "./preferences";

const DEFAULTS: Preferences = { theme: "system", density: "comfortable", singleKeyShortcuts: true };

describe("defaults", () => {
  it("are System, comfortable (32px) and shortcuts on", () => {
    expect(DEFAULT_PREFERENCES).toEqual(DEFAULTS);
    expect(PREFERENCES_COOKIE).toBe("psa_prefs");
  });
});

describe("parsePreferences", () => {
  it.each([
    ["missing", undefined],
    ["empty", ""],
    ["not JSON", "{theme:dark"],
    ["JSON null", "null"],
    ["JSON array", '["dark"]'],
    ["JSON string", '"dark"'],
    ["unknown values", '{"theme":"sepia","density":"tiny","singleKeyShortcuts":"yes"}'],
    ["wrong types", '{"theme":1,"density":null,"singleKeyShortcuts":0}'],
  ])("falls back to the defaults for a %s cookie", (_label, raw) => {
    expect(parsePreferences(raw)).toEqual(DEFAULTS);
  });

  it("keeps valid fields and defaults only the invalid ones", () => {
    expect(parsePreferences('{"theme":"dark","density":"huge"}')).toEqual({
      ...DEFAULTS,
      theme: "dark",
    });
  });

  it("ignores extra fields", () => {
    expect(parsePreferences('{"theme":"light","__proto__":{"x":1},"extra":true}')).toEqual({
      ...DEFAULTS,
      theme: "light",
    });
  });

  it.each<Preferences>([
    { theme: "light", density: "comfortable", singleKeyShortcuts: true },
    { theme: "dark", density: "compact", singleKeyShortcuts: false },
    { theme: "system", density: "compact", singleKeyShortcuts: false },
  ])("round-trips %o through serializePreferences", (preferences) => {
    expect(parsePreferences(serializePreferences(preferences))).toEqual(preferences);
  });
});

describe("isPreferences (write validation)", () => {
  it("accepts a complete, valid object", () => {
    expect(isPreferences({ theme: "dark", density: "compact", singleKeyShortcuts: false })).toBe(
      true,
    );
  });

  it.each([
    null,
    "dark",
    [],
    {},
    { theme: "dark", density: "compact" },
    { theme: "sepia", density: "compact", singleKeyShortcuts: true },
    { theme: "dark", density: "tiny", singleKeyShortcuts: true },
    { theme: "dark", density: "compact", singleKeyShortcuts: "false" },
  ])("rejects %o", (value) => {
    expect(isPreferences(value)).toBe(false);
  });
});

describe("htmlPreferenceAttributes (first paint)", () => {
  it("System leaves .dark to the theme script", () => {
    expect(htmlPreferenceAttributes(DEFAULTS)).toEqual({
      className: "",
      "data-theme": "system",
      "data-density": "comfortable",
    });
  });

  it("Light never sets .dark, whatever the OS says", () => {
    expect(htmlPreferenceAttributes({ ...DEFAULTS, theme: "light" }).className).toBe("");
  });

  it("Dark sets .dark on the server", () => {
    expect(htmlPreferenceAttributes({ ...DEFAULTS, theme: "dark" }).className).toBe("dark");
  });

  it("Compact sets data-density=compact", () => {
    expect(htmlPreferenceAttributes({ ...DEFAULTS, density: "compact" })["data-density"]).toBe(
      "compact",
    );
  });
});

describe("getPreferences (server reader)", () => {
  beforeEach(() => {
    cookieStore.value = undefined;
  });

  it("returns the defaults with no cookie", async () => {
    expect(await getPreferences()).toEqual(DEFAULTS);
  });

  it("returns the defaults for a malformed cookie, without throwing", async () => {
    cookieStore.value = "%%%not-json";
    expect(await getPreferences()).toEqual(DEFAULTS);
  });

  it("reads Light, Compact and shortcuts Off back after a reload", async () => {
    cookieStore.value = serializePreferences({
      theme: "light",
      density: "compact",
      singleKeyShortcuts: false,
    });
    expect(await getPreferences()).toEqual({
      theme: "light",
      density: "compact",
      singleKeyShortcuts: false,
    });
  });
});

describe("density token in globals.css", () => {
  // Not inlined into `new URL(..., import.meta.url)`: Vite rewrites that pattern to a served
  // asset URL (http://localhost:3000/...), which fs cannot read.
  const testFile = import.meta.url;
  const css = readFileSync(fileURLToPath(new URL("../app/globals.css", testFile)), "utf8");

  it("defines 32px comfortable and 28px compact rows", () => {
    expect(css).toMatch(/--row-height-comfortable:\s*32px;/);
    expect(css).toMatch(/--row-height-compact:\s*28px;/);
    expect(css).toMatch(/:root\s*\{[^}]*--row-height:\s*var\(--row-height-comfortable\);/);
  });

  it("switches the one row variable to 28px under data-density=compact", () => {
    expect(css).toMatch(
      /\[data-density="compact"\]\s*\{\s*--row-height:\s*var\(--row-height-compact\);\s*\}/,
    );
  });

  it("exposes the size tokens to Tailwind", () => {
    for (const token of [
      "--spacing-row: var(--row-height)",
      "--spacing-row-compact: var(--row-height-compact)",
      "--spacing-sidebar: 220px",
      "--spacing-inspector: 420px",
      "--spacing-rail: 300px",
      "--spacing-gutter: 16px",
    ]) {
      expect(css).toContain(token);
    }
  });
});
