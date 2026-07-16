// apps/web/src/components/shell/primary-navigation.tsx

import { Link } from "@tanstack/react-router"

import { navigationItemsForRole } from "@/config/navigation"
import { cn } from "@/lib/utils"

export function PrimaryNavigation({
  density = "default",
  pathname,
  workspaceRole,
}: {
  density?: "comfortable" | "default"
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
              className={cn(
                "text-muted-foreground flex items-center gap-2 rounded-lg px-2 text-sm opacity-60",
                density === "comfortable" ? "h-11" : "h-8"
              )}
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
              "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex items-center gap-2 rounded-lg px-2 text-sm transition-colors",
              density === "comfortable" ? "h-11" : "h-8",
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
