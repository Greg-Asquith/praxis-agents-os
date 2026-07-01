// apps/web/src/components/shell/workspace-switcher.tsx

import { ChevronDownIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import type { Workspace } from "@/features/workspaces/types"

export function WorkspaceSwitcher({
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
        render={<Button variant="ghost" className="h-9 w-56 justify-start gap-2 px-3" />}
      >
        <WorkspaceIcon size="sm" workspace={workspace} />
        <span className="min-w-0 truncate text-sm font-medium">{workspace.name}</span>
        <ChevronDownIcon data-icon="inline-end" className="text-muted-foreground ml-auto" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Switch workspace</DropdownMenuLabel>
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
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
