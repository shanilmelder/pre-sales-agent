import { describe, expect, it } from "vitest";

import { pillToneFor } from "./pill-tone";

describe("pillToneFor", () => {
  it.each([
    ["text-resolved", "resolved"],
    ["text-gap", "gap"],
    ["text-blocker", "blocker"],
    ["text-agent", "agent"],
    ["text-muted-foreground", "neutral"],
    ["", "neutral"],
    ["something-else", "neutral"],
  ])("%s -> %s", (input, expected) => {
    expect(pillToneFor(input)).toBe(expected);
  });
});
