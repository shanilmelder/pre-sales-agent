import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const pillVariants = cva(
  "inline-flex items-center gap-1 rounded-full py-0.5 pr-2.5 pl-2 whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "bg-neutral-tint text-neutral",
        resolved: "bg-resolved-tint text-resolved",
        agent: "bg-agent-tint text-agent",
        blocker: "bg-blocker-tint text-blocker",
        gap: "bg-gap-tint text-gap",
      },
    },
    defaultVariants: { tone: "neutral" },
  }
)

type PillProps = React.ComponentProps<"span"> &
  VariantProps<typeof pillVariants> & {
    /** A 12px icon; decorative, the label carries the meaning. */
    icon?: React.ReactNode
  }

/** The tint-filled status pill. Named Pill because StatusPill is taken by opportunities. */
function Pill({ className, tone, icon, children, ...props }: PillProps) {
  return (
    <span
      data-slot="pill"
      data-tone={tone ?? "neutral"}
      className={`${cn(pillVariants({ tone: tone ?? "neutral" }), className)} text-label`}
      {...props}
    >
      {icon ? (
        <span aria-hidden="true" className="inline-flex">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  )
}

export { Pill, pillVariants }
