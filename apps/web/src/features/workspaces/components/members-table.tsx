// apps/web/src/features/workspaces/components/members-table.tsx

import { UsersIcon } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
import { useWorkspaceMembershipsQuery } from "@/features/workspaces/api/list-memberships"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import type { WorkspaceMembershipsListResponse } from "@/features/workspaces/types"
import { formatDateTime } from "@/lib/format"

type WorkspaceMembership = WorkspaceMembershipsListResponse["memberships"][number]

export function MembersTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceMembershipsQuery(workspace.id)
  const hasMembers = data.memberships.length > 0

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>People who can access {workspace.name}.</CardDescription>
      </CardHeader>
      <CardContent>
        {hasMembers ? (
          <>
            <ResponsiveList>
              {data.memberships.map((membership) => (
                <MemberMobileRow key={membership.id} membership={membership} />
              ))}
            </ResponsiveList>

            <div className="hidden md:block">
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
                          <span className="font-medium">{memberDisplayName(membership)}</span>
                          {membership.user_email ? (
                            <span className="text-muted-foreground text-xs">
                              {membership.user_email}
                            </span>
                          ) : null}
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
            </div>
          </>
        ) : (
          <EmptyState
            description="Workspace members will appear here after they accept access."
            icon={<UsersIcon className="size-5" />}
            size="compact"
            title="No members yet"
          />
        )}
      </CardContent>
    </Card>
  )
}

function MemberMobileRow({ membership }: { membership: WorkspaceMembership }) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{memberDisplayName(membership)}</p>
          {membership.user_email ? (
            <p className="text-muted-foreground truncate text-xs">{membership.user_email}</p>
          ) : null}
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Role">
            <WorkspaceRoleBadge role={membership.role} />
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Added">
            {formatDateTime(membership.created_at)}
          </ResponsiveListMeta>
        </dl>
      </div>
    </ResponsiveListItem>
  )
}

function memberDisplayName(membership: WorkspaceMembership) {
  return membership.user_display_name ?? membership.user_email ?? "Unknown member"
}
