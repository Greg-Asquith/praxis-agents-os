// apps/web/src/features/files/file-actions.ts

import { createFileDownload } from "@/features/files/api/download-file"
import { openSignedResource } from "@/lib/open-signed-resource"

export type WorkspaceFileActionTarget = {
  fileId: string
  name: string
}

export async function openWorkspaceFile(
  file: WorkspaceFileActionTarget,
  { forceDownload }: { forceDownload: boolean }
) {
  if (forceDownload) {
    const grant = await createFileDownload(file.fileId, { forceDownload })
    triggerDownload(grant.download.url, file.name)
    return
  }

  await openSignedResource(async () => {
    const grant = await createFileDownload(file.fileId, { forceDownload })
    return grant.download.url
  })
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
