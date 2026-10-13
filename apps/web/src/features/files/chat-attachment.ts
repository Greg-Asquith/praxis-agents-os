// apps/web/src/features/files/chat-attachment.ts

import type { WorkspaceFile } from "@/features/files/types"

// Chat accepts video only on deployments with tools that can find moments in it or cut it.
export function canAttachFile(file: WorkspaceFile, videoToolsAvailable: boolean) {
  return (
    (file.scope === "workspace" || file.is_published) &&
    (file.category === "editable_text" ||
      file.category === "ingestible_document" ||
      file.category === "image" ||
      (file.category === "video" && videoToolsAvailable))
  )
}
