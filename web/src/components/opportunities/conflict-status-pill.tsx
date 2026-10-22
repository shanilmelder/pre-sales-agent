import { TextSearchIcon } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import { Pill } from "@/components/ui/pill";
import { DETECTED_FROM_TEXT, statusInfo, type ConflictStatus } from "@/lib/conflicts";
import { pillToneFor } from "@/lib/pill-tone";

/** A Conflict's status: always an icon and a label, never colour alone. A tint-filled Pill
 * (blocker for Open, gap for Escalated). */
export function ConflictStatusPill({ status }: { status: ConflictStatus }) {
  const known = statusInfo(status);
  const Icon = known.icon;
  return (
    <Pill data-status={known.value} tone={pillToneFor(known.tone)} icon={<Icon />} className="shrink-0">
      {known.label}
    </Pill>
  );
}

/** Story 6.2: "Detected from text" on a Conflict the Conflict Agent found in the Findings'
 * text. An icon and a label, in the agent tone, never colour alone. */
export function DetectedFromTextTag() {
  return (
    <Chip data-testid="detected-from-text" className="shrink-0 whitespace-nowrap">
      <TextSearchIcon className="size-3 shrink-0 text-agent" aria-hidden="true" />
      {DETECTED_FROM_TEXT}
    </Chip>
  );
}
