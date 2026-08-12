// apps/web/src/features/workspaces/components/members-table.tsx

import { UsersIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
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
  const { data } = useWorkspaceMembershipsQuery(workspace.id)

  return <MembersTableContent memberships={data.memberships} workspaceName={workspace.name} />
}

export function MembersTableContent({
  memberships,
  workspaceName,
}: {
  memberships: WorkspaceMembership[]
  workspaceName: string
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
                <MemberMobileRow key={membership.id} membership={membership} />
              ))}
            </ResponsiveList>

            <table.AppTable>
              <MembersDesktopTable />
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

function MembersDesktopTable() {
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
