// apps/web/src/components/shell/app-shell.tsx

import type { ReactNode } from "react"
import { Link, useNavigate, useRouterState } from "@tanstack/react-router"
import { ChevronDownIcon, LogOutIcon, MenuIcon, UserIcon } from "lucide-react"
import { useSuspenseQuery } from "@tanstack/react-query"

import { appConfig } from "@/config/app"
import { mainNavigation } from "@/config/navigation"
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
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useLogoutMutation } from "@/features/auth/api/logout"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import { initials } from "@/lib/format"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const logoutMutation = useLogoutMutation()
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()

  function signOut() {
    logoutMutation.mutate(undefined, {
      onSuccess: () => {
        void navigate({ to: "/login" })
      },
    })
  }

  return (
    <div className="bg-background text-foreground min-h-screen md:grid md:grid-cols-[256px_minmax(0,1fr)]">
      <aside className="bg-sidebar text-sidebar-foreground hidden border-r md:flex md:min-h-screen md:flex-col">
        <div className="flex h-14 items-center gap-3 border-b px-4">
          <div className="bg-sidebar-primary text-sidebar-primary-foreground flex size-8 items-center justify-center rounded-lg text-sm font-semibold">
            P
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{appConfig.shortName}</p>
            <p className="text-muted-foreground truncate text-xs">Agents OS</p>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 p-3">
          <nav className="flex flex-col gap-1">
            {mainNavigation.map((item) => {
              const isActive = pathname === item.to
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
        </div>

        <div className="border-t p-3">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" className="h-auto w-full justify-start px-2 py-2" />}
            >
              <Avatar size="sm">
                {user.avatar_url && <AvatarImage src={user.avatar_url} />}
                <AvatarFallback>{initials(user.display_name ?? user.email)}</AvatarFallback>
              </Avatar>
              <span className="flex min-w-0 flex-col items-start gap-0.5">
                <span className="max-w-40 truncate text-sm font-medium">
                  {user.display_name ?? user.email}
                </span>
                <span className="text-muted-foreground max-w-40 truncate text-xs">
                  {user.email}
                </span>
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
                <DropdownMenuItem onClick={signOut}>
                  <LogOutIcon />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="bg-background/95 sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-2 md:hidden">
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="outline" size="icon" aria-label="Open menu" />}
              >
                <MenuIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-60">
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
                  <DropdownMenuLabel>Account</DropdownMenuLabel>
                  <DropdownMenuItem render={<Link to="/profile" />}>
                    <UserIcon />
                    Profile settings
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={signOut}>
                    <LogOutIcon />
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <WorkspaceIcon size="sm" workspace={workspace} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{appConfig.shortName}</p>
                  <p className="text-muted-foreground truncate text-xs">{workspace.name}</p>
                </div>
              </div>
            </div>
          </div>

          <div className="hidden min-w-0 md:block" />

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="outline" className="hidden h-auto justify-between px-3 py-2 md:flex" />
              }
            >
              <WorkspaceIcon size="sm" workspace={workspace} />
              <span className="max-w-44 truncate text-sm font-medium">{workspace.name}</span>
              <ChevronDownIcon data-icon="inline-end" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
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
        </header>
        <Separator />
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  )
}
