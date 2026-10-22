import * as React from "react"
import { ChevronDownIcon } from "lucide-react"
import { cn } from "cn"

/** A styled native select: keeps native keyboard, form and test behaviour. */
function Select({
  className,
  children,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <span className="relative inline-flex w-full items-center">
      <select
        data-slot="select"
        className={`${cn(
          "h-[38px] w-full min-w-0 appearance-none rounded-md border border-border-strong bg-surface-alt py-1 pr-9 pl-3 text-foreground transition-colors duration-[120ms] outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-40 aria-invalid:border-destructive",
          className
        )} text-body`}
        {...props}
      >
        {children}
      </select>
      <ChevronDownIcon
        aria-hidden="true"
        className="pointer-events-none absolute right-3 size-4 text-text-secondary"
      />
    </span>
  )
}

export { Select }
