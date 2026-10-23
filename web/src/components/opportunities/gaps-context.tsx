"use client";

import { BookOpenIcon, ListChecksIcon, TagIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { loadChecklistVersion, type VersionResult } from "@/app/knowledge/checklists/actions";
import { ChecklistReadOnly } from "@/components/knowledge/checklist-read-only";
import { chipLayoutClassName } from "@/components/ui/chip";
import { domainLabel } from "@/lib/checklists";
import {
  APPLICABLE_CHECKLISTS,
  checklistChipLabel,
  coverageBanner,
  coverageHref,
  NO_CHECKLISTS_APPLY,
  OPEN_KNOWLEDGE_SOURCES,
  SHOW_UNTAGGED,
  untaggedBanner,
  untaggedHref,
  type GapsContext,
  type GapsContextChecklist,
} from "@/lib/gaps";

const CHECKLIST_LOADING = "Loading the Checklist…";
const CHECKLIST_FAILED = "The Checklist could not be loaded.";
const CHECKLIST_GONE = "This Checklist version is no longer available.";

/** One banner in the mockup's style: a tinted, rounded strip with an icon, the sentence and a
 * right-aligned link. Informational, so `role="status"`. */
function Banner({
  tone,
  icon,
  children,
  href,
  linkLabel,
  testId,
}: {
  tone: "gap" | "primary";
  icon: ReactNode;
  children: ReactNode;
  href: string;
  linkLabel: string;
  testId: string;
}) {
  const colours = tone === "gap" ? "bg-gap-tint text-gap" : "bg-primary-tint text-primary-text";
  return (
    <div
      role="status"
      data-testid={testId}
      className={`flex flex-wrap items-center gap-2.5 rounded-[10px] px-3.5 py-2.5 text-control font-medium ${colours}`}
    >
      <span aria-hidden="true" className="inline-flex shrink-0 [&_svg]:size-4">
        {icon}
      </span>
      <span className="min-w-0 flex-1">{children}</span>
      <Link
        href={href}
        className="ml-auto shrink-0 font-semibold underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        {linkLabel}
      </Link>
    </div>
  );
}

/** The Gaps tab context (Story 4.1), under the header row: the applicable Checklists strip
 * (a chip per Checklist opens it read-only in the right pane), the untagged-integration
 * banner and the coverage banner. */
export function GapsContextBar({
  opportunityId,
  context,
  openChecklistId,
  onOpenChecklist,
}: {
  opportunityId: string;
  context: GapsContext;
  /** The Checklist shown in the right pane, if any (its chip is pressed). */
  openChecklistId: string | null;
  /** `viaKeyboard` is true when activated with Enter or Space, not a pointer. */
  onOpenChecklist: (checklist: GapsContextChecklist, viaKeyboard: boolean) => void;
}) {
  const labelId = useId();
  const checklists = context.applicable_checklists;
  const untagged = context.untagged_integration_count;
  const coverage = coverageBanner(context.uncovered);
  return (
    <div className="flex flex-col gap-2.5" data-testid="gaps-context">
      <div className="flex flex-wrap items-center gap-2">
        <span id={labelId} className="text-label text-text-secondary">
          {APPLICABLE_CHECKLISTS}
        </span>
        {checklists.length > 0 ? (
          <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-1.5">
            {checklists.map((checklist) => {
              const pressed = checklist.checklist_id === openChecklistId;
              return (
                <button
                  key={checklist.checklist_id}
                  type="button"
                  data-checklist-chip={checklist.checklist_id}
                  aria-pressed={pressed}
                  // A keyboard-activated click has no pointer clicks (detail 0).
                  onClick={(event) => onOpenChecklist(checklist, event.detail === 0)}
                  className={`${chipLayoutClassName} text-label outline-none hover:brightness-[.97] focus-visible:ring-2 focus-visible:ring-primary ${
                    pressed
                      ? "border-primary bg-primary-tint text-primary-text"
                      : "border-border-strong bg-surface text-foreground"
                  }`}
                >
                  <ListChecksIcon aria-hidden="true" className="size-3 shrink-0" />
                  {checklistChipLabel(checklist)}
                </button>
              );
            })}
          </div>
        ) : (
          <span className="text-meta text-muted-foreground">{NO_CHECKLISTS_APPLY}</span>
        )}
      </div>
      {untagged > 0 ? (
        <Banner
          tone="gap"
          icon={<TagIcon />}
          href={untaggedHref(opportunityId)}
          linkLabel={SHOW_UNTAGGED}
          testId="untagged-banner"
        >
          {untaggedBanner(untagged)}
        </Banner>
      ) : null}
      {coverage ? (
        <Banner
          tone="primary"
          icon={<BookOpenIcon />}
          href={coverageHref(context.uncovered)}
          linkLabel={OPEN_KNOWLEDGE_SOURCES}
          testId="coverage-banner"
        >
          {coverage}
        </Banner>
      ) : null}
    </div>
  );
}

type Loaded = { key: string; result: VersionResult };

/** An applicable Checklist at its published version, read-only, in the right pane: its name,
 * "Version {n} · {domain}", then its items with their Mandatory or Optional labels. */
export function ChecklistPane({
  checklist,
  focusRequest = 0,
}: {
  checklist: GapsContextChecklist;
  /** Bump to move keyboard focus to the heading. */
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const key = `${checklist.checklist_id}:${checklist.version}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const result = loaded?.key === key ? loaded.result : null;

  useEffect(() => {
    let cancelled = false;
    loadChecklistVersion(checklist.checklist_id, checklist.version)
      .catch((): VersionResult => ({ kind: "error" }))
      .then((next) => {
        if (!cancelled) setLoaded({ key, result: next });
      });
    return () => {
      cancelled = true;
    };
  }, [checklist.checklist_id, checklist.version, key]);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section
      aria-labelledby={headingId}
      data-testid="checklist-pane"
      className="flex flex-col gap-3 p-gutter"
    >
      <div className="flex flex-col gap-0.5">
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {checklist.name}
        </h3>
        <p className="text-meta text-text-secondary">
          Version {checklist.version} · {domainLabel(checklist.domain)}
        </p>
      </div>
      {result === null ? (
        <p role="status" className="text-meta text-muted-foreground">
          {CHECKLIST_LOADING}
        </p>
      ) : result.kind === "ok" ? (
        <ChecklistReadOnly checklist={result.version} showScope={false} optionalLabels />
      ) : (
        <p role="status" className="text-meta text-destructive">
          {result.kind === "not-found" ? CHECKLIST_GONE : CHECKLIST_FAILED}
        </p>
      )}
    </section>
  );
}
