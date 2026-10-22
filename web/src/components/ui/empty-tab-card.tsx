import Link from "next/link"
import * as React from "react"

import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardDescription, CardTitle } from "@/components/ui/card"

type EmptyTabCardProps = {
  title: string
  /** One sentence. */
  body: string
  /** The one primary button's label. */
  actionLabel?: string
  /** Jump to the tab that fixes the empty state. */
  href?: string
  /** Or run an action, such as opening the file chooser. */
  onClick?: () => void
}

/** The empty-tab state: a centred card, a title, one sentence and one primary button. */
function EmptyTabCard({ title, body, actionLabel, href, onClick }: EmptyTabCardProps) {
  return (
    <Card data-testid="empty-tab-card" className="mx-auto w-full max-w-md items-center gap-3 px-5 py-8 text-center">
      <CardTitle>{title}</CardTitle>
      <CardDescription>{body}</CardDescription>
      {actionLabel && href ? (
        <Link
          href={href}
          className={`${buttonVariants({ variant: "default" })} text-body-strong`}
        >
          {actionLabel}
        </Link>
      ) : actionLabel && onClick ? (
        <Button type="button" onClick={onClick}>
          {actionLabel}
        </Button>
      ) : null}
    </Card>
  )
}

export { EmptyTabCard, type EmptyTabCardProps }
