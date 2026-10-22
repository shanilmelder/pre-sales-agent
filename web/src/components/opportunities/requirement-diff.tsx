import { classificationChange, type Classification } from "@/lib/requirements";

/** One side of a Requirement diff: its text and classification. */
export type DiffSide = { text: string; classification: Classification };

/** A Requirement diff: the `before` text as a `−` line and the `after` text as a `+` line,
 * both on the diff tint (never green or red), then the classification change, if any.
 * Shared by the pending change (Story 2.7) and **View diff** after a 412 (Story 2.6).
 * `beforeLabel` / `afterLabel` name the lines for screen readers. */
export function RequirementDiff({
  before,
  after,
  beforeLabel,
  afterLabel,
}: {
  before: DiffSide;
  after: DiffSide;
  beforeLabel: string;
  afterLabel: string;
}) {
  const classification = classificationChange(before.classification, after.classification);
  return (
    <>
      <div className="flex flex-col gap-0.5 text-body">
        <p className="flex gap-2 rounded-sm bg-diff-tint px-1.5 py-0.5">
          <span aria-hidden="true" className="shrink-0 text-muted-foreground">
            −
          </span>
          <span className="sr-only">{`${beforeLabel}: `}</span>
          <span className="min-w-0 break-words">{before.text}</span>
        </p>
        <p className="flex gap-2 rounded-sm bg-diff-tint px-1.5 py-0.5">
          <span aria-hidden="true" className="shrink-0 text-muted-foreground">
            +
          </span>
          <span className="sr-only">{`${afterLabel}: `}</span>
          <span className="min-w-0 break-words">{after.text}</span>
        </p>
      </div>
      {classification ? <p className="text-meta">{classification}</p> : null}
    </>
  );
}
