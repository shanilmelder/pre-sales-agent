"use client"

import * as React from "react"
import { Avatar as AvatarPrimitive } from "@base-ui/react/avatar"
import { cn } from "cn"

type AvatarProps = AvatarPrimitive.Root.Props & {
  /** Humans are circles; agents are 6px-radius squares. */
  kind?: "human" | "agent"
}

function Avatar({ className, kind = "human", ...props }: AvatarProps) {
  return (
    <AvatarPrimitive.Root
      data-slot="avatar"
      data-kind={kind}
      className={`${cn(
        "relative inline-flex size-8 shrink-0 items-center justify-center overflow-hidden select-none",
        kind === "agent"
          ? "rounded-sm bg-agent-tint text-agent"
          : "rounded-full bg-surface-alt text-foreground",
        className
      )} text-label`}
      {...props}
    />
  )
}

function AvatarImage({ className, ...props }: AvatarPrimitive.Image.Props) {
  return (
    <AvatarPrimitive.Image
      data-slot="avatar-image"
      className={cn("size-full object-cover", className)}
      {...props}
    />
  )
}

/** Initials shown when there is no image. */
function AvatarFallback({ className, ...props }: AvatarPrimitive.Fallback.Props) {
  return (
    <AvatarPrimitive.Fallback
      data-slot="avatar-fallback"
      className={cn("flex size-full items-center justify-center uppercase", className)}
      {...props}
    />
  )
}

export { Avatar, AvatarImage, AvatarFallback }
