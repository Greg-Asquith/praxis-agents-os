// apps/web/src/components/tool-ui/kpi.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export type KpiTone = "neutral" | "success" | "warning" | "danger"

export type KpiItem = {
  label: string
  tone?: KpiTone
  value: ReactNode
}

export function KpiStrip({ items }: { items: KpiItem[] }) {
  return (
    <dl className="grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-2">
      {items.map((item) => (
        <div
          className={cn(
            "bg-muted/20 min-w-0 rounded-lg border px-3 py-2",
            toneClass(item.tone ?? "neutral")
          )}
          key={item.label}
        >
          <dt className="text-muted-foreground truncate text-xs">{item.label}</dt>
          <dd className="mt-1 font-mono text-lg font-medium tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function toneClass(tone: KpiTone): string {
  if (tone === "success") {
    return "border-success/35"
  }
  if (tone === "warning") {
    return "border-warning/40"
  }
  if (tone === "danger") {
    return "border-destructive/35"
  }
  return "border-border/70"
}
