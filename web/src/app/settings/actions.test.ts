import { beforeEach, describe, expect, it, vi } from "vitest";

const set = vi.hoisted(() => vi.fn());
vi.mock("next/headers", () => ({ cookies: async () => ({ set }) }));

import { serializePreferences, type Preferences } from "@/lib/preferences";

import { savePreferences } from "./actions";

beforeEach(() => set.mockReset());

describe("savePreferences", () => {
  it.each([
    null,
    "dark",
    {},
    { theme: "sepia", density: "compact", singleKeyShortcuts: true },
    { theme: "dark", density: "compact" },
    { theme: "dark", density: "compact", singleKeyShortcuts: "false" },
  ])("rejects %o and writes nothing", async (input) => {
    expect(await savePreferences(input)).toEqual({ ok: false });
    expect(set).not.toHaveBeenCalled();
  });

  it("writes the psa_prefs cookie for valid input", async () => {
    const input: Preferences = { theme: "dark", density: "compact", singleKeyShortcuts: false };
    expect(await savePreferences(input)).toEqual({ ok: true });
    expect(set).toHaveBeenCalledTimes(1);
    expect(set).toHaveBeenCalledWith(
      "psa_prefs",
      serializePreferences(input),
      expect.objectContaining({
        path: "/",
        httpOnly: true,
        sameSite: "lax",
        maxAge: 60 * 60 * 24 * 365,
      }),
    );
  });
});
