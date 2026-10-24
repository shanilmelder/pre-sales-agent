import { CalendarIcon } from "lucide-react";

import {
  BreadcrumbRow,
  DueCountdown,
  PersonChip,
  WORKSPACE_BAND,
} from "@/components/opportunities/header-parts";
import { EditableWorkspaceHeader } from "@/components/opportunities/inline-field";
import { StatusPill } from "@/components/opportunities/status-pill";
import { SubmissionHeaderActions } from "@/components/opportunities/submission";
import { formatDate, type Opportunity } from "@/lib/opportunities";

/** The workspace header: breadcrumb, the title with its status pill, then the owner and
 * collaborator chips and the proposal date with its day countdown. When the API says the
 * caller may edit (`can_edit`, the owner), the title and date are click-to-edit; everyone
 * else sees plain text. `today` (UTC, from the server layout) keeps the countdown the same
 * on server and client. Story 8.6: the title row ends with Submit and, while blockers remain,
 * **Resolve N blockers** (for those who may submit). */
export function WorkspaceHeader({
  opportunity,
  today,
}: {
  opportunity: Opportunity;
  today: string;
}) {
  const badge = <StatusPill status={opportunity.status} />;
  const meta = (
    <>
      <PersonChip name={opportunity.owner.name} role="Owner" />
      {opportunity.collaborators.map((c) => (
        <PersonChip key={c.id} name={c.name} role="Collaborator" />
      ))}
      {opportunity.collaborators.length === 0 ? <span>No collaborators</span> : null}
    </>
  );

  // Story 8.6: Submit and Resolve N blockers, from the workspace's shared blockers.
  const actions = <SubmissionHeaderActions />;

  if (opportunity.can_edit) {
    return (
      <EditableWorkspaceHeader
        opportunity={opportunity}
        meta={meta}
        badge={badge}
        actions={actions}
        today={today}
      />
    );
  }

  return (
    <header className={WORKSPACE_BAND}>
      <BreadcrumbRow title={opportunity.title} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="min-w-0 text-title">{opportunity.title}</h1>
        {badge}
        {actions}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] leading-5 text-text-secondary">
        {meta}
        <span className="inline-flex items-center gap-1.5">
          <CalendarIcon className="size-3 shrink-0" aria-hidden="true" />
          Proposal due
          <span className="text-numeric text-foreground">
            {formatDate(opportunity.target_proposal_date)}
          </span>
          <DueCountdown date={opportunity.target_proposal_date} today={today} />
        </span>
      </div>
    </header>
  );
}
