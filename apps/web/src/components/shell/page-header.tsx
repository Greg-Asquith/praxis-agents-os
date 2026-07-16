// apps/web/src/components/shell/page-header.tsx

import type { ReactNode } from "react"

type PageHeaderProps = {
  actions?: ReactNode
  description?: ReactNode
  title: ReactNode
}

export function PageHeader({ actions, description, title }: PageHeaderProps) {
  return (
    <header className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
      <div className="min-w-0">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </header>
  )
}
