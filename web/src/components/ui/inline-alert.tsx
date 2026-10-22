import * as React from "react"

import { Button } from "@/components/ui/button"

type InlineAlertProps = {
  id?: string
  /** The lead line, such as who changed the record. */
  lead: string
  /** Detail under the lead line, such as a diff. */
  children?: React.ReactNode
  onReload: () => void
  /** Disables Reload (aria-disabled) while a reload is in flight. */
  reloading?: boolean
  reloadRef?: React.Ref<HTMLButtonElement>
  /** When set, a View diff button is shown. */
  onViewDiff?: () => void
  viewDiffLabel?: string
  diffExpanded?: boolean
}

/** The shared inline alert: red tint, lead line, detail and the Reload and View diff actions. */
function InlineAlert({
  id,
  lead,
  children,
  onReload,
  reloading,
  reloadRef,
  onViewDiff,
  viewDiffLabel = "View diff",
  diffExpanded,
}: InlineAlertProps) {
  return (
    <div
      id={id}
      role="alert"
      data-slot="inline-alert"
      data-tone="error"
      className="flex max-w-md flex-col gap-2 rounded-lg border border-blocker bg-blocker-tint p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-meta text-foreground">{lead}</p>
        <span className="flex shrink-0 gap-2">
          {onViewDiff ? (
            <Button
              type="button"
              variant="outline"
              size="xs"
              aria-expanded={diffExpanded}
              onClick={onViewDiff}
            >
              {viewDiffLabel}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="xs"
            ref={reloadRef}
            onClick={onReload}
            aria-disabled={reloading || undefined}
          >
            Reload
          </Button>
        </span>
      </div>
      {children}
    </div>
  )
}

export { InlineAlert, type InlineAlertProps }
