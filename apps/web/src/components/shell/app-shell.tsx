// apps/web/src/components/shell/app-shell.tsx

import { useCallback, type ReactNode } from "react"
import { Link, useNavigate, useRouterState } from "@tanstack/react-router"
import { ChevronDownIcon, LogOutIcon, MenuIcon, MessagesSquareIcon, UserIcon } from "lucide-react"
import { useSuspenseQuery } from "@tanstack/react-query"

import { AppBreadcrumbs } from "@/components/shell/app-breadcrumbs"
import { SidebarConversations } from "@/components/shell/sidebar-conversations"
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
import { appConfig } from "@/config/app"
import { mainNavigation } from "@/config/navigation"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useLogoutMutation } from "@/features/auth/api/logout"
import type { AuthUser } from "@/features/auth/types"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import type { Workspace } from "@/features/workspaces/types"
import { initials } from "@/lib/format"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data: conversationsData } = useConversationsQuery({ limit: 50 })
  const logoutMutation = useLogoutMutation()
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()

  const signOut = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSuccess: () => {
        void navigate({ to: "/login" })
      },
    })
  }, [logoutMutation, navigate])

  return (
    <div className="bg-background text-foreground h-dvh overflow-hidden md:grid md:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="bg-sidebar text-sidebar-foreground hidden h-dvh min-h-0 border-r md:flex md:flex-col">
        <SidebarHeader />

        <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
          <PrimaryNavigation pathname={pathname} />
          <Separator />
          <SidebarConversations
            conversations={conversationsData.conversations}
            pathname={pathname}
          />
        </div>

        <SidebarFooter user={user} onSignOut={signOut} />
      </aside>

      <div className="flex h-dvh min-h-0 min-w-0 flex-col">
        <header className="bg-background/95 sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <MobileMenu
              onSignOut={signOut}
              setWorkspaceBySlug={setWorkspaceBySlug}
              workspace={workspace}
              workspaces={workspaces}
            />
            <AppBreadcrumbs conversations={conversationsData.conversations} pathname={pathname} />
          </div>
          <div className="hidden w-60 shrink-0 md:block lg:w-72">
            <WorkspaceSwitcher
              setWorkspaceBySlug={setWorkspaceBySlug}
              workspace={workspace}
              workspaces={workspaces}
            />
          </div>
        </header>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  )
}

function SidebarHeader() {
  return (
    <div className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
      <div className="flex min-w-0 items-center gap-3 px-1">
        <div className="bg-sidebar-primary text-sidebar-primary-foreground flex size-8 items-center justify-center rounded-lg text-sm font-semibold">
          P
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{appConfig.shortName}</p>
          <p className="text-muted-foreground truncate text-xs">Agents OS</p>
        </div>
      </div>
    </div>
  )
}

function WorkspaceSwitcher({
  align = "end",
  setWorkspaceBySlug,
  workspace,
  workspaces,
}: {
  align?: "start" | "end"
  setWorkspaceBySlug: (slug: string) => void
  workspace: Workspace
  workspaces: Workspace[]
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" className="h-auto w-full justify-start px-2 py-2 text-left" />
        }
      >
        <WorkspaceIcon workspace={workspace} />
        <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
          <span className="max-w-full truncate text-sm font-medium">{workspace.name}</span>
          <span className="text-muted-foreground max-w-full truncate text-xs">
            Switch workspace
          </span>
        </span>
        <ChevronDownIcon data-icon="inline-end" className="ml-auto" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-64">
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
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function PrimaryNavigation({ pathname }: { pathname: string }) {
  return (
    <nav className="flex shrink-0 flex-col gap-1" aria-label="Primary">
      {mainNavigation.map((item) => {
        const Icon = item.icon

        if (item.disabled) {
          return (
            <span
              key={item.label}
              className="text-muted-foreground flex h-8 items-center gap-2 rounded-lg px-2 text-sm opacity-60"
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
              "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex h-8 items-center gap-2 rounded-lg px-2 text-sm transition-colors",
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

function SidebarFooter({ onSignOut, user }: { onSignOut: () => void; user: AuthUser }) {
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

function MobileMenu({
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

function isNavigationActive(pathname: string, itemPath: string) {
  if (itemPath === "/") {
    return pathname === "/"
  }

  return pathname === itemPath || pathname.startsWith(`${itemPath}/`)
}
