// apps/web/src/integrations/google_ads/components/entity-card.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function GoogleAdsEntityCard({
  title,
  meta,
  trailing,
}: {
  title: ReactNode
  meta?: ReactNode
  trailing?: ReactNode
}) {
  return (
    <div
      className={cn(
        "bg-card grid min-w-0 gap-2 rounded-md border px-2.5 py-2",
        trailing != null && "sm:grid-cols-2 sm:items-center"
      )}
    >
      <div className="min-w-0">
        <p className="text-sm font-medium wrap-anywhere">{title}</p>
        {meta ? <p className="text-muted-foreground mt-0.5 text-xs wrap-anywhere">{meta}</p> : null}
      </div>
      {trailing != null ? <div className="min-w-0 text-sm wrap-anywhere">{trailing}</div> : null}
    </div>
  )
}

export function GoogleAdsEntityGroup({
  title,
  meta,
  children,
}: {
  title: ReactNode
  meta?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="border-border grid min-w-0 gap-2 rounded-lg border p-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium wrap-anywhere">{title}</p>
        {meta ? <p className="text-muted-foreground mt-0.5 text-xs wrap-anywhere">{meta}</p> : null}
      </div>
      {children}
    </section>
  )
}
