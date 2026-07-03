// apps/web/src/components/shell/primary-navigation.tsx

import { Link } from "@tanstack/react-router"

import { navigationItemsForRole } from "@/config/navigation"
import { cn } from "@/lib/utils"

export function PrimaryNavigation({
  pathname,
  workspaceRole,
}: {
  pathname: string
  workspaceRole: string | null
}) {
  return (
    <nav className="flex shrink-0 flex-col gap-1" aria-label="Primary">
      {navigationItemsForRole(workspaceRole).map((item) => {
        const Icon = item.icon

        if (item.disabled) {
          return (
            <span
              key={item.label}
              className="text-muted-foreground flex h-8 items-center gap-2 rounded-lg px-2 text-sm opacity-60"
            >
              <Icon className="size-4" />
              {item.label}
            </span>
          )
        }

        const isActive = isNavigationActive(pathname, item.to)

        return (
          <Link
            key={item.label}
            to={item.to}
            className={cn(
              "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex h-8 items-center gap-2 rounded-lg px-2 text-sm transition-colors",
              isActive && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
          >
            <Icon className="size-4" />
            {item.label}
          </Link>
        )
      })}
    </nav>
  )
}

function isNavigationActive(pathname: string, itemPath: string) {
  if (itemPath === "/") {
    return pathname === "/"
  }

  return pathname === itemPath || pathname.startsWith(`${itemPath}/`)
}
