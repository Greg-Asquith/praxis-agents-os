// apps/web/src/features/files/routes/files-route.tsx

import { useNavigate, useRouterState } from "@tanstack/react-router"
import { FileTextIcon, HardDriveIcon, Loader2Icon } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { MetricCard } from "@/components/ui/metric-card"
import { useFilesQuery } from "@/features/files/api/list-files"
import { FileDetailSheet } from "@/features/files/components/file-detail-sheet"
import { FileUploadButton } from "@/features/files/components/file-upload-button"
import { FilesTable } from "@/features/files/components/files-table"
import type { WorkspaceFile } from "@/features/files/types"
import { formatBytes, pluralize } from "@/lib/format"

type FilesSearch = {
  fileId?: string
}

export function FilesRoute() {
  const { data } = useFilesQuery({ limit: 100 })
  const search = useRouterState({
    select: (state): FilesSearch => state.location.search,
  })
  const navigate = useNavigate()
  const metrics = fileMetrics(data.files)

  function setOpenFile(fileId: string | null) {
    void navigate({
      to: "/files",
      search: fileId ? { fileId } : {},
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Workspace</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Files</h1>
        </div>
        <FileUploadButton />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          description={`${String(data.total)} ${pluralize(data.total, "file")} in this workspace`}
          icon={<FileTextIcon className="size-4" />}
          title="Total files"
        />
        <MetricCard
          description={`${formatBytes(metrics.totalBytes)} stored across current revisions`}
          icon={<HardDriveIcon className="size-4" />}
          title="Current size"
        />
        <MetricCard
          description={`${String(metrics.inFlight)} ${pluralize(metrics.inFlight, "file")} pending or processing`}
          icon={<Loader2Icon className="size-4" />}
          title="Processing"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace files</CardTitle>
          <CardDescription>
            Upload, inspect, and restore durable files shared with agents in this workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FilesTable
            files={data.files}
            onOpenFile={(fileId) => {
              setOpenFile(fileId)
            }}
          />
        </CardContent>
      </Card>

      <FileDetailSheet
        fileId={search.fileId ?? null}
        onClose={() => {
          setOpenFile(null)
        }}
      />
    </div>
  )
}

function fileMetrics(files: WorkspaceFile[]) {
  return files.reduce(
    (metrics, file) => {
      metrics.totalBytes += file.size_bytes
      if (file.processing_status === "pending" || file.processing_status === "processing") {
        metrics.inFlight += 1
      }
      return metrics
    },
    { inFlight: 0, totalBytes: 0 }
  )
}
