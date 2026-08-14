// apps/web/src/features/skills/components/skill-documents-list.tsx

import { useMemo } from "react"
import { DownloadIcon, EyeIcon, Trash2Icon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import type { SkillDocument } from "@/features/skills/types"
import { formatBytes, formatDateTime } from "@/lib/format"

const columnHelper = createAppColumnHelper<SkillDocument>()

export function SkillDocumentsList({
  documents,
  isDeleting,
  onDelete,
  onDownload,
  onPreview,
}: {
  documents: SkillDocument[]
  isDeleting: boolean
  onDelete: (document: SkillDocument) => void
  onDownload: (document: SkillDocument) => void
  onPreview: (document: SkillDocument) => void
}) {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("name", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <span className="font-medium">{getValue()}</span>,
          meta: { label: "Name" },
        }),
        columnHelper.accessor("filename", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => (
            <span className="text-muted-foreground block max-w-48 truncate text-sm">
              {getValue()}
            </span>
          ),
          meta: { label: "File" },
        }),
        columnHelper.accessor("status", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => <DocumentStatusBadge document={row.original} />,
          meta: { label: "Status" },
        }),
        columnHelper.accessor("size_bytes", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatBytes(getValue()),
          meta: { label: "Size" },
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
            <div className="flex justify-end gap-1.5">
              <Button
                aria-label={`Preview ${row.original.name}`}
                disabled={row.original.status !== "ready"}
                onClick={() => {
                  onPreview(row.original)
                }}
                size="icon-sm"
                title="Preview"
                type="button"
                variant="outline"
              >
                <EyeIcon />
              </Button>
              <Button
                aria-label={`Download ${row.original.name}`}
                onClick={() => {
                  onDownload(row.original)
                }}
                size="icon-sm"
                title="Download"
                type="button"
                variant="outline"
              >
                <DownloadIcon />
              </Button>
              <Button
                aria-label={`Delete ${row.original.name}`}
                disabled={isDeleting}
                onClick={() => {
                  onDelete(row.original)
                }}
                size="icon-sm"
                type="button"
                variant="outline"
              >
                <Trash2Icon />
              </Button>
            </div>
          ),
          meta: { label: "Actions", labelClassName: "sr-only" },
        }),
      ]),
    [isDeleting, onDelete, onDownload, onPreview]
  )
  const table = useAppTable({ columns, data: documents, getRowId: (document) => document.name })

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {documents.map((document) => (
          <DocumentMobileRow
            document={document}
            isDeleting={isDeleting}
            key={document.name}
            onDelete={onDelete}
            onDownload={onDownload}
            onPreview={onPreview}
          />
        ))}
      </ResponsiveList>

      <table.AppTable>
        <SkillDocumentsDesktopTable />
      </table.AppTable>
    </div>
  )
}

function SkillDocumentsDesktopTable() {
  const table = useTableContext<SkillDocument>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <SkillDocumentHeaderCell />}
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
                  {() => <SkillDocumentBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function SkillDocumentHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function SkillDocumentBodyCell() {
  const cell = useCellContext()
  const isDateOrSize = cell.column.id === "size_bytes" || cell.column.id === "updated_at"
  return (
    <TableCell className={isDateOrSize ? "whitespace-nowrap" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function DocumentMobileRow({
  document,
  isDeleting,
  onDelete,
  onDownload,
  onPreview,
}: {
  document: SkillDocument
  isDeleting: boolean
  onDelete: (document: SkillDocument) => void
  onDownload: (document: SkillDocument) => void
  onPreview: (document: SkillDocument) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{document.name}</p>
            <p className="text-muted-foreground truncate text-xs">{document.filename}</p>
          </div>
          <DocumentStatusBadge document={document} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Size">{formatBytes(document.size_bytes)}</ResponsiveListMeta>
          <ResponsiveListMeta label="Updated">
            {formatDateTime(document.updated_at)}
          </ResponsiveListMeta>
        </dl>

        <div className="grid gap-2 sm:grid-cols-3">
          <Button
            disabled={document.status !== "ready"}
            onClick={() => {
              onPreview(document)
            }}
            type="button"
            variant="outline"
          >
            <EyeIcon data-icon="inline-start" />
            Preview
          </Button>
          <Button
            onClick={() => {
              onDownload(document)
            }}
            type="button"
            variant="outline"
          >
            <DownloadIcon data-icon="inline-start" />
            Download
          </Button>
          <Button
            disabled={isDeleting}
            onClick={() => {
              onDelete(document)
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

function DocumentStatusBadge({ document }: { document: SkillDocument }) {
  return (
    <Badge
      title={document.status === "failed" ? (document.error ?? "Conversion failed") : undefined}
      variant={document.status === "ready" ? "default" : "destructive"}
    >
      {document.status === "ready" ? "Ready" : "Failed"}
    </Badge>
  )
}
