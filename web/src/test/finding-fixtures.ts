import type { FindingState } from "@/lib/findings";

/** A Critic or Red Team Finding's Story 6.6 fields while open, nobody acting (spread over a
 * fixture's `id`, category, severity and text). */
export const OPEN_STATE: Omit<FindingState, "id"> = {
  status: "open",
  resolution: null,
  override: null,
  previous_override: null,
  policy_ref: null,
  overridable: true,
  can_resolve: false,
  can_override: false,
  row_version: 1,
};
