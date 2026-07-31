// apps/web/src/components/shell/app-shell.tsx

import { useCallback, type ReactNode } from "react"
import { useNavigate, useRouterState } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"

import { AppBreadcrumbs } from "@/components/shell/app-breadcrumbs"
import { MobileMenu } from "@/components/shell/mobile-menu"
import { PrimaryNavigation } from "@/components/shell/primary-navigation"
import { SidebarConversations } from "@/components/shell/sidebar-conversations"
import { SidebarFooter } from "@/components/shell/sidebar-footer"
import { SidebarHeader } from "@/components/shell/sidebar-header"
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher"
import { shouldRedirectHomeForWorkspaceSwitch } from "@/components/shell/workspace-switch-navigation"
import { Separator } from "@/components/ui/separator"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useLogoutMutation } from "@/features/auth/api/logout"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useRouterState({
    select: (state) => state.location,
  })
  const pathname = location.pathname
  const shouldRedirectForWorkspaceSwitch = shouldRedirectHomeForWorkspaceSwitch(
    pathname,
    location.search
  )
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data: conversationsData } = useConversationsQuery({ limit: 50 })
  const logoutMutation = useLogoutMutation()
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()

  const signOut = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSuccess: () => {
        window.location.replace("/login")
      },
    })
  }, [logoutMutation])

  const switchWorkspace = useCallback(
    (slug: string) => {
      if (slug === workspace.slug) {
        return
      }

      if (shouldRedirectForWorkspaceSwitch) {
        void navigate({ to: "/", replace: true }).then(() => {
          setWorkspaceBySlug(slug)
        })
        return
      }

      setWorkspaceBySlug(slug)
    },
    [navigate, setWorkspaceBySlug, shouldRedirectForWorkspaceSwitch, workspace.slug]
  )

  return (
    <div className="bg-sidebar text-foreground h-dvh overflow-hidden md:grid md:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="bg-sidebar text-sidebar-foreground hidden h-dvh min-h-0 md:flex md:flex-col">
        <SidebarHeader />

        <div className="flex min-h-0 flex-1 flex-col gap-3 border-t p-3">
          <PrimaryNavigation pathname={pathname} workspaceRole={workspace.current_user_role} />
          <Separator />
          <SidebarConversations
            conversations={conversationsData.conversations}
            pathname={pathname}
          />
        </div>

        <SidebarFooter user={user} onSignOut={signOut} />
      </aside>

      <div className="flex h-dvh min-h-0 min-w-0 flex-col p-0 md:pl-0">
        <div className="bg-background border-border/60 flex min-h-0 flex-1 flex-col overflow-hidden rounded-none border-0 shadow-none md:border md:shadow-sm">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b px-4">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <MobileMenu
                conversations={conversationsData.conversations}
                onSignOut={signOut}
                pathname={pathname}
                setWorkspaceBySlug={switchWorkspace}
                user={user}
                workspace={workspace}
                workspaces={workspaces}
              />
              <AppBreadcrumbs conversations={conversationsData.conversations} pathname={pathname} />
            </div>
            <div className="hidden shrink-0 md:block">
              <WorkspaceSwitcher
                setWorkspaceBySlug={switchWorkspace}
                workspace={workspace}
                workspaces={workspaces}
              />
            </div>
          </header>
          <main
            key={workspace.slug}
            className={cn(
              "min-h-0 min-w-0 flex-1",
              pathname !== "/conversations" && pathname.startsWith("/conversations/")
                ? "overflow-hidden"
                : "overflow-y-auto px-6 py-5"
            )}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
