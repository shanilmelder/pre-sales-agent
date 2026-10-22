import * as React from "react"
import { cn } from "cn"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={`${cn(
        "flex field-sizing-content min-h-16 w-full rounded-md border border-border-strong bg-surface-alt px-3 py-2 text-foreground transition-colors duration-[120ms] outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-40 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20",
        className
      )} text-body`}
      {...props}
    />
  )
}

export { Textarea }
