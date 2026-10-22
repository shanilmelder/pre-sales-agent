import * as React from "react"
import { cn } from "cn"

/** A static neutral block: no shimmer, no pulse. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("rounded-md bg-neutral-tint", className)}
      {...props}
    />
  )
}

export { Skeleton }
