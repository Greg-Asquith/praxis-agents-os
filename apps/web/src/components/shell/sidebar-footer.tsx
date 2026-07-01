// apps/web/src/components/shell/sidebar-footer.tsx

import { Link } from "@tanstack/react-router"
import { LogOutIcon, UserIcon } from "lucide-react"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
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
      <div className="p-3">
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
          <Button variant="ghost" className="h-auto w-full justify-start px-2 py-2 text-left" />
        }
      >
        <Avatar>
          {user.avatar_url && <AvatarImage src={user.avatar_url} />}
          <AvatarFallback>{initials(user.display_name ?? user.email)}</AvatarFallback>
        </Avatar>
        <span className="flex min-w-0 flex-col items-start gap-0.5">
          <span className="max-w-48 truncate text-sm font-medium">
            {user.display_name ?? user.email}
          </span>
          <span className="text-muted-foreground max-w-48 truncate text-xs">{user.email}</span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Account</DropdownMenuLabel>
          <DropdownMenuItem render={<Link to="/profile" />}>
            <UserIcon />
            Profile settings
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={onSignOut}>
            <LogOutIcon />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
