// apps/web/src/components/tool-ui/detail-list.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export type DetailItem = {
  label: string
  value: ReactNode
}

export function DetailList({ className, items }: { className?: string; items: DetailItem[] }) {
  return (
    <dl className={cn("grid min-w-0 gap-2 text-xs sm:grid-cols-2", className)}>
      {items.map((item) => (
        <div className="grid min-w-0 gap-0.5" key={item.label}>
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="min-w-0 wrap-break-word whitespace-pre-wrap">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
