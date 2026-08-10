// apps/web/src/components/shell/primary-navigation.tsx

import { Link } from "@tanstack/react-router"

import { navigationItemsForRole, type NavigationItem } from "@/config/navigation"
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
  const navigationItems = navigationItemsForRole(workspaceRole)
  const activeLabel = activeNavigationLabel(pathname, navigationItems)

  return (
    <nav className="flex shrink-0 flex-col gap-1" aria-label="Primary">
      {navigationItems.map((item) => {
        const Icon = item.icon

        if (item.disabled) {
          return (
            <span
              key={item.label}
              className={cn(
                "text-muted-foreground flex items-center gap-2.5 rounded-sm px-2.5 text-sm opacity-60",
                density === "comfortable" ? "h-11" : "h-9"
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </span>
          )
        }

        const isActive = item.label === activeLabel

        return (
          <Link
            key={item.label}
            to={item.to}
            className={cn(
              "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex items-center gap-2.5 rounded-sm px-2.5 text-sm transition-colors",
              density === "comfortable" ? "h-11" : "h-9",
              isActive && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
          >
            <Icon
              className={cn(
                "text-muted-foreground size-4",
                isActive && "text-sidebar-accent-foreground"
              )}
            />
            {item.label}
          </Link>
        )
      })}
    </nav>
  )
}

function activeNavigationLabel(pathname: string, items: NavigationItem[]) {
  let activeLabel: string | null = null
  let activePrefixLength = -1

  for (const item of items) {
    if (item.disabled) {
      continue
    }

    for (const prefix of [item.to, ...(item.activeWhen ?? [])]) {
      const matches =
        prefix === "/" ? pathname === "/" : pathname === prefix || pathname.startsWith(`${prefix}/`)

      if (matches && prefix.length > activePrefixLength) {
        activeLabel = item.label
        activePrefixLength = prefix.length
      }
    }
  }

  return activeLabel
}
