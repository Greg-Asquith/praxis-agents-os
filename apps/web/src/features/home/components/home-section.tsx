// apps/web/src/features/home/components/home-section.tsx

import type { ReactNode } from "react"

type HomeSectionProps = {
  action?: ReactNode
  children: ReactNode
  description: string
  icon: ReactNode
  title: string
}

export function HomeSection({ action, children, description, icon, title }: HomeSectionProps) {
  return (
    <section className="bg-card ring-foreground/10 overflow-hidden rounded-xl ring-1">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
            {icon}
          </span>
          <div className="min-w-0">
            <h2 className="font-heading text-sm font-medium">{title}</h2>
            <p className="text-muted-foreground mt-0.5 text-xs">{description}</p>
          </div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      <div className="p-2">{children}</div>
    </section>
  )
}
