// apps/web/src/features/files/components/file-attach-button.tsx

import { Link } from "@tanstack/react-router"
import { PaperclipIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { canAttachFile } from "@/features/files/chat-attachment"
import type { WorkspaceFile } from "@/features/files/types"

export function FileAttachButton({ file }: { file: WorkspaceFile }) {
  if (!canAttachFile(file)) return null

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
