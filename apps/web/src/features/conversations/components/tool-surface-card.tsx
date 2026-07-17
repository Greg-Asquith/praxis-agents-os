// apps/web/src/features/conversations/components/tool-surface-card.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function ToolSurfaceCard({
  accent = false,
  ariaLabel,
  children,
  footer,
  header,
  icon,
}: {
  accent?: boolean
  ariaLabel: string
  children: ReactNode
  footer?: ReactNode
  header: ReactNode
  icon: ReactNode
}) {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "bg-card w-full max-w-3xl min-w-0 overflow-hidden rounded-lg border shadow-xs",
        accent && "border-warning/40"
      )}
    >
      <div className="flex min-w-0 items-start gap-3 px-4 pt-4">
        <div className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
          {icon}
        </div>
        <div className="min-w-0 flex-1">{header}</div>
      </div>
      <div className="flex min-w-0 flex-col gap-3 px-4 py-4">{children}</div>
      {footer !== undefined ? (
        <div className="border-border/60 flex min-w-0 flex-col gap-2 border-t px-4 py-3">
          {footer}
        </div>
      ) : null}
    </section>
  )
}
