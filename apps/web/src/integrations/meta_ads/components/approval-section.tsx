// apps/web/src/integrations/meta_ads/components/approval-section.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function MetaAdsApprovalSection({
  ariaLabel,
  tone = "neutral",
  warning,
  countLine,
  children,
}: {
  ariaLabel: string
  tone?: "neutral" | "spend"
  warning?: ReactNode
  countLine?: ReactNode
  children?: ReactNode
}) {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "@container grid min-w-0 gap-2 rounded-lg border px-3 py-2.5",
        tone === "spend" ? "border-warning/40 bg-warning/10" : "border-border bg-muted/35"
      )}
    >
      {warning ? <p className="text-warning-foreground text-sm font-medium">{warning}</p> : null}
      {countLine ? <p className="text-muted-foreground text-xs">{countLine}</p> : null}
      {children}
    </section>
  )
}
