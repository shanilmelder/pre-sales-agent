import type { PillTone } from "@/components/ui/pill";

/** Maps a lib status `text-*` tone class to a Pill tone. Anything unmapped is neutral. */
export function pillToneFor(tone: string): PillTone {
  const classes = tone.split(/\s+/);
  if (classes.includes("text-resolved")) return "resolved";
  if (classes.includes("text-gap")) return "gap";
  if (classes.includes("text-blocker")) return "blocker";
  if (classes.includes("text-agent")) return "agent";
  return "neutral";
}
