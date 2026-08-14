// apps/web/src/features/workspaces/components/invitations-table.tsx

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

const columnHelper = createAppColumnHelper<WorkspaceInvitation>()

const columns = columnHelper.columns([
  columnHelper.accessor("email", {
    header: ({ header }) => <header.ColumnHeader />,
    meta: { label: "Email" },
  }),
  columnHelper.accessor("role", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => <WorkspaceRoleBadge role={getValue()} />,
    meta: { label: "Role" },
  }),
  columnHelper.accessor("expires_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Expires" },
  }),
  columnHelper.accessor("created_at", {
    header: ({ header }) => <header.ColumnHeader />,
    cell: ({ getValue }) => formatDateTime(getValue()),
    meta: { label: "Created" },
  }),
])

export function InvitationsTable() {
  const { workspace } = useActiveWorkspace()
  const { data } = useWorkspaceInvitationsQuery(workspace.id)
  const hasInvitations = data.invitations.length > 0
  const table = useAppTable({ columns, data: data.invitations })

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
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

            <table.AppTable>
              <InvitationsDesktopTable />
            </table.AppTable>
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

function InvitationsDesktopTable() {
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
