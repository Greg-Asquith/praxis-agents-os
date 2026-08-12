// apps/web/src/features/workspaces/components/workspaces-table.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { BriefcaseBusinessIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
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
import { cn } from "@/lib/utils"

const columnHelper = createAppColumnHelper<Workspace>()

export function WorkspacesTable({ workspaces }: { workspaces: Workspace[] }) {
  const { workspace: activeWorkspace, setWorkspaceBySlug } = useActiveWorkspace()
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.display({
          id: "name",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex min-w-0 items-center gap-3">
              <WorkspaceIcon workspace={row.original} />
              <div className="flex min-w-0 flex-col gap-1">
                <span className="font-medium">{row.original.name}</span>
                <span className="text-muted-foreground text-xs">{row.original.slug}</span>
              </div>
            </div>
          ),
          meta: { label: "Name" },
        }),
        columnHelper.accessor("current_user_role", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <WorkspaceRoleBadge role={getValue()} />,
          meta: { label: "Role" },
        }),
        columnHelper.accessor("status", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <WorkspaceStatusBadges
              isActive={activeWorkspace.id === row.original.id}
              workspace={row.original}
            />
          ),
          meta: { label: "Status" },
        }),
        columnHelper.accessor("created_at", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatDateTime(getValue()),
          meta: { label: "Created" },
        }),
        columnHelper.display({
          id: "actions",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <Button
              onClick={() => {
                setWorkspaceBySlug(row.original.slug)
              }}
              render={<Link to="/workspace-settings" />}
              size="sm"
              variant="outline"
            >
              Manage
            </Button>
          ),
          meta: { label: "Actions", labelClassName: "sr-only" },
        }),
      ]),
    [activeWorkspace.id, setWorkspaceBySlug]
  )
  const table = useAppTable({ columns, data: workspaces })

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

      <table.AppTable>
        <WorkspacesDesktopTable />
      </table.AppTable>
    </div>
  )
}

function WorkspacesDesktopTable() {
  const table = useTableContext<Workspace>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <WorkspaceHeaderCell />}
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
                  {() => <WorkspaceBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function WorkspaceHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function WorkspaceBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
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
            <WorkspaceStatusBadges className="mt-2" isActive={isActive} workspace={workspace} />
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

function WorkspaceStatusBadges({
  className,
  isActive,
  workspace,
}: {
  className?: string
  isActive: boolean
  workspace: Workspace
}) {
  const statusLabel = workspaceStatusLabel(workspace.status)

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {!isActive || statusLabel !== "Active" ? (
        <Badge variant="outline">{statusLabel}</Badge>
      ) : null}
      {workspace.is_personal ? <Badge variant="secondary">Personal</Badge> : null}
      {isActive ? <Badge>Active</Badge> : null}
    </div>
  )
}
