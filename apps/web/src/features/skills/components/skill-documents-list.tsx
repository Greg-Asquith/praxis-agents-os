// apps/web/src/features/skills/components/skill-documents-list.tsx

import { DownloadIcon, EyeIcon, Trash2Icon } from "lucide-react"

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

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>File</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((document) => (
              <TableRow key={document.name}>
                <TableCell className="font-medium">{document.name}</TableCell>
                <TableCell>
                  <span className="text-muted-foreground block max-w-48 truncate text-sm">
                    {document.filename}
                  </span>
                </TableCell>
                <TableCell>
                  <DocumentStatusBadge document={document} />
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {formatBytes(document.size_bytes)}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {formatDateTime(document.updated_at)}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <Button
                      aria-label={`Preview ${document.name}`}
                      disabled={document.status !== "ready"}
                      onClick={() => {
                        onPreview(document)
                      }}
                      size="icon-sm"
                      title="Preview"
                      type="button"
                      variant="outline"
                    >
                      <EyeIcon />
                    </Button>
                    <Button
                      aria-label={`Download ${document.name}`}
                      onClick={() => {
                        onDownload(document)
                      }}
                      size="icon-sm"
                      title="Download"
                      type="button"
                      variant="outline"
                    >
                      <DownloadIcon />
                    </Button>
                    <Button
                      aria-label={`Delete ${document.name}`}
                      disabled={isDeleting}
                      onClick={() => {
                        onDelete(document)
                      }}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
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
