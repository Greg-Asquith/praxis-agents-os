// apps/web/src/features/workspaces/components/members-table.tsx

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useWorkspaceMembershipsQuery } from "@/features/workspaces/api/list-memberships"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { formatDateTime } from "@/lib/format"

export function MembersTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceMembershipsQuery(workspace.id)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>People who can access {workspace.name}.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Added</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.memberships.map((membership) => (
              <TableRow key={membership.id}>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">
                      {membership.user_display_name ?? membership.user_email}
                    </span>
                    <span className="text-muted-foreground text-xs">{membership.user_email}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <WorkspaceRoleBadge role={membership.role} />
                </TableCell>
                <TableCell>{formatDateTime(membership.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
