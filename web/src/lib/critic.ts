// Critic display helpers (Story 6.4). Safe on server and client.
import type { components } from "@/lib/api/client";

export type CriticView = components["schemas"]["CriticView"];
export type CriticReview = components["schemas"]["CriticReviewView"];
export type CriticFinding = components["schemas"]["CriticFinding"];
export type CitedFinding = components["schemas"]["CitedFinding"];
export type CriticCategory = components["schemas"]["CriticCategory"];

/** The Critic's name on its task card, result card and in the Findings table's Raised by. */
export const CRITIC_LABEL = "Critic";

/** One line on what the Critic checks, shown on its task card. */
export const CRITIC_ROLE = "Checks coverage, unsupported claims and timelines across the Assessments";

/** The categories with their labels. */
export const CRITIC_CATEGORIES: readonly { value: CriticCategory; label: string }[] = [
  { value: "coverage", label: "Coverage" },
  { value: "unsupported_claim", label: "Unsupported claim" },
  { value: "timeline", label: "Timeline" },
  { value: "dependency", label: "Dependency" },
  { value: "risk_coverage", label: "Risk coverage" },
];

/** A category's label (its own name for one this build doesn't know). */
export function criticCategoryLabel(value: CriticCategory): string {
  return CRITIC_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** The review's label: "Critic v2". */
export function criticReviewLabel(review: Pick<CriticReview, "version">): string {
  return `${CRITIC_LABEL} v${review.version}`;
}

/** The result card's note while the run's Critic task is running. */
export const CRITIC_REVIEWING = "Critic reviewing";

/** A cited specialist Finding's chip: "Engineering Agent v2". */
export function citedFindingLabel(cited: Pick<CitedFinding, "role" | "assessment_version">): string {
  return `${cited.role} v${cited.assessment_version}`;
}
