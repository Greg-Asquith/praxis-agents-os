// apps/web/src/features/workspaces/components/members-table.tsx

import { useState, type ReactNode } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"
import { UsersIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
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
import { useDeleteMembershipMutation } from "@/features/workspaces/api/delete-membership"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import type { WorkspaceMembershipsListResponse } from "@/features/workspaces/types"
import { canRemoveWorkspaceMembers } from "@/features/workspaces/permissions"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

type WorkspaceMembership = WorkspaceMembershipsListResponse["memberships"][number]

const columnHelper = createAppColumnHelper<WorkspaceMembership>()

const columns = columnHelper.columns([
  columnHelper.display({
    id: "user",
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ row }) => (
      <div className="flex flex-col gap-1">
        <span className="font-medium">{memberDisplayName(row.original)}</span>
        {row.original.user_email ? (
          <span className="text-muted-foreground text-xs">{row.original.user_email}</span>
        ) : null}
      </div>
    ),
    meta: { label: "User" },
  }),
  columnHelper.accessor("role", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <WorkspaceRoleBadge role={getValue()} />,
    meta: { label: "Role" },
  }),
  columnHelper.accessor("created_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Added" },
  }),
])

export function MembersTable() {
  const { workspace } = useActiveWorkspace()
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data } = useWorkspaceMembershipsQuery(workspace.id)
  const remove = useDeleteMembershipMutation()
  const [selected, setSelected] = useState<WorkspaceMembership | null>(null)
  const [error, setError] = useState<string | null>(null)
  const canRemove = canRemoveWorkspaceMembers(workspace, user.is_super_admin)
  const member = selected?.workspace_id === workspace.id ? selected : null

  async function handleRemove() {
    if (!member || !canRemove || remove.isPending) return
    setError(null)
    try {
      await remove.mutateAsync({ workspaceId: member.workspace_id, membershipId: member.id })
      setSelected(null)
    } catch (cause) {
      setError(getErrorMessage(cause))
    }
  }

  return (
    <>
      <MembersTableContent
        memberships={data.memberships}
        workspaceName={workspace.name}
        currentUserId={user.id}
        onRemove={
          canRemove
            ? (membership) => {
                setError(null)
                setSelected(membership)
              }
            : undefined
        }
      />
      <ConfirmDialog
        open={member !== null && canRemove}
        onOpenChange={(open) => {
          if (!open) setSelected(null)
        }}
        title="Remove workspace member?"
        description={
          <>
            {member
              ? `${memberDisplayName(member)} (${member.user_email ?? "email unavailable"}) loses access to ${workspace.name}. Their account and access to other workspaces remain.`
              : null}
            {error ? (
              <span role="alert" className="text-destructive mt-2 block">
                {error}
              </span>
            ) : null}
          </>
        }
        confirmLabel="Remove member"
        confirmPendingLabel="Removing…"
        isPending={remove.isPending}
        onConfirm={handleRemove}
      />
    </>
  )
}

export function MembersTableContent({
  memberships,
  workspaceName,
  currentUserId,
  onRemove,
}: {
  memberships: WorkspaceMembership[]
  workspaceName: string
  currentUserId?: string | undefined
  onRemove?: ((membership: WorkspaceMembership) => void) | undefined
}) {
  const hasMembers = memberships.length > 0
  const table = useAppTable({ columns, data: memberships })

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>People who can access {workspaceName}.</CardDescription>
      </CardHeader>
      <CardContent>
        {hasMembers ? (
          <>
            <ResponsiveList>
              {memberships.map((membership) => (
                <MemberMobileRow key={membership.id} membership={membership}>
                  {onRemove && membership.user_id !== currentUserId ? (
                    <RemoveMemberButton membership={membership} onRemove={onRemove} />
                  ) : null}
                </MemberMobileRow>
              ))}
            </ResponsiveList>

            <table.AppTable>
              <MembersDesktopTable currentUserId={currentUserId} onRemove={onRemove} />
            </table.AppTable>
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

function MembersDesktopTable({
  currentUserId,
  onRemove,
}: {
  currentUserId?: string | undefined
  onRemove?: ((membership: WorkspaceMembership) => void) | undefined
}) {
  const table = useTableContext<WorkspaceMembership>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <MemberHeaderCell />}
                </table.AppHeader>
              ))}
              {onRemove ? (
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              ) : null}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <table.AppCell cell={cell} key={cell.id}>
                  {() => <MemberBodyCell />}
                </table.AppCell>
              ))}
              {onRemove ? (
                <TableCell className="text-right">
                  {row.original.user_id !== currentUserId ? (
                    <RemoveMemberButton membership={row.original} onRemove={onRemove} />
                  ) : null}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function MemberHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function MemberBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell>
      <cell.FlexRender />
    </TableCell>
  )
}

function RemoveMemberButton({
  membership,
  onRemove,
}: {
  membership: WorkspaceMembership
  onRemove: (membership: WorkspaceMembership) => void
}) {
  return (
    <Button
      aria-label={`Remove ${memberDisplayName(membership)} from workspace`}
      onClick={() => {
        onRemove(membership)
      }}
      size="sm"
      type="button"
      variant="outline"
    >
      Remove
    </Button>
  )
}

function MemberMobileRow({
  membership,
  children,
}: {
  membership: WorkspaceMembership
  children: ReactNode
}) {
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
        {children}
      </div>
    </ResponsiveListItem>
  )
}

function memberDisplayName(membership: WorkspaceMembership) {
  return membership.user_display_name ?? membership.user_email ?? "Unknown member"
}
