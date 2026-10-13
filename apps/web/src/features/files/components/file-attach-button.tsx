// apps/web/src/features/files/components/file-attach-button.tsx

import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { PaperclipIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { canAttachFile } from "@/features/files/chat-attachment"
import type { WorkspaceFile } from "@/features/files/types"
import { modelCatalogQueryOptions } from "@/features/models/api/list-model-catalog"

export function FileAttachButton({ file }: { file: WorkspaceFile }) {
  const { data: catalog } = useQuery(modelCatalogQueryOptions())
  if (!canAttachFile(file, catalog?.video_tools_available ?? false)) return null

  return (
    <Button
      nativeButton={false}
      render={<Link to="/conversations/new" search={{ file: file.id }} />}
      variant="outline"
    >
      <PaperclipIcon data-icon="inline-start" />
      Add to chat
    </Button>
  )
}
