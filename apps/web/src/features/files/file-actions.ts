// apps/web/src/features/files/file-actions.ts

import { createFileDownload } from "@/features/files/api/download-file"

export type WorkspaceFileActionTarget = {
  fileId: string
  name: string
}

export async function openWorkspaceFile(
  file: WorkspaceFileActionTarget,
  { forceDownload }: { forceDownload: boolean }
) {
  const grant = await createFileDownload(file.fileId, { forceDownload })
  if (forceDownload) {
    triggerDownload(grant.download.url, file.name)
    return
  }

  window.open(grant.download.url, "_blank", "noopener,noreferrer")
}

function triggerDownload(url: string, filename: string) {
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.rel = "noopener noreferrer"
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}
