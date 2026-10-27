// The Opportunity outcome and its retention date (Story 10.5). Display only: the API
// computes the retention date (never the browser). Safe on server and client.

import { formatDate, type Opportunity, type OpportunityStatus } from "@/lib/opportunities";

/** The four outcome commands the Overview's Outcome card offers. */
export const OUTCOME_COMMANDS = ["lost", "won", "contract_end", "reopen"] as const;
export type OutcomeCommand = (typeof OUTCOME_COMMANDS)[number];

/** The API's longest reason, in code points. */
export const OUTCOME_REASON_MAX = 1000;

export const OUTCOME_HEADING = "Outcome";
export const REASON_LABEL = "Reason (required)";
export const CONTRACT_END_LABEL = "Contract end date";
export const CANCEL = "Cancel";
export const OUTCOME_REJECTED = "The change was not accepted.";
export const OUTCOME_FAILED = "The outcome couldn't be saved. Try again.";
export const OUTCOME_FORBIDDEN = "You can't change this Opportunity's outcome.";
export const NEEDS_BASELINE = "Mark as won once a Baseline is set.";

/** The label/value rows' values. */
export const OUTCOME_LABELS = { won: "Won", lost: "Lost", open: "Open" } as const;

/** What each command's button and dialog say. */
export const OUTCOME_DIALOGS: Record<
  OutcomeCommand,
  {
    button: string;
    title: string;
    submit: string;
    helper: string;
    placeholder: string;
    reason: boolean;
    date: boolean;
    announce: string;
  }
> = {
  lost: {
    button: "Close as lost",
    title: "Close as lost",
    submit: "Close as lost",
    helper: "The Opportunity's data is kept for 3 years from today, then purged.",
    placeholder: "State why the Opportunity was lost.",
    reason: true,
    date: false,
    announce: "Closed as lost",
  },
  won: {
    button: "Mark as won",
    title: "Mark as won",
    submit: "Mark as won",
    helper: "The Opportunity's data is kept until the contract end date plus 7 years.",
    placeholder: "",
    reason: false,
    date: true,
    announce: "Marked as won",
  },
  contract_end: {
    button: "Change contract end date",
    title: "Change contract end date",
    submit: "Change date",
    helper: "The retention date moves with it: contract end plus 7 years.",
    placeholder: "State why the contract end date changed.",
    reason: true,
    date: true,
    announce: "Contract end date changed",
  },
  reopen: {
    button: "Reopen",
    title: "Reopen Opportunity",
    submit: "Reopen",
    helper: "Clears the outcome and contract end date. Open Opportunities are never purged.",
    placeholder: "State why the Opportunity is reopened.",
    reason: true,
    date: false,
    announce: "Opportunity reopened",
  },
};

/** The outcome line: "Lost — data kept until 14 Oct 2029", "Won — data kept until contract
 * end plus 7 years (30 Jun 2035)", or, while open, that it is never purged. */
export function retentionLine(
  opportunity: Pick<Opportunity, "outcome" | "retention_until">,
): string {
  const until = opportunity.retention_until ? formatDate(opportunity.retention_until) : null;
  if (opportunity.outcome === "lost") {
    return until ? `Lost — data kept until ${until}` : "Lost";
  }
  if (opportunity.outcome === "won") {
    return until ? `Won — data kept until contract end plus 7 years (${until})` : "Won";
  }
  return "Open — data is kept while the Opportunity is open.";
}

/** Whether the Opportunity has (had) a Baseline, from its derived status: marking it won
 * needs one. The API checks again. */
export function hasBaseline(status: OpportunityStatus): boolean {
  return status === "baselined" || status === "delivered";
}
