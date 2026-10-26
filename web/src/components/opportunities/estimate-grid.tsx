"use client";

import {
  CheckIcon,
  CircleAlertIcon,
  LoaderCircleIcon,
  PencilIcon,
  TriangleAlertIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  acceptAssumption,
  editAssumption,
  editEstimateLine,
  editRisk,
  loadEstimate,
  loadReviewRequests,
  type AssumptionAcceptResult,
  type EstimateItemEditResult,
  type EstimateLineEditResult,
} from "@/app/opportunities/actions";
import {
  AssumptionInspector,
  type AssumptionFields,
} from "@/components/opportunities/assumption-inspector";
import {
  acceptFailure,
  AssumptionsRegister,
  OriginGapInspector,
} from "@/components/opportunities/assumptions-register";
import { RequestReviewDialog } from "@/components/opportunities/request-review-dialog";
import { ReviewPanelLoader } from "@/components/opportunities/review-panel";
import {
  linkedReview,
  ReviewRequestsCard,
} from "@/components/opportunities/review-requests-card";
import { RiskInspector, type RiskFields } from "@/components/opportunities/risk-inspector";
import { RisksCard } from "@/components/opportunities/risks-card";
import { Card } from "@/components/ui/card";
import { submittedBanner } from "@/lib/submission";
import { Chip } from "@/components/ui/chip";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { Pill, pillVariants } from "@/components/ui/pill";
import { EstimateExport } from "@/components/opportunities/estimate-export";
import { EstimateInspector, RoleMixBar } from "@/components/opportunities/estimate-inspector";
import type { EditOutcome, LineChange } from "@/components/opportunities/estimate-line-edit";
import { useAnnounce } from "@/components/shell/live-region";
import { RIGHT_PANE_TOGGLE_ID, RightPaneContent, useShell } from "@/components/shell/shell-context";
import {
  BUILDING,
  REBUILDING,
  COLUMNS,
  DRAFT_POLL_LIMIT_MS,
  DRAFT_POLL_MS,
  EDIT_NOT_ALLOWED,
  EDIT_SAVE_FAILED,
  editedLabel,
  footerRoleLabel,
  fromRunLabel,
  hours,
  isDrafting,
  isSent,
  isProposing,
  lifecycleSteps,
  NO_ESTIMATE,
  NO_ESTIMATE_BODY,
  NO_ESTIMATE_TITLE,
  RUN_ASSESSMENT,
  NEW_VERSION_ARRIVED,
  OPEN_CONFLICT,
  roleMixLabel,
  sectionLabel,
  STILL_BUILDING,
  UNALLOCATED_CONTINGENCY,
  uncarriedEditsNote,
  uncoveredBanner,
  acceptedLabel,
  assumptionId,
  ITEM_GONE,
  registerSummary,
  riskId,
  staleMessage,
  VERSION_REPLACED,
  versionLabel,
  versionNote,
  versionPillLabel,
  versionTag,
  type Assumption,
  type EstimateLine,
  type EstimateVersion,
  type EstimateView,
  type Risk,
  type Totals,
} from "@/lib/estimates";
import { useReviewEvents } from "@/lib/opportunity-events";
import { NO_ACCESS_TO_OPPORTUNITY, UUID_RE } from "@/lib/opportunities";
import type { ReviewRequest, ReviewRequestsView } from "@/lib/reviews";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

export type { EditOutcome, LineChange } from "@/components/opportunities/estimate-line-edit";

const num = "px-2.5 text-right text-numeric whitespace-nowrap";
/** The left rule that sets the Contingency column apart. */
const cont = "border-l border-border";
const headCell = "h-[34px] bg-background px-2.5 text-label text-muted-foreground whitespace-nowrap";

/** Each version status's pill tone (Story 9.1: `submitted` neutral, `in_review` gap; Story
 * 9.3: `approved` resolved, `rejected` blocker). */
const VERSION_TONES: Record<
  EstimateVersion["status"],
  "agent" | "neutral" | "gap" | "resolved" | "blocker"
> = {
  draft: "agent",
  submitted: "neutral",
  in_review: "gap",
  approved: "resolved",
  rejected: "blocker",
  superseded: "neutral",
};

/** The version pill: "v3 · Draft" (primary tint), "v3 · In review" (gap) or "v2 · Superseded"
 * (neutral). */
export function VersionPill({
  version,
}: {
  version: Pick<EstimateVersion, "status" | "version">;
}) {
  return (
    <Pill
      tone={VERSION_TONES[version.status] ?? "neutral"}
      data-version-pill=""
      className="shrink-0"
    >
      {versionTag(version)}
    </Pill>
  );
}

/** The Covers cell: one chip per Requirement the line covers. */
export function CoversChips({ line }: { line: Pick<EstimateLine, "requirements"> }) {
  if (line.requirements.length === 0) {
    return (
      <>
        <span aria-hidden="true">–</span>
        <span className="sr-only">None</span>
      </>
    );
  }
  return (
    <span className="flex flex-wrap gap-1" data-covers="">
      {line.requirements.map((requirement) => (
        <Chip key={requirement.id} className="px-1.5 py-0">
          {requirement.label}
        </Chip>
      ))}
    </span>
  );
}

function TotalsCells({ totals, className }: { totals: Totals; className?: string }) {
  return (
    <>
      <td className={cn(num, className)}>{hours(totals.effort_hours)}</td>
      <td className={cn(num, cont, className)}>{hours(totals.contingency_hours)}</td>
      <td className={cn(num, "font-semibold", className)}>{hours(totals.total_hours)}</td>
    </>
  );
}

/** The "Edited" pill: a pencil plus its label ("Edited, carried from v2"), never the icon
 * alone. */
export function EditedMarker({ line }: { line: EstimateLine }) {
  const label = editedLabel(line);
  if (!label) return null;
  return (
    <Pill tone="neutral" data-edited="" icon={<PencilIcon />} className="shrink-0">
      {label}
    </Pill>
  );
}

/** The "Open Conflict" pill (Story 8.3): an alert icon plus its label in blocker colours,
 * never the icon alone; it links to the Conflicts tab. */
export function ConflictMarker({
  line,
  opportunityId,
}: {
  line: EstimateLine;
  opportunityId?: string;
}) {
  if (line.conflicts.length === 0) return null;
  const content = (
    <>
      <CircleAlertIcon aria-hidden="true" />
      {OPEN_CONFLICT}
    </>
  );
  const className = `${cn(pillVariants({ tone: "blocker" }), "shrink-0")} text-label`;
  return opportunityId ? (
    <Link
      href={tabHref(opportunityId, "conflicts")}
      data-conflict-marker=""
      tabIndex={-1}
      aria-label={`${OPEN_CONFLICT} on ${line.title}: open the Conflicts tab`}
      className={`${className} outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary`}
    >
      {content}
    </Link>
  ) : (
    <span data-conflict-marker="" className={className}>
      {content}
    </span>
  );
}

/** The Estimate Version as a dense grid in a card: lines grouped by section in template
 * order, each section closed by its subtotal row; a sticky header and a sticky totals row
 * ("Total · v3 · Engineer 24.5 h · PM 8.2 h · QA 8.3 h"). Each line shows its title with an
 * "Open Conflict" and an "Edited" pill, one chip per covered Requirement, its role mix as a
 * bar over "E 60 · PM 20 · QA 20", and its hours. A line with an open Conflict is tinted red
 * with a red left edge; the selected line is tinted primary (selection wins). Numbers are
 * right-aligned tabular figures from the server; the Contingency column has a left rule. The
 * grid is read-only: lines are edited in the inspector.
 *
 * The lines are one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first line); j/k (with single-key shortcuts on) or the arrow keys move between lines, and
 * Enter, Space or a click opens the line. With `canEdit`, `e` on a focused line opens it with
 * focus in the inspector's "Edit line" form. */
export function EstimateGrid({
  version,
  selectedId = null,
  onOpen,
  canEdit = false,
  opportunityId,
}: {
  version: EstimateVersion;
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter, Space or `e`, not a pointer; `edit` when
   * opened with `e`. */
  onOpen?: (line: EstimateLine, viaKeyboard: boolean, edit?: boolean) => void;
  canEdit?: boolean;
  /** For the Conflicts tab links. */
  opportunityId?: string;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const lines = version.sections.flatMap((section) => section.lines);
  const editable = canEdit && version.status === "draft";
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && lines.some((l) => l.id === id)) ??
    lines[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target as HTMLElement;
    if (
      editable &&
      singleKeyShortcuts &&
      event.key === "e" &&
      target.matches("button[data-line-row]")
    ) {
      const line = lines.find((l) => l.id === target.dataset.lineId);
      if (line) {
        event.preventDefault();
        onOpen?.(line, true, true);
      }
      return;
    }
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-line-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    if (index === -1) return;
    const next = Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  const cell = "border-b border-border";
  return (
    <Card ref={container} onKeyDown={onKeyDown} className="overflow-hidden" data-estimate-grid="">
      <div className="max-h-[70vh] overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-body">
          <caption className="sr-only">{`Estimate ${versionLabel(version)}`}</caption>
          <thead className="sticky top-0 z-10 bg-background">
            <tr>
              {COLUMNS.map((column, i) => (
                <th
                  key={column}
                  scope="col"
                  className={cn(
                    headCell,
                    "border-b border-border",
                    i >= 3 ? "text-right" : "text-left",
                    i === 0 && "pl-4",
                    i === 4 && cont,
                  )}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          {version.sections.map((section) => (
            <tbody key={section.section} data-section={section.section}>
              <tr>
                <th
                  scope="rowgroup"
                  colSpan={COLUMNS.length}
                  className="h-8 border-b border-border bg-background px-4 text-left text-muted-foreground uppercase"
                >
                  <span className="text-eyebrow">{sectionLabel(section.section)}</span>
                </th>
              </tr>
              {section.lines.map((line) => {
                const selected = line.id === selectedId;
                const conflicted = line.conflicts.length > 0;
                return (
                  <tr
                    key={line.id}
                    aria-selected={selected}
                    data-conflict-row={conflicted ? "" : undefined}
                    className={cn(
                      selected
                        ? "bg-primary-tint"
                        : conflicted
                          ? "bg-blocker-tint"
                          : "hover:bg-muted/60",
                    )}
                  >
                    <th
                      scope="row"
                      className={cn(
                        cell,
                        "max-w-0 py-2 pr-2.5 pl-2.5 text-left font-normal",
                        selected
                          ? "shadow-[inset_3px_0_0_var(--primary)]"
                          : conflicted && "shadow-[inset_3px_0_0_var(--blocker)]",
                      )}
                    >
                      <div className="flex min-w-0 flex-col items-start gap-1">
                        <button
                          type="button"
                          data-line-row=""
                          data-line-id={line.id}
                          tabIndex={line.id === tabStopId ? 0 : -1}
                          onFocus={() => setFocusedId(line.id)}
                          // A keyboard-activated click has no pointer clicks (detail 0).
                          onClick={(event) => onOpen?.(line, event.detail === 0)}
                          className="block max-w-full min-w-0 truncate rounded-sm px-1.5 text-left text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          {line.title}
                        </button>
                        {conflicted || line.edited ? (
                          <div className="flex flex-wrap items-center gap-1.5 px-1.5">
                            <ConflictMarker line={line} opportunityId={opportunityId} />
                            <EditedMarker line={line} />
                          </div>
                        ) : null}
                      </div>
                    </th>
                    <td className={cn(cell, "w-36 px-2.5 py-2")}>
                      <CoversChips line={line} />
                    </td>
                    <td className={cn(cell, "w-40 px-2.5 py-2")}>
                      <div className="flex flex-col gap-1">
                        <RoleMixBar mix={line.role_mix} />
                        <span className="text-meta whitespace-nowrap text-muted-foreground [font-variant-numeric:tabular-nums]">
                          {roleMixLabel(line.role_mix)}
                        </span>
                      </div>
                    </td>
                    <td className={cn(num, cell, "w-24")}>{hours(line.effort_hours)}</td>
                    <td className={cn(num, cont, cell, "w-24")}>
                      {hours(line.contingency_hours)}
                    </td>
                    <td className={cn(num, cell, "w-24 font-semibold")}>
                      {hours(line.total_hours)}
                    </td>
                  </tr>
                );
              })}
              <tr data-subtotal="" className="h-8 bg-background text-muted-foreground">
                <th scope="row" colSpan={3} className={cn(cell, "px-4 text-left")}>
                  <span className="text-label">{`${sectionLabel(section.section)} subtotal`}</span>
                </th>
                <TotalsCells totals={section.subtotal} className={cell} />
              </tr>
            </tbody>
          ))}
          {version.unallocated_contingency_hours > 0 ? (
            <tbody data-unallocated="">
              <tr className="h-row">
                <th
                  scope="row"
                  colSpan={3}
                  className={cn(cell, "px-4 text-left text-body font-normal")}
                >
                  {UNALLOCATED_CONTINGENCY}
                </th>
                <td className={cn(num, cell, "text-muted-foreground")}>
                  <span aria-hidden="true">–</span>
                  <span className="sr-only">None</span>
                </td>
                <td className={cn(num, cont, cell)}>
                  {hours(version.unallocated_contingency_hours)}
                </td>
                <td className={cn(num, cell, "font-semibold")}>
                  {hours(version.unallocated_contingency_hours)}
                </td>
              </tr>
            </tbody>
          ) : null}
          <tfoot className="sticky bottom-0 z-10 bg-background">
            <tr data-totals="" className="h-row">
              <th scope="row" colSpan={3} className="border-t border-border px-4 text-left">
                <span className="text-body-strong">{`Total · v${version.version}`}</span>
                <span
                  data-role-totals=""
                  className="text-label text-muted-foreground [font-variant-numeric:tabular-nums]"
                >
                  {` · ${footerRoleLabel(version.totals)}`}
                </span>
              </th>
              <td className={cn(num, "border-t border-border font-semibold")}>
                {hours(version.totals.effort_hours)}
              </td>
              <td className={cn(num, cont, "border-t border-border font-semibold")}>
                {hours(version.totals.contingency_hours)}
              </td>
              <td className={cn(num, "border-t border-border font-semibold text-primary-text")}>
                {hours(version.totals.total_hours)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

/** The toolbar above the Estimate: the version pill ("v3 · Draft"), "From Assessments (run
 * 2)" when the version names its run, and **Export** (Story 8.8) at the right when the caller
 * may export it. Under it, before the first version while an assessment run is queued or
 * running (Story 8.3), "The Estimate is built when the Engineering, PM and Security Agents
 * finish." with a running dot ("Still waiting for the agents — reload to check." once polling
 * has stopped); with a version shown, "Rebuilding from the Assessments when the run
 * finishes." in muted text with the running dot. There is no draft Retry: the Estimate is
 * built from the Assessments. */
export function EstimateHeader({
  version,
  assessmentRunning = false,
  opportunityId,
  canExport = false,
  stalled = false,
  actions,
}: {
  version: EstimateVersion | null;
  /** An assessment run is queued or running. */
  assessmentRunning?: boolean;
  /** Needed for **Export**; without it the control is hidden. */
  opportunityId?: string;
  canExport?: boolean;
  /** Polling has stopped while still waiting. */
  stalled?: boolean;
  /** Story 9.1: more toolbar actions after Export (**Request review**). */
  actions?: ReactNode;
}) {
  const waiting = !version && assessmentRunning;
  const rebuilding = version !== null && assessmentRunning;
  if (!version && !waiting) return null;
  const fromRun = version ? fromRunLabel(version) : null;
  return (
    <div className="flex flex-col items-stretch gap-1.5">
      {version ? (
        <div className="flex flex-wrap items-center gap-3" data-estimate-toolbar="">
          <VersionPill version={version} />
          {fromRun ? <p className="text-meta text-muted-foreground">{fromRun}</p> : null}
          <span className="flex-1" aria-hidden="true" />
          {canExport && opportunityId ? <EstimateExport opportunityId={opportunityId} /> : null}
          {actions}
        </div>
      ) : null}
      {waiting && stalled ? (
        <p className="text-label text-muted-foreground">{STILL_BUILDING}</p>
      ) : waiting ? (
        <p className="flex items-center gap-2 text-label" data-status="waiting">
          <LoaderCircleIcon
            aria-hidden="true"
            data-testid="running-dot"
            className="size-3 shrink-0 text-agent"
          />
          {BUILDING}
        </p>
      ) : rebuilding && !stalled ? (
        <p
          className="flex items-center gap-2 text-label text-muted-foreground"
          data-status="rebuilding"
        >
          <LoaderCircleIcon
            aria-hidden="true"
            data-testid="running-dot"
            className="size-3 shrink-0 text-agent"
          />
          {REBUILDING}
        </p>
      ) : null}
    </div>
  );
}

/** The Version lifecycle card: the mockup's Draft → In review → Approved → Baseline stepper
 * (done steps green with a check, the current one primary-tinted with a primary ring and a
 * 600-weight label, the rest grey), a note on what the version is, and the note on edits a
 * new version could not carry. */
export function VersionLifecycle({ version }: { version: EstimateVersion }) {
  const steps = lifecycleSteps(version.status);
  return (
    <Card className="gap-3 px-5 py-4" data-lifecycle="">
      <h3 className="text-muted-foreground uppercase">
        <span className="text-eyebrow">Version lifecycle</span>
      </h3>
      <ol aria-label="Version lifecycle" className="flex items-center">
        {steps.map((step, i) => {
          return (
            <li
              key={step.label}
              aria-current={step.state === "current" ? "step" : undefined}
              data-step-state={step.state}
              className={cn("flex items-center", i < steps.length - 1 && "flex-1")}
            >
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full border-2",
                    step.state === "passed"
                      ? "border-resolved bg-resolved text-resolved-foreground"
                      : step.state === "current"
                        ? "border-primary bg-primary-tint text-primary-text ring-2 ring-primary/30"
                        : "border-border-strong bg-neutral-tint text-neutral",
                  )}
                >
                  {step.state === "passed" ? (
                    <CheckIcon className="size-3.5" />
                  ) : (
                    <span className="text-label">{i + 1}</span>
                  )}
                </span>
                <span
                  className={cn(
                    "whitespace-nowrap",
                    step.state === "current" ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  <span
                    className={cn("text-body", step.state === "current" && "font-semibold")}
                  >
                    {step.label}
                  </span>
                  {step.state === "passed" ? <span className="sr-only"> (done)</span> : null}
                </span>
              </span>
              {i < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={cn(
                    "mx-3 h-0.5 min-w-6 flex-1 rounded-full",
                    step.state === "passed" ? "bg-resolved" : "bg-border",
                  )}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
      <p className="text-meta text-muted-foreground">{versionNote(version)}</p>
      {version.uncarried_edit_count > 0 ? (
        <p className="flex items-center gap-1.5 text-label text-foreground" data-uncarried="">
          <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0 text-gap" />
          {uncarriedEditsNote(version.uncarried_edit_count, version.uncarried_edits_from_version)}
        </p>
      ) : null}
    </Card>
  );
}

/** The amber banner for Requirements no Estimate line covers; nothing when all are covered. */
export function UncoveredBanner({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <p
      data-uncovered=""
      className="flex items-center gap-2 rounded-lg border border-gap/30 bg-gap-tint px-4 py-2.5 text-gap"
    >
      <TriangleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
      <span className="text-body-strong">{uncoveredBanner(count)}</span>
    </p>
  );
}

/** What the right pane shows: a line, an Assumption (Story 8.5), a Risk (Story 8.5), the
 * Gap an Assumption or a Risk was made from, or a Review Request's review panel (Story 9.3). */
type Selection =
  | { kind: "review"; id: string }
  | { kind: "line"; id: string }
  | { kind: "assumption"; id: string }
  | { kind: "risk"; id: string }
  | { kind: "gap"; assumptionId: string }
  | { kind: "risk-gap"; riskId: string };

/** The Estimate tab's content: the toolbar, the Version lifecycle card, the uncovered banner,
 * the grid and the Assumptions Register below it in the main pane, and the selected line's (or Assumption's Gap's) inspector in the right pane
 * (opened if closed). While an assessment run (which builds the Estimate, Story 8.3), a
 * model draft left over from before Story 8.3, or the Assumption proposals are queued or
 * running the Estimate is re-read every 2 s:
 * paused while the tab is hidden, and stopped after 15 minutes. A selected line that a new
 * version replaced leaves the pane showing the empty Inspector text (and, when its "Edit line"
 * form held unsaved changes, says so above the grid). Lines of the draft are editable in the
 * inspector for those who may edit them (Story 8.2), with a note when a new version could not
 * carry some edits; Accept for those who may accept Assumptions. No draft Retry. */
export function EstimateSection({
  opportunityId,
  initial,
  initialReviews = null,
}: {
  opportunityId: string;
  initial: EstimateView;
  /** Story 9.1: the current version's Review Requests (null: not read). */
  initialReviews?: ReviewRequestsView | null;
}) {
  const announce = useAnnounce();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [view, setView] = useState<EstimateView>(initial);
  const [reviews, setReviews] = useState<ReviewRequestsView | null>(initialReviews);
  const [reviewsFrom, setReviewsFrom] = useState(initialReviews);
  if (initialReviews !== reviewsFrom) {
    setReviewsFrom(initialReviews);
    setReviews(initialReviews);
  }
  const [selection, setSelection] = useState<Selection | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  /** Bumped to move focus into the inspector's "Edit line" form (opened with `e`). */
  const [editFocusRequest, setEditFocusRequest] = useState(0);
  /** The inspector's "Edit line" form holds unsaved changes. */
  const [editDirty, setEditDirty] = useState(false);
  /** A new version replaced the line whose unsaved change was open. */
  const [replaced, setReplaced] = useState(false);
  /** The element to focus when the pane closes after a keyboard open. */
  const returnFocusTo = useRef<string | null>(null);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const [stalled, setStalled] = useState(false);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (an edit, an acceptance); a poll that started before one
   * is dropped. */
  const mutation = useRef(0);
  const draftingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const drafting = isDrafting(view.draft);
  const proposing = isProposing(view.version);
  const building = view.assessment_running;
  const working = building || drafting || proposing;
  /** The view as last rendered, for the poll to tell what finished. */
  const viewRef = useRef(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  // A new version drops an open edit (its lines are gone): say so if it held changes.
  const [seenVersionId, setSeenVersionId] = useState(view.version?.id ?? null);
  if (seenVersionId !== (view.version?.id ?? null)) {
    setSeenVersionId(view.version?.id ?? null);
    if (editDirty) setReplaced(true);
    setEditDirty(false);
    // The inspector remounts for the new version: it must not take focus again.
    setFocusRequest(0);
    setEditFocusRequest(0);
  }

  const lines = view.version?.sections.flatMap((section) => section.lines) ?? [];
  const register = view.version
    ? [...view.version.assumptions.conditions, ...view.version.assumptions.contingencies]
    : [];
  const selected =
    selection?.kind === "line" ? (lines.find((line) => line.id === selection.id) ?? null) : null;
  const risks = view.version?.risks ?? [];
  const gapOf =
    selection?.kind === "gap"
      ? (register.find((a) => a.id === selection.assumptionId) ?? null)
      : selection?.kind === "risk-gap"
        ? (risks.find((r) => r.id === selection.riskId) ?? null)
        : null;
  const selectedAssumption =
    selection?.kind === "assumption"
      ? (register.find((a) => a.id === selection.id) ?? null)
      : null;
  const selectedRisk =
    selection?.kind === "risk" ? (risks.find((r) => r.id === selection.id) ?? null) : null;
  const [accepting, setAccepting] = useState(false);
  const [acceptMessage, setAcceptMessage] = useState<string | null>(null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) {
      setFocusRequest(0);
      setEditFocusRequest(0);
    }
  }

  // When the pane closes after a keyboard open, focus goes back to the line, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(id)?.focus();
    }
  }, [rightPaneOpen]);

  function open(line: EstimateLine, viaKeyboard: boolean, edit = false) {
    setSelection({ kind: "line", id: line.id });
    setReplaced(false);
    returnFocusTo.current = viaKeyboard ? `[data-line-id="${line.id}"]` : null;
    // Focus goes to the title, or with `e` to the form's Effort field: never both.
    setFocusRequest((n) => (viaKeyboard && !edit ? n + 1 : 0));
    setEditFocusRequest((n) => (edit ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function openAssumption(assumption: Assumption, viaKeyboard: boolean) {
    setSelection({ kind: "assumption", id: assumption.id });
    setReplaced(false);
    setAcceptMessage(null);
    returnFocusTo.current = viaKeyboard
      ? `[data-assumption-id="${assumption.id}"] [data-open-assumption]`
      : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    setEditFocusRequest(0);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function openRisk(risk: Risk, viaKeyboard: boolean) {
    setSelection({ kind: "risk", id: risk.id });
    setReplaced(false);
    returnFocusTo.current = viaKeyboard ? `[data-risk-id="${risk.id}"] [data-risk-row]` : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    setEditFocusRequest(0);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  /** Story 9.3: a Review requests row (or `?review={id}`) opens its review panel. */
  function openReview(requestId: string, viaKeyboard: boolean) {
    setSelection({ kind: "review", id: requestId });
    setReplaced(false);
    returnFocusTo.current = viaKeyboard ? `[data-open-review="${requestId}"]` : null;
    setFocusRequest(0);
    setEditFocusRequest(0);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  // `?review={id}` (the Inbox's and the blockers' links): open that panel once.
  const linkedOpened = useRef(false);
  useEffect(() => {
    if (linkedOpened.current) return;
    const wanted = linkedReview();
    if (!wanted || !UUID_RE.test(wanted)) return;
    // After the first render (the URL is read in the browser only). The ref is set when the
    // timer fires, so a StrictMode re-run (whose cleanup cleared the first timer) opens it.
    const timer = setTimeout(() => {
      linkedOpened.current = true;
      setSelection({ kind: "review", id: wanted });
      setRightPaneOpen(true);
    }, 0);
    return () => clearTimeout(timer);
  }, [setRightPaneOpen]);

  function openGap(assumption: Assumption, viaKeyboard: boolean) {
    setSelection({ kind: "gap", assumptionId: assumption.id });
    setReplaced(false);
    returnFocusTo.current = viaKeyboard
      ? `[data-assumption-id="${assumption.id}"] [data-gap-chip]`
      : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    setEditFocusRequest(0);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!working) {
      draftingSince.current = null;
      return;
    }
    draftingSince.current ??= Date.now();
    if (!visible) return;
    if (Date.now() - draftingSince.current >= DRAFT_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadEstimate(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          const before = viewRef.current;
          setView(result.estimate);
          const { version } = result.estimate;
          if (before.assessment_running && !result.estimate.assessment_running) {
            announce(version ? versionPillLabel(version) : NO_ESTIMATE);
          } else if (version && version.id !== before.version?.id) {
            announce(versionPillLabel(version));
          } else if (isProposing(before.version) && version && !isProposing(version)) {
            announce(`Assumptions Register: ${registerSummary(version.counts)}`);
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = draftingSince.current;
      if (since !== null && Date.now() - since >= DRAFT_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, DRAFT_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [working, visible, opportunityId, pollTick, announce]);

  /** Story 8.2: save a line's change with its reason (from the inspector's "Edit line" form);
   * the grid re-renders from the server's Estimate. */
  async function saveLine(
    line: EstimateLine,
    change: LineChange,
    reason: string,
    rowVersion: number,
  ): Promise<EditOutcome> {
    let result: EstimateLineEditResult;
    try {
      result = await editEstimateLine({
        opportunityId,
        lineId: line.id,
        rowVersion,
        ...(change.effortHours !== undefined ? { effortHours: change.effortHours } : {}),
        ...(change.roleMix !== undefined ? { roleMix: change.roleMix } : {}),
        reason,
      });
    } catch {
      result = { kind: "error" };
    }
    let outcome: EditOutcome;
    switch (result.kind) {
      case "ok":
        mutation.current += 1;
        setView(result.estimate);
        announce(`Saved: ${line.title}`);
        return { ok: true };
      case "stale":
        outcome = { ok: false, message: result.message, reload: true };
        break;
      case "not-draft":
        outcome = { ok: false, message: VERSION_REPLACED, reload: true };
        break;
      case "invalid":
        outcome = { ok: false, message: result.detail };
        break;
      case "forbidden":
        outcome = { ok: false, message: EDIT_NOT_ALLOWED };
        break;
      case "not-found":
        outcome = { ok: false, message: NO_ACCESS_TO_OPPORTUNITY };
        break;
      default:
        outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    announce(outcome.message);
    return outcome;
  }

  /** Story 8.5: the outcome of saving an Assumption's or a Risk's edit. */
  function itemOutcome(result: EstimateItemEditResult, label: string): EditOutcome {
    let outcome: EditOutcome;
    switch (result.kind) {
      case "ok":
        mutation.current += 1;
        setView(result.estimate);
        announce(`Saved: ${label}`);
        return { ok: true };
      case "stale":
        outcome = { ok: false, message: result.message, reload: true };
        break;
      case "not-draft":
        outcome = { ok: false, message: VERSION_REPLACED, reload: true };
        break;
      case "invalid":
        outcome = { ok: false, message: result.detail };
        break;
      case "forbidden":
        outcome = { ok: false, message: EDIT_NOT_ALLOWED };
        break;
      case "not-found":
        outcome = { ok: false, message: ITEM_GONE, reload: true };
        break;
      default:
        outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    announce(outcome.message);
    return outcome;
  }

  async function saveAssumption(
    assumption: Assumption,
    fields: AssumptionFields,
    reason: string,
    rowVersion: number,
  ): Promise<EditOutcome> {
    let result: EstimateItemEditResult;
    try {
      result = await editAssumption({
        opportunityId,
        assumptionId: assumption.id,
        rowVersion,
        ...fields,
        reason,
      });
    } catch {
      result = { kind: "error" };
    }
    return itemOutcome(result, assumptionId(assumption));
  }

  async function saveRisk(
    risk: Risk,
    fields: RiskFields,
    reason: string,
    rowVersion: number,
  ): Promise<EditOutcome> {
    let result: EstimateItemEditResult;
    try {
      result = await editRisk({ opportunityId, riskId: risk.id, rowVersion, ...fields, reason });
    } catch {
      result = { kind: "error" };
    }
    return itemOutcome(result, riskId(risk));
  }

  /** Story 8.5: **Accept** from the Assumption inspector; the Estimate is read again. */
  async function acceptFromInspector(assumption: Assumption) {
    if (accepting) return;
    setAccepting(true);
    setAcceptMessage(null);
    let result: AssumptionAcceptResult;
    try {
      result = await acceptAssumption({
        opportunityId,
        assumptionId: assumption.id,
        rowVersion: assumption.row_version,
      });
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      try {
        const loaded = await loadEstimate(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setView(loaded.estimate);
        }
      } catch {
        // The tab stays as it is.
      }
      announce(acceptedLabel(result.assumption));
    } else {
      const sentence =
        result.kind === "stale" ? staleMessage(result.changedBy) : acceptFailure(result);
      setAcceptMessage(sentence);
      announce(sentence);
    }
    setAccepting(false);
  }

  /** Story 9.1: read the Estimate and its Review Requests again (after a send or a cancel,
   * and on every Review Request frame of the event stream). */
  const reloadReviews = useCallback(async () => {
    try {
      const [estimate, requests] = await Promise.all([
        loadEstimate(opportunityId),
        loadReviewRequests(opportunityId),
      ]);
      if (estimate.kind === "ok") {
        mutation.current += 1;
        setView(estimate.estimate);
      }
      if (requests.kind === "ok") setReviews(requests.reviews);
    } catch {
      // The tab stays as it is; the next frame reads them again.
    }
  }, [opportunityId]);
  useReviewEvents(opportunityId, () => void reloadReviews(), initialReviews !== null);

  async function reloadEstimate() {
    try {
      const loaded = await loadEstimate(opportunityId);
      if (loaded.kind === "ok") {
        mutation.current += 1;
        setView(loaded.estimate);
        announce("Reloaded the Estimate");
      }
    } catch {
      // The tab stays as it is.
    }
  }

  const { version } = view;
  const draft = version?.status === "draft";
  const canEditLines = view.can_edit_lines && draft;
  // Story 8.5: a version that isn't the draft, and sales representatives, see no Accept,
  // Accept all, Edit or Risk edit controls.
  const canAccept = view.can_accept_assumptions && draft;
  const canEditAssumptions = view.can_edit_assumptions && draft;
  const canEditRisks = view.can_edit_risks && draft;
  // Story 9.1: the requests shown are the current version's; the API's flags decide who may
  // send or cancel them.
  const versionReviews = reviews && version && reviews.version_id === version.id ? reviews : null;
  return (
    <div className="flex flex-col gap-4">
      <EstimateHeader
        version={version}
        assessmentRunning={building}
        opportunityId={opportunityId}
        canExport={view.can_export}
        stalled={stalled}
        actions={
          version && view.can_request_review && isSent(version.status) ? (
            <RequestReviewDialog
              opportunityId={opportunityId}
              version={version}
              assessments={versionReviews?.assessments ?? []}
              onSent={() => void reloadReviews()}
            />
          ) : null
        }
      />
      {version ? (
        <>
          {isSent(version.status) ? (
            <p
              data-submitted-banner=""
              className="flex items-center gap-2 rounded-lg border border-resolved/30 bg-resolved-tint px-4 py-2.5 text-resolved"
            >
              <CheckIcon aria-hidden="true" className="size-4 shrink-0" />
              <span className="text-body-strong">
                {submittedBanner(version.version, version.submitted_at)}
              </span>
              <span className="text-meta text-muted-foreground">
                Submitted versions can&apos;t be edited.
              </span>
            </p>
          ) : null}
          <VersionLifecycle version={version} />
          {versionReviews && isSent(version.status) ? (
            <ReviewRequestsCard
              opportunityId={opportunityId}
              items={versionReviews.items}
              onChanged={() => void reloadReviews()}
              onOpen={(request: ReviewRequest, viaKeyboard) => openReview(request.id, viaKeyboard)}
              selectedId={selection?.kind === "review" ? selection.id : null}
            />
          ) : null}
          <UncoveredBanner count={version.uncovered_count} />
          {replaced ? (
            <p className="flex items-center gap-1.5 text-meta text-destructive" role="alert">
              <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
              {NEW_VERSION_ARRIVED}
            </p>
          ) : null}
          <EstimateGrid
            version={version}
            selectedId={selected?.id ?? null}
            onOpen={open}
            canEdit={canEditLines}
            opportunityId={opportunityId}
          />
          <AssumptionsRegister
            opportunityId={opportunityId}
            version={version}
            canAccept={canAccept}
            selectedId={selection?.kind === "gap" ? (gapOf?.id ?? null) : null}
            selectedAssumptionId={selectedAssumption?.id ?? null}
            onChanged={(estimate) => {
              mutation.current += 1;
              setView(estimate);
            }}
            onOpen={openAssumption}
            onOpenGap={openGap}
          />
          <RisksCard risks={version.risks} selectedId={selectedRisk?.id ?? null} onOpen={openRisk} />
        </>
      ) : !building ? (
        <EmptyTabCard
          title={NO_ESTIMATE_TITLE}
          body={NO_ESTIMATE_BODY}
          actionLabel={RUN_ASSESSMENT}
          href={tabHref(opportunityId, "assessments")}
        />
      ) : null}
      {selected ? (
        <RightPaneContent>
          <EstimateInspector
            // A new version remounts it, dropping an unsaved edit of the replaced line.
            key={`${version?.id}-${selected.id}`}
            line={selected}
            opportunityId={opportunityId}
            focusRequest={focusRequest}
            editing={
              canEditLines && version
                ? {
                    versionId: version.id,
                    reasonKey: opportunityId,
                    onSave: saveLine,
                    onReload: () => void reloadEstimate(),
                    onDirtyChange: setEditDirty,
                    focusRequest: editFocusRequest,
                  }
                : undefined
            }
          />
        </RightPaneContent>
      ) : selectedAssumption ? (
        <RightPaneContent>
          <AssumptionInspector
            key={`${version?.id}-${selectedAssumption.id}`}
            assumption={selectedAssumption}
            focusRequest={focusRequest}
            onOpenGap={() => openGap(selectedAssumption, false)}
            accepting={
              canAccept
                ? {
                    busy: accepting,
                    onAccept: () => void acceptFromInspector(selectedAssumption),
                    message: acceptMessage,
                  }
                : undefined
            }
            editing={
              canEditAssumptions
                ? {
                    lines: lines.map((line) => ({ id: line.id, title: line.title })),
                    onSave: saveAssumption,
                    onReload: () => void reloadEstimate(),
                  }
                : undefined
            }
          />
        </RightPaneContent>
      ) : selectedRisk ? (
        <RightPaneContent>
          <RiskInspector
            key={`${version?.id}-${selectedRisk.id}`}
            risk={selectedRisk}
            focusRequest={focusRequest}
            onOpenGap={() => {
              setSelection({ kind: "risk-gap", riskId: selectedRisk.id });
              setFocusRequest(0);
            }}
            editing={
              canEditRisks
                ? { onSave: saveRisk, onReload: () => void reloadEstimate() }
                : undefined
            }
          />
        </RightPaneContent>
      ) : gapOf ? (
        <RightPaneContent>
          <OriginGapInspector key={gapOf.id} gap={gapOf.origin} focusRequest={focusRequest} />
        </RightPaneContent>
      ) : selection?.kind === "review" ? (
        <RightPaneContent>
          <div key={selection.id} className="p-gutter">
            <ReviewPanelLoader
              opportunityId={opportunityId}
              requestId={selection.id}
              layout="inspector"
              onDecided={() => void reloadReviews()}
            />
          </div>
        </RightPaneContent>
      ) : null}
    </div>
  );
}
