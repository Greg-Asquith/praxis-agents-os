// apps/web/src/components/ui/stat.tsx

import * as React from "react"

import { cn } from "@/lib/utils"

export const microLabelClass = "text-muted-foreground text-xs font-medium tracking-wide uppercase"

export type StatTone = "success" | "warning" | "danger"

function StatGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="stat-group"
      className={cn(
        "divide-border grid grid-cols-2 gap-x-4 gap-y-4 sm:auto-cols-fr sm:grid-flow-col sm:grid-cols-none sm:gap-0 sm:divide-x sm:[&>*]:px-6 sm:[&>*:first-child]:pl-0",
        className
      )}
      {...props}
    />
  )
}

function Stat({
  className,
  footnote,
  label,
  size = "default",
  tone,
  value,
  ...props
}: React.ComponentProps<"div"> & {
  footnote?: React.ReactNode
  label: React.ReactNode
  size?: "default" | "lg"
  tone?: StatTone | undefined
  value: React.ReactNode
}) {
  return (
    <div data-slot="stat" data-size={size} className={cn("min-w-0", className)} {...props}>
      <div className={size === "lg" ? microLabelClass : "text-muted-foreground text-sm"}>
        {label}
      </div>
      <div
        className={cn(
          "mt-1 font-semibold tracking-tight tabular-nums",
          size === "lg" ? "text-3xl" : "text-2xl",
          statToneClass(tone)
        )}
      >
        {value}
      </div>
      {footnote ? <div className="text-muted-foreground mt-1 text-xs">{footnote}</div> : null}
    </div>
  )
}

function statToneClass(tone: StatTone | undefined): string | undefined {
  if (tone === "success") {
    return "text-success"
  }
  if (tone === "warning") {
    return "text-warning"
  }
  if (tone === "danger") {
    return "text-destructive"
  }
  return undefined
}

export { Stat, StatGroup }
