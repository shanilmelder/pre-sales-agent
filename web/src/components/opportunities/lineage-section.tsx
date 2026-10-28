"use client";

import { ExternalLinkIcon, QuoteIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";

import {
  getPassage,
  loadAssumptionLineage,
  loadLineLineage,
  type PassageResult,
} from "@/app/opportunities/actions";
import type {
  AssumptionLineageResult,
  LineLineageResult,
} from "@/app/opportunities/data";
import { PaneLabel } from "@/components/opportunities/estimate-item-parts";
import { PassageView } from "@/components/opportunities/requirement-inspector";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  actorAndDate,
  deltaText,
  findingSource,
  hours,
  LINE_LINEAGE_SECTIONS,
  LINEAGE,
  LINEAGE_FAILED,
  lineTraceHref,
  LOADING_LINEAGE,
  NOTHING_RECORDED,
  OPEN_IN_TRACE,
  SUPERSEDED,
  type AssumptionLineage,
  type LineageEvidence,
  type LineageFinding,
  type LineageStep,
  type LineLineage,
} from "@/lib/estimates";
import type { Passage } from "@/lib/requirements";
import { useSkeletonDone } from "@/lib/use-skeleton-done";
import { cn } from "@/lib/utils";

/** A lineage sub-section's eyebrow heading (one level under "Lineage"). */
function SectionLabel({ children }: { children: ReactNode }) {
  return <h5 className="text-eyebrow text-muted-foreground uppercase">{children}</h5>;
}

/** Struck-through text plus a "superseded" label (never colour alone), or the text. */
export function MaybeSuperseded({
  superseded,
  children,
}: {
  superseded: boolean;
  children: ReactNode;
}) {
  if (!superseded) return <>{children}</>;
  return (
    <>
      <s>{children}</s>
      <span data-superseded="" className="text-meta text-muted-foreground">{` (${SUPERSEDED})`}</span>
    </>
  );
}

/** The mockup's Evidence chip: the primary tint, radius 6, 2×8 padding, an 11px quote icon
 * and the label. A button: it opens the cited version (a superseded one is struck through
 * and labelled, and still opens). */
export function LineageChip({
  evidence,
  pressed,
  onSelect,
}: {
  evidence: Pick<LineageEvidence, "label" | "superseded" | "version" | "kind">;
  pressed: boolean;
  onSelect: () => void;
}) {
  const cited =
    evidence.kind === "requirement" && evidence.version != null ? ` v${evidence.version}` : "";
  return (
    <button
      type="button"
      aria-pressed={pressed}
      data-lineage-chip=""
      onClick={onSelect}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-[6px] bg-primary-tint px-2 py-0.5 text-label text-primary-text outline-none hover:brightness-[.97] focus-visible:ring-2 focus-visible:ring-primary",
        pressed && "ring-1 ring-primary",
      )}
    >
      <QuoteIcon aria-hidden="true" className="size-[11px] shrink-0" />
      <span className="truncate">
        <MaybeSuperseded superseded={evidence.superseded}>{`${evidence.label}${cited}`}</MaybeSuperseded>
      </span>
    </button>
  );
}

/** A Requirement version as a passage (its text, labelled with the cited version). */
function requirementPassage(evidence: LineageEvidence, text: string): Passage {
  return {
    passage_id: `${evidence.id}:${evidence.version ?? 0}`,
    source_id: evidence.id,
    source_version: evidence.version ?? 1,
    filename: evidence.label,
    label: evidence.label,
    before: "",
    text,
    after: "",
  };
}

/** A row of Evidence chips; the chosen one shows the cited Requirement version's text in a
 * `PassageView` under them. */
export function EvidenceChips({
  evidence,
  texts,
}: {
  evidence: readonly LineageEvidence[];
  /** The full text of a Requirement version by `{id}:{version}` (else its excerpt shows). */
  texts?: ReadonlyMap<string, string>;
}) {
  const [open, setOpen] = useState<number | null>(null);
  if (evidence.length === 0) return null;
  const shown = open === null ? null : evidence[open];
  return (
    <div className="flex flex-col gap-1.5">
      <span className="flex flex-wrap gap-1">
        {evidence.map((item, i) => (
          <LineageChip
            key={`${item.kind}-${item.id}-${item.version}`}
            evidence={item}
            pressed={open === i}
            onSelect={() => setOpen((current) => (current === i ? null : i))}
          />
        ))}
      </span>
      {shown ? (
        <div className="rounded-md border border-border bg-background p-2" data-cited-version="">
          <PassageView
            passage={requirementPassage(
              shown,
              texts?.get(`${shown.id}:${shown.version}`) ?? shown.excerpt,
            )}
          />
        </div>
      ) : null}
    </div>
  );
}

function Empty() {
  return <p className="text-meta text-muted-foreground">{NOTHING_RECORDED}</p>;
}

function Meta({ children }: { children: ReactNode }) {
  return <p className="text-meta text-muted-foreground">{children}</p>;
}

/** A finding or effort entry; its source opens a summary of that Assessment version. */
function FindingItem({ finding, texts }: { finding: LineageFinding; texts: ReadonlyMap<string, string> }) {
  const [summary, setSummary] = useState(false);
  return (
    <li className="flex flex-col gap-1" data-lineage-finding={finding.entry}>
      <button
        type="button"
        aria-expanded={summary}
        onClick={() => setSummary((v) => !v)}
        className="w-fit rounded-sm text-left text-meta text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        <MaybeSuperseded superseded={finding.superseded}>{findingSource(finding)}</MaybeSuperseded>
      </button>
      <p className="text-body break-words">
        {finding.title}
        {finding.hours != null ? (
          <span className="text-muted-foreground text-numeric">{` · ${hours(finding.hours)} h`}</span>
        ) : null}
      </p>
      {summary ? (
        <dl
          className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 rounded-md border border-border bg-background p-2 text-meta"
          data-assessment-summary=""
        >
          <dt className="text-muted-foreground">{finding.entry === "effort" ? "Basis" : "Detail"}</dt>
          <dd className="break-words">{finding.detail || "–"}</dd>
          {finding.severity ? (
            <>
              <dt className="text-muted-foreground">Severity</dt>
              <dd className="capitalize">{finding.severity}</dd>
            </>
          ) : null}
          {finding.status ? (
            <>
              <dt className="text-muted-foreground">Status</dt>
              <dd className="capitalize">{finding.status}</dd>
            </>
          ) : null}
          {finding.created_at ? (
            <>
              <dt className="text-muted-foreground">Recorded</dt>
              <dd>{actorAndDate(null, finding.created_at)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
      <EvidenceChips evidence={finding.evidence} texts={texts} />
    </li>
  );
}

function LineLineageBody({ lineage }: { lineage: LineLineage }) {
  const texts = new Map(lineage.requirements.map((r) => [`${r.id}:${r.version}`, r.text]));
  const sections: Record<(typeof LINE_LINEAGE_SECTIONS)[number]["key"], ReactNode> = {
    requirements:
      lineage.requirements.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-2">
          {lineage.requirements.map((r) => (
            <li key={`${r.id}-${r.version}`} className="flex flex-col gap-1" data-lineage-requirement="">
              <EvidenceChips evidence={r.evidence} texts={texts} />
              <p className="text-body break-words">
                <MaybeSuperseded superseded={r.superseded}>{r.text}</MaybeSuperseded>
              </p>
            </li>
          ))}
        </ul>
      ),
    findings:
      lineage.findings.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-3">
          {lineage.findings.map((f) => (
            <FindingItem key={`${f.entry}-${f.id}`} finding={f} texts={texts} />
          ))}
        </ul>
      ),
    decisions:
      lineage.decisions.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-2">
          {lineage.decisions.map((d) => (
            <li key={`${d.kind}-${d.subject_id}-${d.at}`} className="flex flex-col gap-0.5" data-lineage-decision={d.kind}>
              <p className="text-body-strong break-words">
                <MaybeSuperseded superseded={d.superseded}>{d.title}</MaybeSuperseded>
              </p>
              {d.reason ? <p className="text-body break-words">{d.reason}</p> : null}
              <Meta>{actorAndDate(d.actor, d.at)}</Meta>
            </li>
          ))}
        </ul>
      ),
    assumptions:
      lineage.assumptions.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-2">
          {lineage.assumptions.map((a) => (
            <li key={a.id} className="flex flex-col gap-0.5" data-lineage-assumption="">
              <p className="text-body break-words">
                {`A${a.position}`}
                {a.amount_hours != null ? ` · ${hours(a.amount_hours)} h` : ""}
                {` · ${a.wording}`}
              </p>
              <Meta>
                {a.accepted_by_name
                  ? `Accepted · ${actorAndDate({ name: a.accepted_by_name }, a.accepted_at)}`
                  : "Not accepted"}
              </Meta>
            </li>
          ))}
        </ul>
      ),
    edits:
      lineage.edits.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-2">
          {lineage.edits.map((e) => (
            <li key={`${e.line_id}-${e.at}`} className="flex flex-col gap-0.5" data-lineage-edit="">
              <p className="text-body text-numeric">
                <MaybeSuperseded superseded={e.superseded}>
                  {`v${e.version}: ${hours(e.before_hours)} h → ${hours(e.after_hours)} h (${deltaText(e.after_hours - e.before_hours)})`}
                </MaybeSuperseded>
              </p>
              {e.reason ? <p className="text-body break-words">{e.reason}</p> : null}
              <Meta>{actorAndDate(e.actor, e.at)}</Meta>
            </li>
          ))}
        </ul>
      ),
    reviews:
      lineage.reviews.length === 0 ? (
        <Empty />
      ) : (
        <ul className="flex flex-col gap-2">
          {lineage.reviews.map((r) => (
            <li key={`${r.kind}-${r.id}`} className="flex flex-col gap-0.5" data-lineage-review={r.kind}>
              <p className="text-body-strong">
                <MaybeSuperseded superseded={r.superseded}>{r.label}</MaybeSuperseded>
              </p>
              {r.reason ? <p className="text-body break-words">{r.reason}</p> : null}
              <Meta>{actorAndDate(r.actor, r.at)}</Meta>
            </li>
          ))}
        </ul>
      ),
  };
  return (
    <>
      {LINE_LINEAGE_SECTIONS.map((section) => (
        <div key={section.key} className="flex flex-col gap-1.5" data-lineage-section={section.key}>
          <SectionLabel>{section.label}</SectionLabel>
          {sections[section.key]}
        </div>
      ))}
    </>
  );
}

function LoadingLineage() {
  return (
    <div aria-busy="true" className="flex flex-col gap-2" data-lineage-loading="">
      <p className="sr-only">{LOADING_LINEAGE}</p>
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}

/** Scroll to and focus `ref` when the monotonic `request` goes up past both the last value
 * seen here and `handled` (a request already acted on, e.g. before a remount); `onFocused`
 * reports the value acted on. */
function useFocusRequest(
  ref: RefObject<HTMLElement | null>,
  request: number,
  handled = 0,
  onFocused?: (request: number) => void,
) {
  const last = useRef(0);
  const report = useRef(onFocused);
  useEffect(() => {
    report.current = onFocused;
  }, [onFocused]);
  useEffect(() => {
    const fresh = request > last.current && request > handled;
    last.current = Math.max(last.current, request);
    if (!fresh) return;
    const el = ref.current;
    el?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    el?.focus();
    report.current?.(request);
  }, [ref, request, handled]);
}

/** Story 9.9: the **Lineage** section of the Estimate line inspector: the line's
 * Requirements, Findings and effort entries with Evidence chips, decisions, Contingencies,
 * edits and reviews (in that order, "Nothing recorded." when empty), and **Open in Trace**
 * to the line's trace events. A skeleton shows for at least 150 ms while it loads.
 * `focusRequest` (**Trace**) or `externalFocusRequest` (`t` on a grid row; not past
 * `externalFocusHandled`) going up scrolls to and focuses its heading. `reloadKey` changing
 * (e.g. after the line is edited) reads the lineage again. */
export function LineLineageSection({
  opportunityId,
  lineId,
  focusRequest = 0,
  externalFocusRequest = 0,
  externalFocusHandled = 0,
  onExternalFocus,
  reloadKey = "",
}: {
  opportunityId: string;
  lineId: string;
  focusRequest?: number;
  externalFocusRequest?: number;
  externalFocusHandled?: number;
  onExternalFocus?: (request: number) => void;
  reloadKey?: string;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const skeletonDone = useSkeletonDone();
  const [loaded, setLoaded] = useState<{ lineId: string; result: LineLineageResult } | null>(
    null,
  );
  useFocusRequest(headingRef, focusRequest);
  useFocusRequest(headingRef, externalFocusRequest, externalFocusHandled, onExternalFocus);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let result: LineLineageResult;
      try {
        result = await loadLineLineage(opportunityId, lineId);
      } catch {
        result = { kind: "error" };
      }
      if (!cancelled) setLoaded({ lineId, result });
    })();
    return () => {
      cancelled = true;
    };
  }, [opportunityId, lineId, reloadKey]);

  const result = loaded?.lineId === lineId ? loaded.result : null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3" data-lineage="line">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PaneLabel>
          <span
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {LINEAGE}
          </span>
        </PaneLabel>
        <Link
          href={lineTraceHref(opportunityId, lineId)}
          data-open-in-trace=""
          className={`${buttonVariants({ variant: "outline", size: "sm" })} text-control`}
        >
          <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
          {OPEN_IN_TRACE}
        </Link>
      </div>
      {!result || !skeletonDone ? (
        <LoadingLineage />
      ) : result.kind === "ok" ? (
        <LineLineageBody lineage={result.lineage} />
      ) : (
        <p className="text-meta text-muted-foreground">{LINEAGE_FAILED}</p>
      )}
    </section>
  );
}

const STEP_LABELS: Record<LineageStep["kind"], string> = {
  gap: "Gap",
  unknown: "Unknown",
  finding: "Finding",
  question: "Clarification Question",
  answer: "Answer",
  conversion: "Conversion",
  acceptance: "Acceptance",
  actual: "Actual",
};

/** Evidence chips as the chain shows them: a Source passage chip loads its passage, a
 * Requirement chip shows the cited version's text (Story 10.4: also the failed Assumptions'
 * Evidence in the Actuals Inspector). */
export function EvidenceList({
  opportunityId,
  evidence,
}: {
  opportunityId: string;
  evidence: readonly LineageEvidence[];
}) {
  return (
    <>
      {evidence.map((item) =>
        item.kind === "source_document" ? (
          <PassageChip
            key={`${item.id}-${item.passage_id}`}
            opportunityId={opportunityId}
            evidence={item}
          />
        ) : (
          <EvidenceChips key={`${item.id}-${item.version}`} evidence={[item]} />
        ),
      )}
    </>
  );
}

/** The answer step's Source passage chip: it loads and shows the passage. */
export function PassageChip({
  opportunityId,
  evidence,
}: {
  opportunityId: string;
  evidence: LineageEvidence;
}) {
  const [open, setOpen] = useState(false);
  const [passage, setPassage] = useState<PassageResult | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || passage?.kind === "ok" || !evidence.passage_id) return;
    try {
      setPassage(await getPassage(opportunityId, evidence.passage_id));
    } catch {
      setPassage({ kind: "error" });
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span>
        <LineageChip evidence={evidence} pressed={open} onSelect={() => void toggle()} />
      </span>
      {open ? (
        <div className="rounded-md border border-border bg-background p-2" data-cited-passage="">
          {passage === null ? (
            <p className="text-meta text-muted-foreground">Loading passage</p>
          ) : passage.kind === "ok" ? (
            <PassageView passage={passage.passage} />
          ) : (
            <p className="text-meta break-words">{evidence.excerpt || "The passage could not be loaded."}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** The Assumption's chain of origin as a vertical list (Story 10.4: also the Trace tab's
 * Chain card): origin, question, answer, conversion, acceptance, then each Actual that
 * recorded it as failed. */
export function AssumptionLineageBody({
  opportunityId,
  lineage,
}: {
  opportunityId: string;
  lineage: AssumptionLineage;
}) {
  if (lineage.steps.length === 0) return <Empty />;
  return (
    <ol className="flex flex-col" aria-label="Chain of origin">
      {lineage.steps.map((step, i) => {
        const last = i === lineage.steps.length - 1;
        return (
          <li key={`${step.kind}-${step.id}`} className="flex gap-3" data-lineage-step={step.kind}>
            <span aria-hidden="true" className="flex flex-col items-center">
              <span className="mt-1 size-2.5 shrink-0 rounded-full border-2 border-primary bg-primary-tint" />
              {last ? null : <span className="w-0.5 flex-1 bg-border" />}
            </span>
            <div className={cn("flex min-w-0 flex-1 flex-col gap-1", !last && "pb-3")}>
              <SectionLabel>{STEP_LABELS[step.kind]}</SectionLabel>
              <p className="text-body break-words">
                <MaybeSuperseded superseded={step.superseded}>{step.title}</MaybeSuperseded>
              </p>
              {step.detail ? <Meta>{step.detail}</Meta> : null}
              {step.actor || step.at ? <Meta>{actorAndDate(step.actor, step.at)}</Meta> : null}
              <EvidenceList opportunityId={opportunityId} evidence={step.evidence ?? []} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Story 9.9: the **Lineage** section of the Assumption inspector, as a vertical chain: its
 * origin (Gap, Unknown or Finding), the Clarification Question, the recorded answer with its
 * Source passage, the conversion and the acceptance (Story 10.4: then each Actual that
 * recorded it as failed). A step that never happened is left out.
 * A skeleton shows for at least 150 ms while it loads. */
export function AssumptionLineageSection({
  opportunityId,
  assumptionId,
}: {
  opportunityId: string;
  assumptionId: string;
}) {
  const headingId = useId();
  const skeletonDone = useSkeletonDone();
  const [loaded, setLoaded] = useState<{ id: string; result: AssumptionLineageResult } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let result: AssumptionLineageResult;
      try {
        result = await loadAssumptionLineage(opportunityId, assumptionId);
      } catch {
        result = { kind: "error" };
      }
      if (!cancelled) setLoaded({ id: assumptionId, result });
    })();
    return () => {
      cancelled = true;
    };
  }, [opportunityId, assumptionId]);

  const result = loaded?.id === assumptionId ? loaded.result : null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3" data-lineage="assumption">
      <PaneLabel>
        <span id={headingId}>{LINEAGE}</span>
      </PaneLabel>
      {!result || !skeletonDone ? (
        <LoadingLineage />
      ) : result.kind === "ok" ? (
        <AssumptionLineageBody opportunityId={opportunityId} lineage={result.lineage} />
      ) : (
        <p className="text-meta text-muted-foreground">{LINEAGE_FAILED}</p>
      )}
    </section>
  );
}
