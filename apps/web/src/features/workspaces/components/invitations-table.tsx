// apps/web/src/features/workspaces/components/invitations-table.tsx

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useWorkspaceInvitationsQuery } from "@/features/workspaces/api/list-invitations"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { CreateInvitationDialog } from "@/features/workspaces/components/create-invitation-dialog"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import { formatDateTime } from "@/lib/format"

export function InvitationsTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceInvitationsQuery(workspace.id)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invitations</CardTitle>
        <CardDescription>Pending invitations for {workspace.name}.</CardDescription>
        <CardAction>
          <CreateInvitationDialog />
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.invitations.map((invitation) => (
              <TableRow key={invitation.id}>
                <TableCell>{invitation.email}</TableCell>
                <TableCell>
                  <WorkspaceRoleBadge role={invitation.role} />
                </TableCell>
                <TableCell>{formatDateTime(invitation.expires_at)}</TableCell>
                <TableCell>{formatDateTime(invitation.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
