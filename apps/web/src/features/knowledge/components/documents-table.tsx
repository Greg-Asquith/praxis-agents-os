// apps/web/src/features/knowledge/components/documents-table.tsx

import { useCallback, useMemo, useState, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { BookOpenIcon, LockIcon, RefreshCwIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { useReprocessDocumentMutation } from "@/features/knowledge/api/reprocess-document"
import { DocumentStatusBadge } from "@/features/knowledge/components/document-status-badge"
import { SourceTypeBadge } from "@/features/knowledge/components/source-type-badge"
import type { KbDocument } from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"
import { relativeDateTime } from "@/lib/format"

const columnHelper = createAppColumnHelper<KbDocument>()

export function DocumentsTable({
  canWrite,
  documents,
  emptyAction,
}: {
  canWrite: boolean
  documents: KbDocument[]
  emptyAction?: ReactNode
}) {
  const mutation = useReprocessDocumentMutation()
  const [error, setError] = useState<string | null>(null)

  const reprocess = useCallback(
    async (documentId: string) => {
      setError(null)
      try {
        await mutation.mutateAsync(documentId)
      } catch (mutationError) {
        setError(getErrorMessage(mutationError))
      }
    },
    [mutation]
  )

  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("title", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex max-w-md min-w-44 flex-col gap-1">
              <Link
                className="truncate font-medium hover:underline"
                params={{ documentId: row.original.id }}
                to="/knowledge/$documentId"
              >
                {row.original.title}
              </Link>
              <span className="text-muted-foreground text-xs">
                {row.original.chunk_count} {row.original.chunk_count === 1 ? "chunk" : "chunks"}
              </span>
            </div>
          ),
          meta: { label: "Title" },
        }),
        columnHelper.accessor("source_type", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <SourceTypeBadge sourceType={getValue()} />,
          meta: { label: "Source" },
        }),
        columnHelper.accessor("status", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => <StatusCell document={row.original} />,
          meta: { label: "Status" },
        }),
        columnHelper.accessor("is_private", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) =>
            getValue() ? (
              <span className="inline-flex items-center gap-1 text-sm">
                <LockIcon className="text-muted-foreground size-3.5" />
                Private
              </span>
            ) : (
              <span className="text-muted-foreground text-sm">Workspace</span>
            ),
          meta: { label: "Privacy" },
        }),
        columnHelper.accessor("updated_at", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => <span title={getValue()}>{relativeDateTime(getValue())}</span>,
          meta: { label: "Updated" },
        }),
        columnHelper.display({
          id: "actions",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) =>
            canWrite && row.original.status === "error" ? (
              <Button
                disabled={mutation.isPending}
                onClick={() => void reprocess(row.original.id)}
                size="sm"
                type="button"
                variant="outline"
              >
                <RefreshCwIcon data-icon="inline-start" />
                Reprocess
              </Button>
            ) : null,
          meta: { label: "Actions", labelClassName: "sr-only" },
        }),
      ]),
    [canWrite, mutation.isPending, reprocess]
  )
  const table = useAppTable({ columns, data: documents })

  if (documents.length === 0) {
    return (
      <EmptyState
        action={emptyAction}
        description="Add a document to give agents durable, searchable workspace knowledge."
        icon={<BookOpenIcon className="size-5" />}
        size="compact"
        title="No Knowledge Base documents yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn’t reprocess document</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <ResponsiveList>
        {documents.map((document) => (
          <ResponsiveListItem key={document.id}>
            <DocumentMobileRow
              canWrite={canWrite}
              document={document}
              isPending={mutation.isPending}
              onReprocess={reprocess}
            />
          </ResponsiveListItem>
        ))}
      </ResponsiveList>
      <table.AppTable>
        <DocumentsDesktopTable />
      </table.AppTable>
    </div>
  )
}

function DocumentsDesktopTable() {
  const table = useTableContext<KbDocument>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <DocumentHeaderCell />}
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
                  {() => <DocumentBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function DocumentHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function DocumentBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function StatusCell({ document }: { document: KbDocument }) {
  return (
    <div className="flex max-w-xs flex-col items-start gap-1">
      <DocumentStatusBadge status={document.status} />
      {document.status === "error" ? (
        <span
          className="text-destructive line-clamp-2 text-xs"
          title={document.processing_error ?? ""}
        >
          Attempt {document.processing_attempts}:{" "}
          {document.processing_error ?? "Processing failed without an error message."}
        </span>
      ) : document.status === "processing" && document.processing_attempts > 0 ? (
        <span className="text-muted-foreground text-xs">
          Attempt {document.processing_attempts}
        </span>
      ) : null}
    </div>
  )
}

function DocumentMobileRow({
  canWrite,
  document,
  isPending,
  onReprocess,
}: {
  canWrite: boolean
  document: KbDocument
  isPending: boolean
  onReprocess: (documentId: string) => Promise<void>
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <Link
          className="min-w-0 truncate font-medium hover:underline"
          params={{ documentId: document.id }}
          to="/knowledge/$documentId"
        >
          {document.title}
        </Link>
        <DocumentStatusBadge status={document.status} />
      </div>
      {document.status === "error" ? (
        <p className="text-destructive text-xs">
          Attempt {document.processing_attempts}:{" "}
          {document.processing_error ?? "Processing failed without an error message."}
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-3">
        <ResponsiveListMeta label="Source">
          <SourceTypeBadge sourceType={document.source_type} />
        </ResponsiveListMeta>
        <ResponsiveListMeta label="Privacy">
          {document.is_private ? "Private" : "Workspace"}
        </ResponsiveListMeta>
        <ResponsiveListMeta label="Chunks">{document.chunk_count}</ResponsiveListMeta>
        <ResponsiveListMeta label="Updated">
          {relativeDateTime(document.updated_at)}
        </ResponsiveListMeta>
      </dl>
      {canWrite && document.status === "error" ? (
        <Button
          className="w-full"
          disabled={isPending}
          onClick={() => void onReprocess(document.id)}
          type="button"
          variant="outline"
        >
          <RefreshCwIcon data-icon="inline-start" />
          Reprocess
        </Button>
      ) : null}
    </div>
  )
}
