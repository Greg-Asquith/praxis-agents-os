// apps/web/src/features/home/components/home-section.tsx

import type { ReactNode } from "react"

import { microLabelClass } from "@/components/ui/stat"

type HomeSectionProps = {
  action?: ReactNode
  children: ReactNode
  description: string
  title: string
}

export function HomeSection({ action, children, description, title }: HomeSectionProps) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className={microLabelClass}>{title}</h2>
          <p className="text-muted-foreground mt-1 text-xs">{description}</p>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      <div className="min-w-0">{children}</div>
    </section>
  )
}
