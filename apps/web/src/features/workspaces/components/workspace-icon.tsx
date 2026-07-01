// apps/web/src/features/workspaces/components/workspace-icon.tsx

import type { Workspace } from "@/features/workspaces/types"
import { initials } from "@/lib/format"
import { cn } from "@/lib/utils"

type WorkspaceIconSize = "sm" | "default" | "lg"

const sizeClasses: Record<WorkspaceIconSize, string> = {
  sm: "size-6 rounded-md text-xs",
  default: "size-8 rounded-lg text-sm",
  lg: "size-14 rounded-lg text-base",
}

export function WorkspaceIcon({
  className,
  size = "default",
  workspace,
}: {
  className?: string
  size?: WorkspaceIconSize
  workspace: Pick<Workspace, "icon_url" | "name">
}) {
  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground border-border relative inline-flex shrink-0 items-center justify-center overflow-hidden border font-medium",
        sizeClasses[size],
        className
      )}
    >
      {workspace.icon_url ? (
        <img alt="" className="size-full object-cover" src={workspace.icon_url} />
      ) : (
        initials(workspace.name)
      )}
    </span>
  )
}
