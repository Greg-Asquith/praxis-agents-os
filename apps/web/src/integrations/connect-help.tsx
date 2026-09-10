// apps/web/src/integrations/connect-help.tsx

import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export type ConnectHelpItem = {
  body: ReactNode
  icon: LucideIcon
  title: string
}

export function ConnectHelpCards({ items }: { items: ConnectHelpItem[] }) {
  return (
    <div
      className={cn(
        "border-border bg-muted/20 grid gap-4 rounded-xl border p-4",
        items.length > 2 ? "lg:grid-cols-3" : "sm:grid-cols-2"
      )}
    >
      {items.map((item) => (
        <div className="flex gap-3" key={item.title}>
          <item.icon aria-hidden="true" className="text-muted-foreground mt-0.5 size-4 shrink-0" />
          <div className="grid gap-1">
            <h2 className="text-sm font-medium">{item.title}</h2>
            <p className="text-muted-foreground text-sm">{item.body}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
