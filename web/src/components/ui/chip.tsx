import * as React from "react"
import { cn } from "cn"

/** The chip's shape without colours, for button chips that recolour themselves (pressed). */
const chipLayoutClassName = "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5"

/** The evidence chip: a source reference such as `S2 · email-it-systems`. */
function Chip({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="chip"
      className={`${cn(
        "inline-flex items-center gap-1 rounded-sm border border-border-strong bg-surface px-2 py-0.5 text-primary-text",
        className
      )} text-label`}
      {...props}
    />
  )
}

export { Chip, chipLayoutClassName }
