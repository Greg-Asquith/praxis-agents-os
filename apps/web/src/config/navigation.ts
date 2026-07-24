// apps/web/src/config/navigation.ts

import {
  BotIcon,
  CalendarClockIcon,
  FilesIcon,
  LayoutDashboardIcon,
  LibraryIcon,
  PlugIcon,
  type LucideIcon,
  SparklesIcon,
} from "lucide-react"

type NavigationItem =
  | {
      label: string
      to: string
      icon: LucideIcon
      disabled: false
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
    label: "Skills",
    to: "/skills",
    icon: SparklesIcon,
    disabled: false,
  },
  {
    label: "Knowledge Base",
    to: "/knowledge",
    icon: LibraryIcon,
    disabled: false,
  },
  {
    label: "Files",
    to: "/files",
    icon: FilesIcon,
    disabled: false,
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
