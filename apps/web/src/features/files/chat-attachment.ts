// apps/web/src/features/files/chat-attachment.ts

import type { WorkspaceFile } from "@/features/files/types"

export function canAttachFile(file: WorkspaceFile) {
  return (
    (file.scope === "workspace" || file.is_published) &&
    (file.category === "editable_text" ||
      file.category === "ingestible_document" ||
      file.category === "image")
  )
}
