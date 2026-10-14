// apps/web/src/components/tool-ui/tool-heading.tsx

import type { LucideIcon } from "lucide-react"

export function ToolHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
