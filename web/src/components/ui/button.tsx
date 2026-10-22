import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-md border border-transparent bg-clip-padding whitespace-nowrap transition-[filter,background-color,border-color] duration-[120ms] outline-none select-none hover:brightness-[.97] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:brightness-100 aria-disabled:cursor-not-allowed aria-disabled:opacity-40 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        // The DESIGN.md secondary button.
        outline:
          "border-border-strong bg-surface text-foreground aria-expanded:bg-surface-alt",
        secondary:
          "bg-secondary text-secondary-foreground aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost: "disabled:hover:bg-transparent hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 disabled:hover:bg-destructive/10 focus-visible:ring-destructive/40",
        link: "text-primary-text underline-offset-4 hover:underline disabled:hover:no-underline",
      },
      size: {
        // 32px, control type: the secondary button. The primary variant grows to 38px below.
        default:
          "h-8 gap-1.5 px-3 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-md px-2 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-md px-2.5 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-10 gap-1.5 px-4 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        icon: "size-8",
        "icon-xs": "size-6 rounded-md [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-7 rounded-md",
        "icon-lg": "size-9",
      },
    },
    compoundVariants: [
      {
        variant: "default",
        size: "default",
        className:
          "h-[38px] px-4 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
      },
    ],
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

/** Type classes sit outside cn(): its merge treats text-control and friends as colours. */
function buttonType(variant: string | null, size: string | null) {
  if (size === "xs") return "text-xs"
  if (size === "lg" || (size === "default" && variant === "default")) return "text-body-strong"
  if (size === "default" || size === "sm") return "text-control"
  return ""
}

function Button({
  className,
  variant = "default",
  size = "default",
  disabled,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={`${cn(buttonVariants({ variant, size, className }))} ${buttonType(variant, size)}`}
      disabled={disabled}
      aria-disabled={disabled ? true : undefined}
      {...props}
    />
  )
}

export { Button, buttonVariants }
