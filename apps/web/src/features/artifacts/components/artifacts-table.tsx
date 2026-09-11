// apps/web/src/features/artifacts/components/artifacts-table.tsx

import { useMemo, useState, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import type { OnChangeFn, PaginationState, SortingState } from "@tanstack/react-table"
import { ExternalLinkIcon, FileCode2Icon } from "lucide-react"

import {
  ACTIVATABLE_ROW_CLASS_NAME,
  handleRowKeyDown,
  stopRowClick,
} from "@/components/data-table/row-activation"
import {
  paginationStateFromServer,
  paginationStateToServer,
  resolveUpdater,
  sortingStateFromServer,
  sortingStateToServer,
} from "@/components/data-table/server-state"
import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { ResponsiveList, ResponsiveListItem } from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { createArtifactViewUrl } from "@/features/artifacts/api/create-view-url"
import { ArtifactBadges } from "@/features/artifacts/components/artifact-badges"
import { ArtifactTypeTile } from "@/features/artifacts/components/artifact-type-tile"
import { artifactTypeLabel } from "@/features/artifacts/format"
import { ARTIFACT_SORT_FIELDS } from "@/features/artifacts/search"
import type {
  ArtifactSortDirection,
  ArtifactSortField,
  ArtifactSummary,
  PlatformArtifactSummary,
} from "@/features/artifacts/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatCompactDate, formatDateTime, pluralize, relativeDateTime } from "@/lib/format"
import { openSignedResource } from "@/lib/open-signed-resource"

export type ArtifactRow = ArtifactSummary | PlatformArtifactSummary

const columnHelper = createAppColumnHelper<ArtifactRow>()

// The management list has a fixed order, so its columns render without sort controls.
function buildColumns(management: boolean) {
  const sortable = !management
  return columnHelper.columns([
    columnHelper.accessor("title", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ row }) => <ArtifactNameCell artifact={row.original} management={management} />,
      enableSorting: sortable,
      meta: { headClassName: "w-auto max-w-0", label: "Artifact" },
      sortDescFirst: false,
    }),
    columnHelper.accessor("version_count", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => <span className="text-muted-foreground">{getValue()}</span>,
      enableSorting: sortable,
      meta: { headClassName: "w-28", label: "Versions" },
      sortDescFirst: true,
    }),
    columnHelper.accessor("updated_at", {
      header: ({ header }) => <header.ColumnHeader />,
      cell: ({ getValue }) => (
        <span className="text-muted-foreground" title={formatDateTime(getValue())}>
          {formatCompactDate(getValue())}
        </span>
      ),
      enableSorting: sortable,
      meta: { headClassName: "w-32", label: "Updated" },
      sortDescFirst: true,
    }),
    columnHelper.display({
      id: "actions",
      header: ({ header }) => <header.ColumnHeader />,
      cell: () => null,
      meta: { headClassName: "w-14", label: "Actions", labelClassName: "sr-only" },
    }),
  ])
}

export function ArtifactsTable({
  artifacts,
  emptyAction,
  emptyDescription = "Artifacts created by agents will appear here with their complete version history.",
  emptyTitle = "No artifacts yet",
  isChangingView,
  limit,
  management = false,
  offset,
  onOpenArtifact,
  onPageChange,
  onSortChange,
  sortBy,
  sortDirection,
  total,
}: {
  artifacts: ArtifactRow[]
  emptyAction?: ReactNode
  emptyDescription?: string
  emptyTitle?: string
  isChangingView: boolean
  limit: number
  management?: boolean
  offset: number
  onOpenArtifact: (artifact: ArtifactRow) => void
  onPageChange: (offset: number) => void
  onSortChange: (sortBy: ArtifactSortField, direction: ArtifactSortDirection) => void
  sortBy: ArtifactSortField
  sortDirection: ArtifactSortDirection
  total: number
}) {
  const [error, setError] = useState<string | null>(null)
  const columns = useMemo(() => buildColumns(management), [management])
  const pagination = paginationStateFromServer({ limit, offset }, total)
  const sorting = sortingStateFromServer({ sort_by: sortBy, sort_direction: sortDirection })
  const table = useAppTable({
    columns,
    data: artifacts,
    enableSortingRemoval: false,
    manualPagination: true,
    manualSorting: true,
    onPaginationChange: ((updater) => {
      onPageChange(paginationStateToServer(resolveUpdater(updater, pagination)).offset)
    }) satisfies OnChangeFn<PaginationState>,
    onSortingChange: ((updater) => {
      const next = sortingStateToServer(resolveUpdater(updater, sorting), ARTIFACT_SORT_FIELDS, {
        sort_by: sortBy,
        sort_direction: sortDirection,
      })
      onSortChange(next.sort_by, next.sort_direction)
    }) satisfies OnChangeFn<SortingState>,
    rowCount: total,
    state: { pagination, sorting },
  })

  async function openArtifact(artifact: ArtifactRow) {
    setError(null)
    try {
      await openSignedResource(async () => {
        const grant = await createArtifactViewUrl(artifact.id, artifact.current_version_id)
        return grant.url
      })
    } catch (openError) {
      setError(getErrorMessage(openError))
    }
  }

  if (artifacts.length === 0 && total === 0) {
    return (
      <EmptyState
        action={emptyAction}
        description={emptyDescription}
        icon={<FileCode2Icon className="size-5" />}
        size="compact"
        title={emptyTitle}
      />
    )
  }

  return (
    <table.AppTable>
      <div aria-busy={isChangingView} className="flex max-w-full min-w-0 flex-col gap-3">
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
        {management ? null : <table.SortMenu className="md:hidden" disabled={isChangingView} />}
        <ResponsiveList className={isChangingView ? "opacity-60" : undefined}>
          {artifacts.map((artifact) => (
            <ArtifactMobileRow
              artifact={artifact}
              key={artifact.id}
              management={management}
              onOpen={openArtifact}
              onOpenArtifact={onOpenArtifact}
            />
          ))}
        </ResponsiveList>
        <div className="hidden max-w-full min-w-0 overflow-hidden md:block">
          <Table className="max-w-full table-fixed">
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <table.AppHeader header={header} key={header.id}>
                      {() => <ArtifactHeaderCell />}
                    </table.AppHeader>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody className={isChangingView ? "opacity-60" : undefined}>
              {table.getRowModel().rows.map((row) => (
                <ArtifactTableRow
                  artifact={row.original}
                  key={row.id}
                  onOpen={openArtifact}
                  onOpenArtifact={onOpenArtifact}
                />
              ))}
            </TableBody>
          </Table>
        </div>
        {total > 0 ? (
          <table.Pagination
            ariaLabel="Artifacts pagination"
            disabled={isChangingView}
            total={total}
          />
        ) : null}
      </div>
    </table.AppTable>
  )
}

function canOpen(artifact: ArtifactRow) {
  return artifact.scope === "workspace" || artifact.is_published
}

function ArtifactHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function ArtifactTableRow({
  artifact,
  onOpen,
  onOpenArtifact,
}: {
  artifact: ArtifactRow
  onOpen: (artifact: ArtifactRow) => Promise<void>
  onOpenArtifact: (artifact: ArtifactRow) => void
}) {
  const table = useTableContext<ArtifactRow>()
  const row = table.getRow(artifact.id)
  const open = () => {
    onOpenArtifact(artifact)
  }

  return (
    <TableRow
      aria-label={`Open details for ${artifact.title}`}
      className={ACTIVATABLE_ROW_CLASS_NAME}
      onClick={open}
      onKeyDown={(event) => {
        handleRowKeyDown(event, open)
      }}
      tabIndex={0}
    >
      {row.getVisibleCells().map((cell) => (
        <table.AppCell cell={cell} key={cell.id}>
          {() => <ArtifactBodyCell artifact={artifact} onOpen={onOpen} />}
        </table.AppCell>
      ))}
    </TableRow>
  )
}

function ArtifactBodyCell({
  artifact,
  onOpen,
}: {
  artifact: ArtifactRow
  onOpen: (artifact: ArtifactRow) => Promise<void>
}) {
  const cell = useCellContext()
  if (cell.column.id === "actions") {
    return (
      <TableCell className="w-14 text-right" onClick={stopRowClick}>
        {canOpen(artifact) ? <OpenButton artifact={artifact} onOpen={onOpen} /> : null}
      </TableCell>
    )
  }
  return (
    <TableCell className={cell.column.columnDef.meta?.headClassName}>
      <cell.FlexRender />
    </TableCell>
  )
}

function OpenButton({
  artifact,
  onOpen,
}: {
  artifact: ArtifactRow
  onOpen: (artifact: ArtifactRow) => Promise<void>
}) {
  return (
    <Button
      aria-label={`Open ${artifact.title}`}
      onClick={() => {
        void onOpen(artifact)
      }}
      size="icon-sm"
      type="button"
      variant="ghost"
    >
      <ExternalLinkIcon />
    </Button>
  )
}

function ArtifactNameCell({
  artifact,
  management,
  size = "md",
}: {
  artifact: ArtifactRow
  management: boolean
  size?: "sm" | "md"
}) {
  return (
    <div className="flex max-w-full min-w-0 items-center gap-3">
      <ArtifactTypeTile size={size} type={artifact.artifact_type} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <Link
            className="truncate font-medium hover:underline"
            onClick={stopRowClick}
            params={{ artifactId: artifact.id }}
            search={management ? { platform: true } : {}}
            to="/artifacts/$artifactId"
          >
            {artifact.title}
          </Link>
          <ArtifactBadges artifact={artifact} />
        </div>
        <p className="text-muted-foreground truncate text-xs">
          {artifactTypeLabel(artifact.artifact_type)}
        </p>
      </div>
    </div>
  )
}

function ArtifactMobileRow({
  artifact,
  management,
  onOpen,
  onOpenArtifact,
}: {
  artifact: ArtifactRow
  management: boolean
  onOpen: (artifact: ArtifactRow) => Promise<void>
  onOpenArtifact: (artifact: ArtifactRow) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <ArtifactNameCell artifact={artifact} management={management} size="sm" />
        <p className="text-muted-foreground text-xs">
          {artifact.version_count} {pluralize(artifact.version_count, "version")} · Updated{" "}
          {relativeDateTime(artifact.updated_at)}
        </p>
        <div className="grid grid-cols-2 gap-2">
          <Button
            onClick={() => {
              onOpenArtifact(artifact)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Details
          </Button>
          {canOpen(artifact) ? (
            <Button
              onClick={() => {
                void onOpen(artifact)
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              <ExternalLinkIcon data-icon="inline-start" />
              Open
            </Button>
          ) : null}
        </div>
      </div>
    </ResponsiveListItem>
  )
}
