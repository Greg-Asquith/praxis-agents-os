// apps/web/src/features/knowledge/routes/document-detail-route.tsx

import { useParams, useSearch } from "@tanstack/react-router"
import { useSuspenseQueries, useSuspenseQuery } from "@tanstack/react-query"

import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { documentQueryOptions } from "@/features/knowledge/api/get-document"
import { platformDocumentQueryOptions } from "@/features/knowledge/api/platform-get-document"
import { DocumentDetailHeader } from "@/features/knowledge/components/document-detail-header"
import { DocumentMarkdownView } from "@/features/knowledge/components/document-markdown-view"
import { canEditWorkspace } from "@/features/workspaces/permissions"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function KnowledgeDocumentRoute() {
  const { documentId } = useParams({ from: "/app/knowledge/$documentId" })
  const { workspace } = useActiveWorkspace()
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const search = useSearch({ from: "/app/knowledge/$documentId" })
  const platformManagement = search.platform === true && user.is_super_admin
  const [{ data: document }] = useSuspenseQueries({
    queries: [
      platformManagement
        ? platformDocumentQueryOptions(documentId)
        : documentQueryOptions(documentId),
    ],
  })
  const canWrite = canEditWorkspace(workspace.current_user_role)

  return (
    <div className="flex flex-col gap-6">
      <DocumentDetailHeader
        canMakePrivate={
          canWrite && document.scope === "workspace" && document.created_by_user_id === user.id
        }
        canWrite={canWrite && document.scope === "workspace"}
        canCopy={canWrite && document.scope === "platform" && document.is_published}
        canManagePlatform={platformManagement && document.can_manage_platform}
        document={document}
      />
      <DocumentMarkdownView document={document} />
    </div>
  )
}
