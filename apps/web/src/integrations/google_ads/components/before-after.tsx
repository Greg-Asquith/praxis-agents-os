// apps/web/src/integrations/google_ads/components/before-after.tsx

import type { ReactNode } from "react"
import { ArrowRightIcon } from "lucide-react"

export function GoogleAdsBeforeAfter({
  current,
  proposed,
  ariaLabel,
}: {
  current: ReactNode
  proposed: ReactNode
  ariaLabel: string
}) {
  return (
    <div
      aria-label={ariaLabel}
      role="group"
      className="border-border bg-muted/25 grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 rounded-md border px-3 py-2 tabular-nums"
    >
      <div className="min-w-0">
        <p className="text-muted-foreground text-[11px] leading-none">Current</p>
        <div className="mt-1 text-sm font-medium wrap-anywhere">{current}</div>
      </div>
      <span className="bg-background text-muted-foreground flex size-6 items-center justify-center rounded-full border">
        <ArrowRightIcon aria-hidden="true" className="size-3.5" />
      </span>
      <div className="min-w-0 text-right">
        <p className="text-muted-foreground text-[11px] leading-none">Proposed</p>
        <div className="mt-1 text-sm font-semibold wrap-anywhere">{proposed}</div>
      </div>
    </div>
  )
}
