// apps/web/src/components/shell/sidebar-header.tsx

import { appConfig } from "@/config/app"

export function SidebarHeader() {
  return (
    <div className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
      <div className="flex min-w-0 items-center gap-3 px-1">
        <div className="bg-sidebar-primary text-sidebar-primary-foreground flex size-8 items-center justify-center rounded-lg text-sm font-semibold">
          P
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{appConfig.shortName}</p>
          <p className="text-muted-foreground truncate text-xs">Agents OS</p>
        </div>
      </div>
    </div>
  )
}
