"use client";

import { AnchorIcon, HistoryIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useShell } from "@/components/shell/shell-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Pill, type PillTone } from "@/components/ui/pill";
import {
  ALL_VERSIONS,
  BASELINE,
  longDate,
  switcherVersions,
  versionHref,
  versionStatusLabel,
  type EstimateVersion,
  type VersionListItem,
} from "@/lib/estimates";
import { cn } from "@/lib/utils";

/** Each status's state pill tone in the switcher (the mockup: Draft primary, the rest as the
 * version pill's tones). */
const STATE_TONES: Record<EstimateVersion["status"], PillTone> = {
  draft: "agent",
  submitted: "neutral",
  in_review: "gap",
  approved: "resolved",
  rejected: "blocker",
  superseded: "neutral",
};

/** A version's state pill: Baseline (green, with the anchor), else its status. */
export function VersionStatePill({
  item,
}: {
  item: Pick<VersionListItem, "status" | "is_baseline">;
}) {
  return item.is_baseline ? (
    <Pill tone="resolved" icon={<AnchorIcon />} data-state-pill="baseline">
      {BASELINE}
    </Pill>
  ) : (
    <Pill tone={STATE_TONES[item.status] ?? "neutral"} data-state-pill={item.status}>
      {versionStatusLabel(item.status)}
    </Pill>
  );
}

/** The Estimate toolbar's version switcher (Story 9.7; the mockup's segmented control): the
 * Baseline (if any) then the two most recent versions (and the selected one when it is
 * neither), each "v{n}" with its state pill; the
 * selected one is `aria-pressed`, and choosing one sets `?version={n}`. **All versions** opens
 * the full list (number, state, author, date and reason), the Baseline first; with single-key
 * shortcuts on, `v` opens it too. */
export function VersionSwitcher({
  opportunityId,
  versions,
  selected,
}: {
  opportunityId: string;
  /** Every version, the Baseline first (the API's order). */
  versions: readonly VersionListItem[];
  /** The number of the version shown. */
  selected: number;
}) {
  const router = useRouter();
  const { singleKeyShortcuts, dialog } = useShell();
  const [open, setOpen] = useState(false);
  const segments = switcherVersions(versions, selected);

  // `v` opens All versions (single-key shortcuts only; the button is always there).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "v" || event.isComposing || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!singleKeyShortcuts || dialog || isEditableTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="menu"],[role="dialog"]'))
        return;
      event.preventDefault();
      setOpen(true);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [singleKeyShortcuts, dialog]);

  function choose(version: number) {
    setOpen(false);
    router.push(versionHref(opportunityId, version), { scroll: false });
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-version-switcher="">
      <div
        role="group"
        aria-label="Estimate Versions"
        className="flex gap-0.5 rounded-[9px] bg-surface-alt p-[3px]"
      >
        {segments.map((item) => {
          const pressed = item.version === selected;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={pressed}
              data-version-segment={item.version}
              onClick={() => choose(item.version)}
              className={cn(
                "flex items-center gap-1.5 rounded-[7px] px-3 py-1 text-control outline-none focus-visible:ring-2 focus-visible:ring-primary",
                pressed
                  ? "bg-surface text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {`v${item.version}`}
              <VersionStatePill item={item} />
            </button>
          );
        })}
      </div>
      <Button
        type="button"
        variant="outline"
        className="h-auto rounded-lg border-border-strong bg-surface px-3 py-1.5 text-control"
        aria-keyshortcuts={singleKeyShortcuts ? "v" : undefined}
        onClick={() => setOpen(true)}
      >
        <HistoryIcon aria-hidden="true" />
        {ALL_VERSIONS}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[560px]">
          <DialogHeader>
            <DialogTitle>{ALL_VERSIONS}</DialogTitle>
            <DialogDescription>The Baseline first, then the newest.</DialogDescription>
          </DialogHeader>
          <ul className="flex max-h-[60vh] flex-col overflow-y-auto" data-all-versions="">
            {versions.map((item) => (
              <li key={item.id} className="border-t border-border first:border-t-0">
                <button
                  type="button"
                  aria-current={item.version === selected ? "true" : undefined}
                  onClick={() => choose(item.version)}
                  className="flex w-full flex-col gap-0.5 rounded-md px-2 py-2.5 text-left outline-none hover:bg-surface-alt focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-body-strong">{`v${item.version}`}</span>
                    <VersionStatePill item={item} />
                    <span className="text-meta text-muted-foreground">
                      {[item.created_by_name, longDate(item.created_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  {item.reason ? (
                    <span className="text-meta break-words text-foreground">{item.reason}</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </div>
  );
}
