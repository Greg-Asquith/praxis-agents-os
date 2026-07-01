// apps/web/src/features/workspaces/components/workspaces-table.tsx

import { Link } from "@tanstack/react-router"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import type { Workspace } from "@/features/workspaces/types"
import { formatDateTime } from "@/lib/format"

export function WorkspacesTable({ workspaces }: { workspaces: Workspace[] }) {
  const { workspace: activeWorkspace, setWorkspaceBySlug } = useActiveWorkspace()

  return (
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
                <Badge variant="outline">{workspace.status}</Badge>
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
  )
}
