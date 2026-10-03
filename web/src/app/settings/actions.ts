"use server";

import { cookies } from "next/headers";

import {
  PREFERENCES_COOKIE,
  PREFERENCES_COOKIE_MAX_AGE,
  isPreferences,
  serializePreferences,
} from "@/lib/preferences";

export type SavePreferencesResult = { ok: true } | { ok: false };

/** Validates and stores the preferences cookie. Setting a cookie in a Server Action makes
 * Next.js re-render the current route, so the layout applies the new `<html>` classes. */
export async function savePreferences(input: unknown): Promise<SavePreferencesResult> {
  if (!isPreferences(input)) return { ok: false };
  const store = await cookies();
  store.set(PREFERENCES_COOKIE, serializePreferences(input), {
    path: "/",
    maxAge: PREFERENCES_COOKIE_MAX_AGE,
    sameSite: "lax",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
  });
  return { ok: true };
}
