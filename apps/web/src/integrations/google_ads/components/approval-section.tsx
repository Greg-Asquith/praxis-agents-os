// apps/web/src/integrations/google_ads/components/approval-section.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function GoogleAdsApprovalSection({
  ariaLabel,
  tone = "neutral",
  title,
  countLine,
  children,
}: {
  ariaLabel: string
  tone?: "neutral" | "destructive"
  title?: ReactNode
  countLine?: ReactNode
  children?: ReactNode
}) {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "@container grid min-w-0 gap-2 rounded-lg border px-3 py-2.5",
        tone === "destructive"
          ? "border-destructive/35 bg-destructive/5"
          : "border-border bg-muted/35"
      )}
    >
      {title ? <p className="text-sm font-medium wrap-anywhere">{title}</p> : null}
      {countLine ? <p className="text-muted-foreground text-xs">{countLine}</p> : null}
      {tone === "destructive" ? (
        <p className="text-destructive text-xs font-medium">This action cannot be undone.</p>
      ) : null}
      {children}
    </section>
  )
}
