// apps/web/src/components/shell/mobile-menu.tsx

import { useState } from "react"
import { MenuIcon, XIcon } from "lucide-react"

import { PrimaryNavigation } from "@/components/shell/primary-navigation"
import { SidebarConversations } from "@/components/shell/sidebar-conversations"
import { SidebarFooter } from "@/components/shell/sidebar-footer"
import { SidebarHeader } from "@/components/shell/sidebar-header"
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher"
import { Button } from "@/components/ui/button"
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Separator } from "@/components/ui/separator"
import type { AuthUser } from "@/features/auth/types"
import type { Conversation } from "@/features/conversations/types"
import type { Workspace } from "@/features/workspaces/types"

type MobileMenuProps = {
  conversations: Conversation[]
  onSignOut: () => void
  pathname: string
  setWorkspaceBySlug: (slug: string) => void
  user: AuthUser
  workspace: Workspace
  workspaces: Workspace[]
}

export function MobileMenu(props: MobileMenuProps) {
  return (
    <div className="md:hidden">
      <MobileMenuDrawer key={props.pathname} {...props} />
    </div>
  )
}

function MobileMenuDrawer({
  conversations,
  onSignOut,
  pathname,
  setWorkspaceBySlug,
  user,
  workspace,
  workspaces,
}: MobileMenuProps) {
  const [open, setOpen] = useState(false)

  const switchWorkspace = (slug: string) => {
    setOpen(false)
    setWorkspaceBySlug(slug)
  }

  const signOut = () => {
    setOpen(false)
    onSignOut()
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button variant="outline" size="icon" aria-label="Open menu" />}>
        <MenuIcon />
      </SheetTrigger>
      <SheetContent
        side="left"
        showCloseButton={false}
        className="bg-sidebar text-sidebar-foreground h-dvh w-80 max-w-[85vw] gap-0 p-0 md:hidden"
        onClick={(event) => {
          if (
            !event.defaultPrevented &&
            event.target instanceof Element &&
            event.target.closest("a[href]")
          ) {
            setOpen(false)
          }
        }}
      >
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <div className="relative shrink-0">
          <SidebarHeader />
          <SheetClose
            render={
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close menu"
                className="absolute top-3 right-3"
              />
            }
          >
            <XIcon />
          </SheetClose>
        </div>

        <div className="shrink-0 border-t px-3 py-2">
          <WorkspaceSwitcher
            align="start"
            className="h-11 w-full"
            contentClassName="w-(--anchor-width)"
            setWorkspaceBySlug={switchWorkspace}
            workspace={workspace}
            workspaces={workspaces}
          />
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-3">
          <PrimaryNavigation
            density="comfortable"
            pathname={pathname}
            workspaceRole={workspace.current_user_role}
          />
          <Separator />
          <SidebarConversations conversations={conversations} pathname={pathname} />
        </div>

        <SidebarFooter user={user} onSignOut={signOut} />
      </SheetContent>
    </Sheet>
  )
}
