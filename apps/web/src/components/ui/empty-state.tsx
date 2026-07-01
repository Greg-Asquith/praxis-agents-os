// apps/web/src/components/ui/empty-state.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type EmptyStateProps = {
  action?: ReactNode
  className?: string
  description: string
  icon?: ReactNode
  size?: "default" | "compact"
  title: string
}

export function EmptyState({
  action,
  className,
  description,
  icon,
  size = "default",
  title,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center",
        size === "compact" ? "min-h-40" : "min-h-72",
        className
      )}
    >
      {icon ? (
        <div className="bg-muted text-muted-foreground mb-4 flex size-10 items-center justify-center rounded-full">
          {icon}
        </div>
      ) : null}
      <h2 className="font-heading text-lg font-medium">{title}</h2>
      <p className="text-muted-foreground mt-2 max-w-sm text-sm">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}
