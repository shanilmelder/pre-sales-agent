"use client";

import { CircleAlertIcon, WaypointsIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { EditLineForm, type SaveLine } from "@/components/opportunities/estimate-line-edit";
import { LineLineageSection } from "@/components/opportunities/lineage-section";
import { typeLabel } from "@/lib/conflicts";
import {
  editedLabel,
  editHistory,
  hours,
  lineHeading,
  OPEN_CONFLICT,
  roleShares,
  TRACE,
  type EstimateLine,
  type RoleMix,
  type RoleName,
} from "@/lib/estimates";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

/** Each role's colour in the role-mix bar and its legend. */
export const ROLE_COLOUR: Record<RoleName, string> = {
  engineer: "bg-primary",
  project_manager: "bg-role-pm",
  qa: "bg-role-qa",
};

/** The role mix as an 8px stacked bar (decorative: the shares are always given as text too). */
export function RoleMixBar({ mix, className }: { mix: RoleMix; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-role-bar=""
      className={cn("flex h-2 w-full overflow-hidden rounded-full bg-surface-alt", className)}
    >
      {roleShares(mix).map((role) =>
        role.percent > 0 ? (
          <span
            key={role.value}
            className={cn("h-full", ROLE_COLOUR[role.value])}
            style={{ width: `${role.percent}%` }}
          />
        ) : null,
      )}
    </span>
  );
}

function Label({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h4 className={`${cn("text-muted-foreground uppercase", className)} text-eyebrow`}>
      {children}
    </h4>
  );
}

/** What the inspector needs to offer the "Edit line" form; left out, there is no form. */
export type LineEditing = {
  versionId: string;
  reasonKey: string;
  onSave: SaveLine;
  onReload?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  /** Bumped to move focus to the form's Effort field instead of the title. */
  focusRequest?: number;
};

/** The selected Estimate line in the right pane: "{section} · line {position}" over its title,
 * the basis for its effort, its role mix as a bar and broken down into hours
 * (server-calculated), its effort, Contingency and total, and the Requirements it covers as
 * chips with their excerpts. A line with an open Conflict about a Requirement it covers (Story
 * 8.3) names each Conflict's type and links to the Conflicts tab; an edited line (Story 8.2)
 * shows who edited it, when and why. With `editing` (a draft the user may edit) it ends with
 * the "Edit line" form. Story 9.9: with `opportunityId`, a **Trace** outline button under the
 * title and the **Lineage** section at the end; **Trace** (or `lineageFocusRequest` going up,
 * `t` on a grid row) scrolls to and focuses it. */
export function EstimateInspector({
  line,
  opportunityId,
  focusRequest = 0,
  lineageFocusRequest = 0,
  lineageFocusHandled = 0,
  onLineageFocused,
  editing,
}: {
  line: EstimateLine;
  /** Needed for the Conflicts tab link and the lineage; without it they are left out. */
  opportunityId?: string;
  focusRequest?: number;
  /** Bumped to scroll to and focus the Lineage section (`t` on a grid row). */
  lineageFocusRequest?: number;
  /** The last `lineageFocusRequest` already acted on (a remount must not act on it again). */
  lineageFocusHandled?: number;
  onLineageFocused?: (request: number) => void;
  editing?: LineEditing;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  /** Bumped by the **Trace** button. */
  const [traceRequest, setTraceRequest] = useState(0);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-5 p-gutter">
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">{lineHeading(line)}</p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {line.title}
        </h3>
        {opportunityId ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-1 w-fit text-control"
            data-trace-button=""
            onClick={() => setTraceRequest((n) => n + 1)}
          >
            <WaypointsIcon aria-hidden="true" />
            {TRACE}
          </Button>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Basis</Label>
        <p className="whitespace-pre-wrap break-words text-body">{line.basis}</p>
      </div>

      <div className="flex flex-col gap-2">
        <Label>Role mix</Label>
        <RoleMixBar mix={line.role_mix} />
        <table className="w-full text-body">
          <caption className="sr-only">Role mix in hours</caption>
          <thead>
            <tr className="text-label text-muted-foreground">
              <th scope="col" className="py-0.5 text-left font-medium">
                Role
              </th>
              <th scope="col" className="py-0.5 text-right font-medium">
                Share (%)
              </th>
              <th scope="col" className="py-0.5 text-right font-medium">
                Effort (h)
              </th>
            </tr>
          </thead>
          <tbody>
            {roleShares(line.role_mix).map((role) => (
              <tr key={role.value} data-role={role.value}>
                <th scope="row" className="py-0.5 text-left font-normal">
                  <span className="inline-flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={cn("size-2.5 shrink-0 rounded-sm", ROLE_COLOUR[role.value])}
                    />
                    {role.label}
                  </span>
                </th>
                <td className="py-0.5 text-right text-numeric">{role.share}</td>
                <td className="py-0.5 text-right text-numeric">
                  {hours(line.role_hours[role.value])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="grid grid-cols-3 gap-2">
        {(
          [
            ["Effort (h)", line.effort_hours],
            ["Contingency (h)", line.contingency_hours],
            ["Total (h)", line.total_hours],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <dt className="text-label text-muted-foreground">{label}</dt>
            <dd className="text-numeric">{hours(value)}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-2">
        <Label>Covered Requirements</Label>
        <ul className="flex flex-col gap-1.5">
          {line.requirements.map((requirement) => (
            <li key={requirement.id} className="flex items-baseline gap-2">
              <Chip className="shrink-0">{requirement.label}</Chip>
              <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
            </li>
          ))}
        </ul>
      </div>

      {line.conflicts.length > 0 ? (
        <div className="flex flex-col gap-1" data-line-conflicts="">
          <h4 className="flex items-center gap-1.5 text-label text-blocker">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            {OPEN_CONFLICT}
          </h4>
          <ul className="flex flex-col gap-0.5 text-body">
            {line.conflicts.map((conflict) => (
              <li key={conflict.id}>{`${typeLabel(conflict.type)} Conflict`}</li>
            ))}
          </ul>
          {opportunityId ? (
            <Link
              href={tabHref(opportunityId, "conflicts")}
              className="w-fit rounded-sm text-label text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
            >
              View on the Conflicts tab
            </Link>
          ) : null}
        </div>
      ) : null}

      {line.edited ? (
        <div className="flex flex-col gap-1" data-edit-history="">
          <h4 className="text-label text-muted-foreground">{editedLabel(line)}</h4>
          <p className="whitespace-pre-wrap break-words text-body">{editHistory(line)}</p>
        </div>
      ) : null}

      {editing ? (
        <EditLineForm
          line={line}
          versionId={editing.versionId}
          reasonKey={editing.reasonKey}
          onSave={editing.onSave}
          onReload={editing.onReload}
          onDirtyChange={editing.onDirtyChange}
          focusRequest={editing.focusRequest}
        />
      ) : null}

      {opportunityId ? (
        <LineLineageSection
          opportunityId={opportunityId}
          lineId={line.id}
          focusRequest={traceRequest}
          externalFocusRequest={lineageFocusRequest}
          externalFocusHandled={lineageFocusHandled}
          onExternalFocus={onLineageFocused}
          reloadKey={`${line.row_version}:${line.total_hours}`}
        />
      ) : null}
    </section>
  );
}
