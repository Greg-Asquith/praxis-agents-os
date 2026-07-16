// apps/web/src/components/shell/sidebar-footer.tsx

import { Link } from "@tanstack/react-router"
import { ChevronsUpDownIcon, LogOutIcon, SettingsIcon, UserIcon, UsersIcon } from "lucide-react"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Separator } from "@/components/ui/separator"
import type { AuthUser } from "@/features/auth/types"
import { initials } from "@/lib/format"

export function SidebarFooter({ onSignOut, user }: { onSignOut: () => void; user: AuthUser }) {
  return (
    <div className="shrink-0">
      <Separator />
      <div className="p-1">
        <UserMenu user={user} onSignOut={onSignOut} />
      </div>
    </div>
  )
}

function UserMenu({ onSignOut, user }: { onSignOut: () => void; user: AuthUser }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            className="hover:bg-sidebar-accent hover:text-sidebar-accent-foreground data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground dark:hover:bg-sidebar-accent h-auto w-full justify-start rounded-lg px-2 py-2 text-left"
          />
        }
      >
        <UserIdentity user={user} />
        <ChevronsUpDownIcon className="text-muted-foreground ml-auto size-4 shrink-0" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" sideOffset={6} className="w-(--anchor-width)">
        <div className="flex items-center gap-2 px-2 py-2">
          <UserIdentity user={user} />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem render={<Link to="/profile" />}>
            <UserIcon />
            Profile Settings
          </DropdownMenuItem>
          <DropdownMenuItem render={<Link to="/workspaces" />}>
            <UsersIcon />
            Workspaces
          </DropdownMenuItem>
          <DropdownMenuItem render={<Link to="/workspace-settings" />}>
            <SettingsIcon />
            Workspace Settings
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onSignOut}>
          <LogOutIcon />
          Sign Out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function UserIdentity({ user }: { user: AuthUser }) {
  return (
    <>
      <Avatar>
        {user.avatar_url && <AvatarImage src={user.avatar_url} />}
        <AvatarFallback>{initials(user.display_name ?? user.email)}</AvatarFallback>
      </Avatar>
      <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
        <span className="w-full truncate text-sm font-medium">
          {user.display_name ?? user.email}
        </span>
        <span className="text-muted-foreground w-full truncate text-xs font-normal">
          {user.email}
        </span>
      </span>
    </>
  )
}
