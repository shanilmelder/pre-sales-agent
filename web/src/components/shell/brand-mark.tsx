import { cn } from "cn";

/** The Pre Sales Agent mark: a one-stroke P with the agent's spark. Same art as app/icon.svg. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      data-testid="brand-mark"
      className={cn("shrink-0", className)}
    >
      <rect width="64" height="64" rx="16" fill="var(--primary)" />
      <path
        d="M21 46V18H31A9 9 0 0 1 31 36H21"
        fill="none"
        stroke="#FFFFFF"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M48 7C48.7 11.6 50.4 13.3 55 14C50.4 14.7 48.7 16.4 48 21C47.3 16.4 45.6 14.7 41 14C45.6 13.3 47.3 11.6 48 7Z"
        fill="#FFC861"
      />
    </svg>
  );
}
