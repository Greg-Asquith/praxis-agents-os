// apps/web/src/config/navigation.ts

import {
  BotIcon,
  CalendarClockIcon,
  LayoutDashboardIcon,
  LibraryBigIcon,
  PlugIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

export type NavigationItem =
  | {
      label: string
      to: string
      icon: LucideIcon
      disabled: false
      activeWhen?: readonly string[]
      managerOnly?: boolean
      customToolsOnly?: boolean
    }
  | {
      label: string
      to: null
      icon: LucideIcon
      disabled: true
      managerOnly?: boolean
    }

const mainNavigation: NavigationItem[] = [
  {
    label: "Home",
    to: "/",
    icon: LayoutDashboardIcon,
    disabled: false,
  },
  {
    label: "Agents",
    to: "/agents",
    icon: BotIcon,
    disabled: false,
  },
  {
    label: "Context",
    to: "/context",
    icon: LibraryBigIcon,
    disabled: false,
    activeWhen: [
      "/skills",
      "/memories",
      "/knowledge",
      "/files",
      "/artifacts",
      "/integrations/context-groups",
    ],
  },
  {
    label: "Schedules",
    to: "/schedules",
    icon: CalendarClockIcon,
    disabled: false,
  },
  {
    label: "Integrations",
    to: "/integrations",
    icon: PlugIcon,
    disabled: false,
  },
  {
    label: "Tools",
    to: "/tools",
    icon: WrenchIcon,
    disabled: false,
    customToolsOnly: true,
  },
] as const

export function navigationItemsForRole(role: string | null | undefined, hasCustomTools: boolean) {
  return mainNavigation.filter(
    (item) =>
      (!item.managerOnly || isWorkspaceManagerRole(role)) &&
      (item.disabled || !item.customToolsOnly || hasCustomTools)
  )
}

function isWorkspaceManagerRole(role: string | null | undefined) {
  return role === "owner" || role === "admin"
}
