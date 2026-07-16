// apps/web/src/features/workspaces/components/workspaces-table.tsx

import { Link } from "@tanstack/react-router"
import { BriefcaseBusinessIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { CreateWorkspaceDialog } from "@/features/workspaces/components/create-workspace-dialog"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { workspaceStatusLabel } from "@/features/workspaces/format"
import type { Workspace } from "@/features/workspaces/types"
import { formatDateTime } from "@/lib/format"

export function WorkspacesTable({ workspaces }: { workspaces: Workspace[] }) {
  const { workspace: activeWorkspace, setWorkspaceBySlug } = useActiveWorkspace()

  if (workspaces.length === 0) {
    return (
      <EmptyState
        action={<CreateWorkspaceDialog />}
        description="Create a workspace to separate access and audit records for a team."
        icon={<BriefcaseBusinessIcon className="size-5" />}
        size="compact"
        title="No workspaces yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {workspaces.map((workspace) => (
          <WorkspaceMobileRow
            key={workspace.id}
            activeWorkspaceId={activeWorkspace.id}
            onManage={() => {
              setWorkspaceBySlug(workspace.slug)
            }}
            workspace={workspace}
          />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workspaces.map((workspace) => (
              <TableRow key={workspace.id}>
                <TableCell>
                  <div className="flex min-w-0 items-center gap-3">
                    <WorkspaceIcon workspace={workspace} />
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="font-medium">{workspace.name}</span>
                      <span className="text-muted-foreground text-xs">{workspace.slug}</span>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <WorkspaceRoleBadge role={workspace.current_user_role} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{workspaceStatusLabel(workspace.status)}</Badge>
                    {workspace.is_personal && <Badge variant="secondary">Personal</Badge>}
                    {activeWorkspace.id === workspace.id && <Badge>Active</Badge>}
                  </div>
                </TableCell>
                <TableCell>{formatDateTime(workspace.created_at)}</TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setWorkspaceBySlug(workspace.slug)
                    }}
                    render={<Link to="/workspace-settings" />}
                  >
                    Manage
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function WorkspaceMobileRow({
  activeWorkspaceId,
  onManage,
  workspace,
}: {
  activeWorkspaceId: string
  onManage: () => void
  workspace: Workspace
}) {
  const isActive = activeWorkspaceId === workspace.id

  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <WorkspaceIcon size="lg" workspace={workspace} />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{workspace.name}</p>
            <p className="text-muted-foreground truncate text-xs">{workspace.slug}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline">{workspaceStatusLabel(workspace.status)}</Badge>
              {workspace.is_personal && <Badge variant="secondary">Personal</Badge>}
              {isActive && <Badge>Active</Badge>}
            </div>
          </div>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Role">
            <WorkspaceRoleBadge role={workspace.current_user_role} />
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Created">
            {formatDateTime(workspace.created_at)}
          </ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          variant="outline"
          onClick={onManage}
          render={<Link to="/workspace-settings" />}
        >
          Manage
        </Button>
      </div>
    </ResponsiveListItem>
  )
}
