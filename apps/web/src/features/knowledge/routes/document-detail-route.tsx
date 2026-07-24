// apps/web/src/features/knowledge/routes/document-detail-route.tsx

import { useParams } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"

import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useDocumentQuery } from "@/features/knowledge/api/get-document"
import { DocumentDetailHeader } from "@/features/knowledge/components/document-detail-header"
import { DocumentMarkdownView } from "@/features/knowledge/components/document-markdown-view"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function KnowledgeDocumentRoute() {
  const { documentId } = useParams({ from: "/app/knowledge/$documentId" })
  const { workspace } = useActiveWorkspace()
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data: document } = useDocumentQuery(documentId)
  const canWrite =
    workspace.current_user_role !== null && workspace.current_user_role !== "read_only"

  return (
    <div className="flex flex-col gap-6">
      <DocumentDetailHeader
        canMakePrivate={canWrite && document.created_by_user_id === user.id}
        canWrite={canWrite}
        document={document}
      />
      <DocumentMarkdownView document={document} />
    </div>
  )
}
