// apps/web/src/features/classifiers/components/classifiers-table.tsx

import { useMemo } from "react"
import { PencilIcon, PlusIcon, SparklesIcon, Trash2Icon } from "lucide-react"

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
import { classifierModelLabel } from "@/features/classifiers/format"
import type { Classifier } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import { formatDateTime } from "@/lib/format"

const columnHelper = createAppColumnHelper<Classifier>()

type ClassifiersTableProps = {
  classifiers: Classifier[]
  modelCatalog: ModelCatalogResponse
  onCreate: () => void
  onDelete: (classifier: Classifier) => void
  onEdit: (classifier: Classifier) => void
}

export function ClassifiersTable({
  classifiers,
  modelCatalog,
  onCreate,
  onDelete,
  onEdit,
}: ClassifiersTableProps) {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.display({
          id: "name",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex min-w-44 flex-col gap-1">
              <span className="font-medium">{row.original.display_name}</span>
              <code className="text-muted-foreground text-xs">classifier_{row.original.name}</code>
            </div>
          ),
          meta: { label: "Name" },
        }),
        columnHelper.display({
          id: "labels",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => {
            const labelCount = row.original.labels.length
            return categoryCountLabel(labelCount)
          },
          meta: { label: "Categories" },
        }),
        columnHelper.display({
          id: "model",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => classifierModelLabel(row.original, modelCatalog),
          meta: { label: "Model" },
        }),
        columnHelper.display({
          id: "status",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => <ClassifierStatusBadge classifier={row.original} />,
          meta: { label: "Status" },
        }),
        columnHelper.accessor("updated_at", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatDateTime(getValue()),
          meta: { label: "Updated" },
        }),
        columnHelper.display({
          id: "actions",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex justify-end gap-1">
              <Button
                aria-label={`Edit ${row.original.display_name}`}
                onClick={() => {
                  onEdit(row.original)
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <PencilIcon />
              </Button>
              <Button
                aria-label={`Delete ${row.original.display_name}`}
                onClick={() => {
                  onDelete(row.original)
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <Trash2Icon />
              </Button>
            </div>
          ),
          meta: { label: "Actions", labelClassName: "sr-only" },
        }),
      ]),
    [modelCatalog, onDelete, onEdit]
  )
  const table = useAppTable({ columns, data: classifiers })

  if (classifiers.length === 0) {
    return (
      <EmptyState
        action={
          <Button onClick={onCreate} type="button">
            <PlusIcon data-icon="inline-start" />
            New Classifier
          </Button>
        }
        description="Create a reusable set of categories and judging guidance for your agents."
        icon={<SparklesIcon className="size-5" />}
        size="compact"
        title="No classifiers yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {classifiers.map((classifier) => (
          <ClassifierMobileRow
            classifier={classifier}
            key={classifier.id}
            modelCatalog={modelCatalog}
            onDelete={onDelete}
            onEdit={onEdit}
          />
        ))}
      </ResponsiveList>

      <table.AppTable>
        <ClassifiersDesktopTable />
      </table.AppTable>
    </div>
  )
}

function ClassifiersDesktopTable() {
  const table = useTableContext<Classifier>()
  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <ClassifierHeaderCell />}
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
                  {() => <ClassifierBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ClassifierHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function ClassifierBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function ClassifierMobileRow({
  classifier,
  modelCatalog,
  onDelete,
  onEdit,
}: {
  classifier: Classifier
  modelCatalog: ModelCatalogResponse
  onDelete: (classifier: Classifier) => void
  onEdit: (classifier: Classifier) => void
}) {
  const labelCount = classifier.labels.length
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{classifier.display_name}</p>
            <code className="text-muted-foreground block truncate text-xs">
              classifier_{classifier.name}
            </code>
          </div>
          <ClassifierStatusBadge classifier={classifier} />
        </div>
        <p className="text-muted-foreground line-clamp-2 text-xs leading-5">
          {classifier.description}
        </p>
        <dl className="grid gap-3 sm:grid-cols-3">
          <ResponsiveListMeta label="Categories">
            {categoryCountLabel(labelCount)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Model">
            {classifierModelLabel(classifier, modelCatalog)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Updated">
            {formatDateTime(classifier.updated_at)}
          </ResponsiveListMeta>
        </dl>
        <div className="grid grid-cols-2 gap-2">
          <Button
            onClick={() => {
              onEdit(classifier)
            }}
            type="button"
            variant="outline"
          >
            <PencilIcon data-icon="inline-start" />
            Edit
          </Button>
          <Button
            onClick={() => {
              onDelete(classifier)
            }}
            type="button"
            variant="outline"
          >
            <Trash2Icon data-icon="inline-start" />
            Delete
          </Button>
        </div>
      </div>
    </ResponsiveListItem>
  )
}

function ClassifierStatusBadge({ classifier }: { classifier: Classifier }) {
  return (
    <Badge variant={classifier.is_active ? "success" : "outline"}>
      {classifier.is_active ? "Active" : "Inactive"}
    </Badge>
  )
}

function categoryCountLabel(count: number) {
  return `${String(count)} ${count === 1 ? "category" : "categories"}`
}
