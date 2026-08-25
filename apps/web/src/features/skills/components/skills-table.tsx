// apps/web/src/features/skills/components/skills-table.tsx

import { Link } from "@tanstack/react-router"
import type { OnChangeFn, PaginationState } from "@tanstack/react-table"
import { EyeIcon, PencilIcon, PlusIcon, SparklesIcon } from "lucide-react"
import { useMemo } from "react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import {
  paginationStateFromServer,
  paginationStateToServer,
} from "@/components/data-table/server-state"
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
import { skillDisplayName } from "@/features/skills/format"
import type { Skill } from "@/features/skills/types"
import { formatDateTime, pluralize } from "@/lib/format"

const columnHelper = createAppColumnHelper<Skill>()

function skillColumns(canManagePlatformSkills: boolean) {
  return columnHelper.columns([
    columnHelper.display({
      id: "name",
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => (
        <div className="flex min-w-40 flex-col gap-1">
          <Link
            className="font-medium hover:underline"
            params={{ skillId: row.original.id }}
            to="/skills/$skillId"
          >
            {skillDisplayName(row.original)}
          </Link>
          {row.original.scope === "platform" && !canManagePlatformSkills ? (
            <span className="text-muted-foreground text-xs">Managed by Admins</span>
          ) : null}
        </div>
      ),
      meta: { label: "Name" },
    }),
    columnHelper.accessor("description", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => (
        <span className="text-muted-foreground block max-w-md truncate text-sm">{getValue()}</span>
      ),
      meta: { label: "Description" },
    }),
    columnHelper.display({
      id: "documents",
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => {
        const documentCount = Object.keys(row.original.documentation_refs).length
        return `${String(documentCount)} ${pluralize(documentCount, "document")}`
      },
      meta: { label: "Documents" },
    }),
    columnHelper.display({
      id: "status",
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => <SkillStatusBadges skill={row.original} />,
      meta: { label: "Status" },
    }),
    columnHelper.accessor("last_used_at", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => formatDateTime(getValue()),
      meta: { label: "Last used" },
    }),
    columnHelper.display({
      id: "actions",
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => (
        <Button
          render={<Link params={{ skillId: row.original.id }} to="/skills/$skillId" />}
          size="sm"
          variant="outline"
        >
          {row.original.scope === "platform" && !canManagePlatformSkills ? (
            <EyeIcon data-icon="inline-start" />
          ) : (
            <PencilIcon data-icon="inline-start" />
          )}
          {row.original.scope === "platform" && !canManagePlatformSkills ? "View" : "Edit"}
        </Button>
      ),
      meta: { label: "Actions", labelClassName: "sr-only" },
    }),
  ])
}

export function SkillsTable({
  canManagePlatformSkills,
  limit,
  offset,
  onPageChange,
  skills,
  total,
}: {
  canManagePlatformSkills: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  skills: Skill[]
  total: number
}) {
  const columns = useMemo(() => skillColumns(canManagePlatformSkills), [canManagePlatformSkills])
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const table = useAppTable({
    columns,
    data: skills,
    manualPagination: true,
    onPaginationChange: ((updater) => {
      const nextPagination = typeof updater === "function" ? updater(pagination) : updater
      onPageChange(paginationStateToServer(nextPagination).offset)
    }) satisfies OnChangeFn<PaginationState>,
    rowCount: total,
    state: { pagination },
  })

  if (total === 0) {
    return (
      <EmptyState
        action={
          <Button render={<Link to="/skills/new" />}>
            <PlusIcon data-icon="inline-start" />
            New Skill
          </Button>
        }
        description="Create a skill to package instructions and reference documents your agents can activate on demand."
        icon={<SparklesIcon className="size-5" />}
        size="compact"
        title="No skills yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {skills.map((skill) => (
          <SkillMobileRow
            canManagePlatformSkills={canManagePlatformSkills}
            key={skill.id}
            skill={skill}
          />
        ))}
      </ResponsiveList>

      <table.AppTable>
        <SkillsDesktopTable />
        <table.Pagination ariaLabel="Skills pagination" total={total} />
      </table.AppTable>
    </div>
  )
}

function SkillsDesktopTable() {
  const table = useTableContext<Skill>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <SkillHeaderCell />}
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
                  {() => <SkillBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function SkillHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function SkillBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function SkillMobileRow({
  canManagePlatformSkills,
  skill,
}: {
  canManagePlatformSkills: boolean
  skill: Skill
}) {
  const documentCount = Object.keys(skill.documentation_refs).length

  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <p className="min-w-0 truncate font-medium">{skillDisplayName(skill)}</p>
          <SkillStatusBadges skill={skill} />
        </div>

        <p className="text-muted-foreground line-clamp-2 text-xs leading-5">{skill.description}</p>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Documents">
            {documentCount} {pluralize(documentCount, "document")}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Last used">
            {formatDateTime(skill.last_used_at)}
          </ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          variant="outline"
          render={<Link to="/skills/$skillId" params={{ skillId: skill.id }} />}
        >
          {skill.scope === "platform" && !canManagePlatformSkills ? (
            <EyeIcon data-icon="inline-start" />
          ) : (
            <PencilIcon data-icon="inline-start" />
          )}
          {skill.scope === "platform" && !canManagePlatformSkills ? "View" : "Edit"}
        </Button>
      </div>
    </ResponsiveListItem>
  )
}

function SkillStatusBadges({ skill }: { skill: Skill }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={skill.is_active ? "success" : "outline"}>
        {skill.is_active ? "Active" : "Inactive"}
      </Badge>
      {skill.scope === "platform" ? <Badge variant="secondary">Platform</Badge> : null}
      {skill.scope === "workspace" && skill.is_favorite ? (
        <Badge variant="outline">Favorite</Badge>
      ) : null}
    </div>
  )
}
