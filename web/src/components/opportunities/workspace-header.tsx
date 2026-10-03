import { CalendarIcon, UsersIcon } from "lucide-react";

import { StatusPill } from "@/components/opportunities/status-pill";
import { formatDate, type Opportunity } from "@/lib/opportunities";

/** The workspace header (mockups/opportunity-overview.html): the title, then one meta row
 * with the derived status, owner, collaborators and target proposal date. */
export function WorkspaceHeader({ opportunity }: { opportunity: Opportunity }) {
  const collaborators = opportunity.collaborators.map((c) => c.name).join(", ");
  return (
    <header className="flex shrink-0 flex-col gap-1.5 px-gutter pt-gutter pb-3">
      <h1 className="text-title">{opportunity.title}</h1>
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-label text-muted-foreground">
        <StatusPill status={opportunity.status} />
        <span>
          <span className="text-foreground">{opportunity.owner.name}</span> · owner
        </span>
        <span className="inline-flex items-center gap-1.5">
          <UsersIcon className="size-3 shrink-0" aria-hidden="true" />
          {collaborators ? (
            <span>
              <span className="sr-only">Collaborators: </span>
              <span className="text-foreground">{collaborators}</span>
            </span>
          ) : (
            "No collaborators"
          )}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <CalendarIcon className="size-3 shrink-0" aria-hidden="true" />
          Proposal due
          <span className="text-numeric text-foreground">
            {formatDate(opportunity.target_proposal_date)}
          </span>
        </span>
      </div>
    </header>
  );
}
