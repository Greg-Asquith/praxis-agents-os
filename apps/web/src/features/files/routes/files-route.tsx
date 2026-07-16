// apps/web/src/features/files/routes/files-route.tsx

import { useNavigate, useRouterState } from "@tanstack/react-router"
import { PageHeader } from "@/components/shell/page-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useFilesQuery } from "@/features/files/api/list-files"
import { FileDetailSheet } from "@/features/files/components/file-detail-sheet"
import { FileUploadButton } from "@/features/files/components/file-upload-button"
import { FilesTable } from "@/features/files/components/files-table"

type FilesSearch = {
  fileId?: string
}

export function FilesRoute() {
  const { data } = useFilesQuery({ limit: 100 })
  const search = useRouterState({
    select: (state): FilesSearch => state.location.search,
  })
  const navigate = useNavigate()
  const hasFiles = data.files.length > 0

  function setOpenFile(fileId: string | null) {
    void navigate({
      to: "/files",
      search: fileId ? { fileId } : {},
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={hasFiles ? <FileUploadButton /> : null}
        description="Upload, inspect, and restore durable files shared with agents."
        title="Files"
      />

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
            emptyAction={<FileUploadButton />}
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
