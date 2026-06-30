import { BlocksIcon, LayoutDashboardIcon, SettingsIcon, UsersIcon } from "lucide-react"

export const mainNavigation = [
  {
    label: "Home",
    to: "/",
    icon: LayoutDashboardIcon,
    disabled: false,
  },
  {
    label: "Agents",
    to: null,
    icon: BlocksIcon,
    disabled: true,
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
