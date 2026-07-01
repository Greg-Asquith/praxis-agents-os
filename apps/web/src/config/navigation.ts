// apps/web/src/config/navigation.ts

import {
  BlocksIcon,
  LayoutDashboardIcon,
  type LucideIcon,
  SettingsIcon,
  UsersIcon,
} from "lucide-react"

type NavigationItem =
  | {
      label: string
      to: string
      icon: LucideIcon
      disabled: false
    }
  | {
      label: string
      to: null
      icon: LucideIcon
      disabled: true
    }

export const mainNavigation: NavigationItem[] = [
  {
    label: "Home",
    to: "/",
    icon: LayoutDashboardIcon,
    disabled: false,
  },
  {
    label: "Agents",
    to: "/agents",
    icon: BlocksIcon,
    disabled: false,
  },
  {
    label: "Workspaces",
    to: "/workspaces",
    icon: UsersIcon,
    disabled: false,
  },
  {
    label: "Settings",
    to: "/workspace-settings",
    icon: SettingsIcon,
    disabled: false,
  },
] as const
