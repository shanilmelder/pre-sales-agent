// Per-browser UI preferences, stored in one cookie and read on the server so `<html>`
// carries the right theme and density on first paint. No server-side storage.
// Client components may only `import type` from here: it imports `next/headers`.
import { cookies } from "next/headers";

export const THEMES = ["system", "light", "dark"] as const;
export const DENSITIES = ["comfortable", "compact"] as const;

export type Theme = (typeof THEMES)[number];
export type Density = (typeof DENSITIES)[number];

export type Preferences = {
  theme: Theme;
  density: Density;
  /** Stored here; honoured by the keyboard layer in Story 1.5 Part B. */
  singleKeyShortcuts: boolean;
};

export const PREFERENCES_COOKIE = "psa_prefs";
/** One year; the cookie is refreshed on every save. */
export const PREFERENCES_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export const DEFAULT_PREFERENCES: Readonly<Preferences> = Object.freeze({
  theme: "system",
  density: "comfortable",
  singleKeyShortcuts: true,
});

function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

function isDensity(value: unknown): value is Density {
  return typeof value === "string" && (DENSITIES as readonly string[]).includes(value);
}

/** Strict check for a full preferences object (used for writes). */
export function isPreferences(value: unknown): value is Preferences {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return (
    isTheme(v.theme) && isDensity(v.density) && typeof v.singleKeyShortcuts === "boolean"
  );
}

/** Lenient read of the cookie value: anything missing, malformed or unknown falls back to
 * the default for that field. Never throws. */
export function parsePreferences(raw: string | null | undefined): Preferences {
  if (!raw) return { ...DEFAULT_PREFERENCES };
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { ...DEFAULT_PREFERENCES };
  }
  const v = data as Record<string, unknown>;
  return {
    theme: isTheme(v.theme) ? v.theme : DEFAULT_PREFERENCES.theme,
    density: isDensity(v.density) ? v.density : DEFAULT_PREFERENCES.density,
    singleKeyShortcuts:
      typeof v.singleKeyShortcuts === "boolean"
        ? v.singleKeyShortcuts
        : DEFAULT_PREFERENCES.singleKeyShortcuts,
  };
}

export function serializePreferences(preferences: Preferences): string {
  const { theme, density, singleKeyShortcuts } = preferences;
  return JSON.stringify({ theme, density, singleKeyShortcuts });
}

/** Attributes for `<html>`. `dark` is set only for an explicit Dark choice; for System the
 * inline theme script adds it from `prefers-color-scheme` before paint. */
export function htmlPreferenceAttributes(preferences: Preferences) {
  return {
    className: preferences.theme === "dark" ? "dark" : "",
    "data-theme": preferences.theme,
    "data-density": preferences.density,
  };
}

/** The current request's preferences. Server only (reads the request cookies). */
export async function getPreferences(): Promise<Preferences> {
  const store = await cookies();
  return parsePreferences(store.get(PREFERENCES_COOKIE)?.value);
}
