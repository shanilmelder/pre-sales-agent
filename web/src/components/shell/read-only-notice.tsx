export const READ_ONLY_MESSAGE =
  "The workbench needs a wider screen. You can view Opportunities here, but editing is disabled.";

/** Shown only below 1024px, where the workbench is read-only. */
export function ReadOnlyNotice() {
  return (
    <p
      data-testid="read-only-notice"
      className="border-b border-border bg-muted px-gutter py-2 text-body min-[1024px]:hidden"
    >
      {READ_ONLY_MESSAGE}
    </p>
  );
}
