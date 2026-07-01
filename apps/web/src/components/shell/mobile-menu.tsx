// apps/web/src/components/shell/mobile-menu.tsx

import { Link } from "@tanstack/react-router"
import {
  LogOutIcon,
  MenuIcon,
  MessageSquarePlusIcon,
  MessagesSquareIcon,
  UserIcon,
} from "lucide-react"

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
import { mainNavigation } from "@/config/navigation"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import type { Workspace } from "@/features/workspaces/types"

export function MobileMenu({
  onSignOut,
  setWorkspaceBySlug,
  workspace,
  workspaces,
}: {
  onSignOut: () => void
  setWorkspaceBySlug: (slug: string) => void
  workspace: Workspace
  workspaces: Workspace[]
}) {
  return (
    <div className="md:hidden">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="outline" size="icon" aria-label="Open menu" />}
        >
          <MenuIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Navigate</DropdownMenuLabel>
            {mainNavigation.map((item) => {
              const Icon = item.icon

              if (item.disabled) {
                return (
                  <DropdownMenuItem key={item.label} disabled>
                    <Icon />
                    {item.label}
                  </DropdownMenuItem>
                )
              }

              return (
                <DropdownMenuItem key={item.label} render={<Link to={item.to} />}>
                  <Icon />
                  {item.label}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Conversations</DropdownMenuLabel>
            <DropdownMenuItem render={<Link to="/conversations/new" />}>
              <MessageSquarePlusIcon />
              New Conversation
            </DropdownMenuItem>
            <DropdownMenuItem render={<Link to="/conversations" />}>
              <MessagesSquareIcon />
              Open conversations
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Switch workspace</DropdownMenuLabel>
            {workspaces.map((item) => (
              <DropdownMenuItem
                key={item.id}
                onClick={() => {
                  setWorkspaceBySlug(item.slug)
                }}
              >
                <WorkspaceIcon size="sm" workspace={item} />
                <span className="truncate">{item.name}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>{workspace.name}</DropdownMenuLabel>
            <DropdownMenuItem render={<Link to="/profile" />}>
              <UserIcon />
              Profile settings
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSignOut}>
              <LogOutIcon />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
