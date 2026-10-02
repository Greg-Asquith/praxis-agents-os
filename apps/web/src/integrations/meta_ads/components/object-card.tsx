// apps/web/src/integrations/meta_ads/components/object-card.tsx

import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"

export function MetaAdsObjectCard({
  title,
  typeLabel,
  meta,
  notes,
  href,
}: {
  title: ReactNode
  typeLabel: string
  meta?: ReactNode
  notes?: readonly string[]
  href?: string | null
}) {
  return (
    <div className="bg-card grid min-w-0 gap-1 rounded-md border px-2.5 py-2">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-medium wrap-anywhere">{title}</p>
        <Badge variant="secondary">{typeLabel}</Badge>
      </div>
      {meta ? <p className="text-muted-foreground text-xs wrap-anywhere">{meta}</p> : null}
      {notes?.map((note) => (
        <p key={note} className="text-sm">
          {note}
        </p>
      ))}
      {href ? <MetaAdsManagerLink href={href} /> : null}
    </div>
  )
}

export function MetaAdsManagerLink({ href }: { href: string }) {
  return (
    <a
      className="text-primary w-fit text-xs underline-offset-2 hover:underline"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      Open in Ads Manager
    </a>
  )
}
