import Link from "next/link"
import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"

type KpiTileProps = {
  label: string
  value: ReactNode
  /** A smaller trailing part of the value: " of 12", " h". */
  unit?: string
  /** The whole tile links here (Overview); without it the tile is static (Reports). */
  href?: string
  children?: ReactNode
}

const BODY = "flex h-full flex-col rounded-xl p-5 text-foreground"

/** A KPI tile: a label, a 28px tabular value and optional notes (DESIGN.md, KPI tiles). */
function KpiTile({ label, value, unit, href, children }: KpiTileProps) {
  const content = (
    <>
      <span className="text-label text-muted-foreground">{label}</span>
      <span className="mt-1 text-kpi text-numeric">
        {value}
        {unit ? (
          <span className="text-section font-normal text-muted-foreground">{unit}</span>
        ) : null}
      </span>
      {children}
    </>
  )
  return (
    <Card className="min-w-0">
      {href ? (
        <Link
          href={href}
          className={`${BODY} outline-none hover:bg-surface-alt focus-visible:ring-2 focus-visible:ring-primary`}
        >
          {content}
        </Link>
      ) : (
        <div className={BODY}>{content}</div>
      )}
    </Card>
  )
}

export { KpiTile, type KpiTileProps }
