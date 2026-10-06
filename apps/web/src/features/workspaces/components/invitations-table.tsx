// apps/web/src/features/workspaces/components/invitations-table.tsx

import { useState } from "react"
import { filterFn_includesString } from "@tanstack/react-table"
import { MailPlusIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { useDeleteInvitationMutation } from "@/features/workspaces/api/delete-invitation"
import { useWorkspaceInvitationsQuery } from "@/features/workspaces/api/list-invitations"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { CreateInvitationDialog } from "@/features/workspaces/components/create-invitation-dialog"
import { WorkspaceRoleBadge } from "@/features/workspaces/components/workspace-role-badge"
import type { WorkspaceInvitationsListResponse } from "@/features/workspaces/types"
import { canManageWorkspace } from "@/features/workspaces/permissions"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

type WorkspaceInvitation = WorkspaceInvitationsListResponse["invitations"][number]

const columnHelper = createAppColumnHelper<WorkspaceInvitation>()

const columns = columnHelper.columns([
  columnHelper.accessor("email", {
    enableSorting: true,
    header: ({ header }) => <header.ColumnHeader />,
    meta: { label: "Email" },
  }),
  columnHelper.accessor("role", {
    enableSorting: true,
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <WorkspaceRoleBadge role={getValue()} />,
    meta: { label: "Role" },
  }),
  columnHelper.accessor("expires_at", {
    enableSorting: true,
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Expires" },
  }),
  columnHelper.accessor("created_at", {
    enableSorting: true,
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Created" },
  }),
])

export function InvitationsTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceInvitationsQuery(workspace.id)
  const revoke = useDeleteInvitationMutation()
  const [selected, setSelected] = useState<WorkspaceInvitation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const canRevoke = !workspace.is_personal && canManageWorkspace(workspace.current_user_role)
  const invitation = selected?.workspace_id === workspace.id ? selected : null

  function selectInvitation(invitation: WorkspaceInvitation) {
    setError(null)
    setSelected(invitation)
  }

  async function handleRevoke() {
    if (!invitation || !canRevoke || revoke.isPending) return
    setError(null)
    try {
      await revoke.mutateAsync({
        workspaceId: invitation.workspace_id,
        invitationId: invitation.id,
      })
      setSelected(null)
    } catch (cause) {
      setError(getErrorMessage(cause))
    }
  }

  return (
    <>
      <InvitationsTableContent
        invitations={data.invitations}
        workspaceName={workspace.name}
        onRevoke={canRevoke ? selectInvitation : undefined}
      />
      <ConfirmDialog
        open={invitation !== null && canRevoke}
        onOpenChange={(open) => {
          if (!open) setSelected(null)
        }}
        title="Revoke invitation?"
        description={
          <>
            {invitation
              ? `The invitation link for ${invitation.email} to join ${workspace.name} stops working.`
              : null}
            {error ? (
              <span role="alert" className="text-destructive mt-2 block">
                {error}
              </span>
            ) : null}
          </>
        }
        confirmLabel="Revoke invitation"
        confirmPendingLabel="Revoking…"
        isPending={revoke.isPending}
        onConfirm={handleRevoke}
      />
    </>
  )
}

export function InvitationsTableContent({
  invitations,
  workspaceName,
  onRevoke,
}: {
  invitations: WorkspaceInvitation[]
  workspaceName: string
  onRevoke?: ((invitation: WorkspaceInvitation) => void) | undefined
}) {
  const hasInvitations = invitations.length > 0
  const table = useAppTable({
    columns,
    data: invitations,
    enableMultiSort: false,
    globalFilterFn: filterFn_includesString,
    initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
  })

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Invitations</CardTitle>
        <CardDescription>Pending invitations for {workspaceName}.</CardDescription>
        {hasInvitations && onRevoke ? (
          <CardAction>
            <CreateInvitationDialog />
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {hasInvitations ? (
          <table.AppTable>
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <table.Search
                  ariaLabel="Search invitations"
                  className="w-full sm:max-w-sm"
                  placeholder="Search invitations…"
                />
                <table.SortMenu />
              </div>
              <ResponsiveList>
                {table.getRowModel().rows.map(({ original: invitation }) => (
                  <InvitationMobileRow
                    key={invitation.id}
                    invitation={invitation}
                    onRevoke={onRevoke}
                  />
                ))}
              </ResponsiveList>

              <InvitationsDesktopTable onRevoke={onRevoke} />
              {table.getRowModel().rows.length === 0 ? (
                <p className="text-muted-foreground py-6 text-center text-sm">
                  No invitations match your search.
                </p>
              ) : null}
              <table.Pagination ariaLabel="Invitations pagination" />
            </div>
          </table.AppTable>
        ) : (
          <EmptyState
            action={onRevoke ? <CreateInvitationDialog /> : undefined}
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

function InvitationsDesktopTable({
  onRevoke,
}: {
  onRevoke?: ((invitation: WorkspaceInvitation) => void) | undefined
}) {
  const table = useTableContext<WorkspaceInvitation>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <InvitationHeaderCell />}
                </table.AppHeader>
              ))}
              {onRevoke ? (
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
                  {() => <InvitationBodyCell />}
                </table.AppCell>
              ))}
              {onRevoke ? (
                <TableCell className="text-right">
                  <RevokeInvitationButton invitation={row.original} onRevoke={onRevoke} />
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function InvitationHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function InvitationBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell>
      <cell.FlexRender />
    </TableCell>
  )
}

function InvitationMobileRow({
  invitation,
  onRevoke,
}: {
  invitation: WorkspaceInvitation
  onRevoke?: ((invitation: WorkspaceInvitation) => void) | undefined
}) {
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
        {onRevoke ? <RevokeInvitationButton invitation={invitation} onRevoke={onRevoke} /> : null}
      </div>
    </ResponsiveListItem>
  )
}

function RevokeInvitationButton({
  invitation,
  onRevoke,
}: {
  invitation: WorkspaceInvitation
  onRevoke: (invitation: WorkspaceInvitation) => void
}) {
  return (
    <Button
      aria-label={`Revoke invitation for ${invitation.email}`}
      onClick={() => {
        onRevoke(invitation)
      }}
      size="sm"
      type="button"
      variant="outline"
    >
      Revoke
    </Button>
  )
}
