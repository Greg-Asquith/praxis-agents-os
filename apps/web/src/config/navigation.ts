// apps/web/src/config/navigation.ts

import {
  BotIcon,
  CalendarClockIcon,
  LayoutDashboardIcon,
  LibraryBigIcon,
  PlugIcon,
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
] as const

export function navigationItemsForRole(role: string | null | undefined) {
  return mainNavigation.filter((item) => !item.managerOnly || isWorkspaceManagerRole(role))
}

function isWorkspaceManagerRole(role: string | null | undefined) {
  return role === "owner" || role === "admin"
}
