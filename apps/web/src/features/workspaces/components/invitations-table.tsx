// apps/web/src/features/workspaces/components/invitations-table.tsx

import { MailPlusIcon } from "lucide-react"

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { useWorkspaceInvitationsQuery } from "@/features/workspaces/api/list-invitations"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { CreateInvitationDialog } from "@/features/workspaces/components/create-invitation-dialog"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import type { WorkspaceInvitationsListResponse } from "@/features/workspaces/types"
import { formatDateTime } from "@/lib/format"

type WorkspaceInvitation = WorkspaceInvitationsListResponse["invitations"][number]

export function InvitationsTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceInvitationsQuery(workspace.id)
  const hasInvitations = data.invitations.length > 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invitations</CardTitle>
        <CardDescription>Pending invitations for {workspace.name}.</CardDescription>
        {hasInvitations ? (
          <CardAction>
            <CreateInvitationDialog />
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {hasInvitations ? (
          <>
            <ResponsiveList>
              {data.invitations.map((invitation) => (
                <InvitationMobileRow key={invitation.id} invitation={invitation} />
              ))}
            </ResponsiveList>

            <div className="hidden md:block">
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
            </div>
          </>
        ) : (
          <EmptyState
            action={<CreateInvitationDialog />}
            description="Invite a teammate when they need access to this workspace."
            icon={<MailPlusIcon className="size-5" />}
            size="compact"
            title="No pending invitations"
          />
        )}
      </CardContent>
    </Card>
  )
}

function InvitationMobileRow({ invitation }: { invitation: WorkspaceInvitation }) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{invitation.email}</p>
          <p className="text-muted-foreground text-xs">Pending invitation</p>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Role">
            <WorkspaceRoleBadge role={invitation.role} />
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Expires">
            {formatDateTime(invitation.expires_at)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Created">
            {formatDateTime(invitation.created_at)}
          </ResponsiveListMeta>
        </dl>
      </div>
    </ResponsiveListItem>
  )
}
