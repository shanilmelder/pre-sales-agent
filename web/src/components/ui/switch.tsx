"use client"

import * as React from "react"
import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

/** 44x26 switch with a visible On/Off label (colour never carries state alone). */
function Switch({
  className,
  checked,
  defaultChecked,
  onCheckedChange,
  ...props
}: SwitchPrimitive.Root.Props) {
  const [inner, setInner] = React.useState(defaultChecked ?? false)
  const isOn = checked ?? inner
  return (
    <span className="inline-flex items-center gap-2">
      <SwitchPrimitive.Root
        data-slot="switch"
        checked={isOn}
        onCheckedChange={(value, event) => {
          setInner(value)
          onCheckedChange?.(value, event)
        }}
        className={cn(
          "relative inline-flex h-[26px] w-11 shrink-0 cursor-pointer items-center rounded-full bg-border-strong p-[3px] transition-colors duration-[120ms] outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none data-checked:bg-primary data-disabled:cursor-not-allowed data-disabled:opacity-40",
          className
        )}
        {...props}
      >
        <SwitchPrimitive.Thumb
          data-slot="switch-thumb"
          className="block size-5 rounded-full bg-white transition-transform duration-[120ms] motion-reduce:transition-none data-checked:translate-x-[18px]"
        />
      </SwitchPrimitive.Root>
      <span data-slot="switch-label" className="text-foreground text-control">
        {isOn ? "On" : "Off"}
      </span>
    </span>
  )
}

export { Switch }
