// apps/web/src/components/shell/workspace-switcher.tsx

import { ChevronDownIcon } from "lucide-react"

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
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import type { Workspace } from "@/features/workspaces/types"
import { cn } from "@/lib/utils"

export function WorkspaceSwitcher({
  align = "end",
  className,
  contentClassName,
  setWorkspaceBySlug,
  workspace,
  workspaces,
}: {
  align?: "start" | "end"
  className?: string
  contentClassName?: string
  setWorkspaceBySlug: (slug: string) => void
  workspace: Workspace
  workspaces: Workspace[]
}) {
  const personalWorkspaces = workspaces.filter((item) => item.is_personal)
  const teamWorkspaces = workspaces.filter((item) => !item.is_personal)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" className={cn("h-9 w-56 justify-start gap-2 px-3", className)} />
        }
      >
        <WorkspaceIcon size="sm" workspace={workspace} />
        <span className="min-w-0 truncate text-sm font-medium">{workspace.name}</span>
        <ChevronDownIcon data-icon="inline-end" className="text-muted-foreground ml-auto" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className={cn("w-56", contentClassName)}>
        <DropdownMenuGroup>
          <DropdownMenuLabel>Switch Workspace</DropdownMenuLabel>
          {personalWorkspaces.length > 0 && (
            <WorkspaceMenuGroup
              label="Personal"
              setWorkspaceBySlug={setWorkspaceBySlug}
              workspaces={personalWorkspaces}
            />
          )}
          {personalWorkspaces.length > 0 && teamWorkspaces.length > 0 && <DropdownMenuSeparator />}
          {teamWorkspaces.length > 0 && (
            <WorkspaceMenuGroup
              label="Teams"
              setWorkspaceBySlug={setWorkspaceBySlug}
              workspaces={teamWorkspaces}
            />
          )}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function WorkspaceMenuGroup({
  label,
  setWorkspaceBySlug,
  workspaces,
}: {
  label: string
  setWorkspaceBySlug: (slug: string) => void
  workspaces: Workspace[]
}) {
  return (
    <>
      <DropdownMenuLabel className="pt-2">{label}</DropdownMenuLabel>
      {workspaces.map((item) => (
        <DropdownMenuItem
          key={item.id}
          className="gap-2 px-2 py-2"
          onClick={() => {
            setWorkspaceBySlug(item.slug)
          }}
        >
          <WorkspaceIcon size="sm" workspace={item} />
          <span className="truncate">{item.name}</span>
        </DropdownMenuItem>
      ))}
    </>
  )
}
