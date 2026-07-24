// apps/web/src/features/knowledge/routes/knowledge-route.tsx

import { PageHeader } from "@/components/shell/page-header"
import { useDocumentsQuery } from "@/features/knowledge/api/list-documents"
import { AddDocumentMenu } from "@/features/knowledge/components/add-document-menu"
import { DocumentsTable } from "@/features/knowledge/components/documents-table"
import { KnowledgeSearchPanel } from "@/features/knowledge/components/knowledge-search-panel"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function KnowledgeRoute() {
  const { workspace } = useActiveWorkspace()
  const canWrite =
    workspace.current_user_role !== null && workspace.current_user_role !== "read_only"
  const { data } = useDocumentsQuery({ limit: 100 })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={canWrite && data.documents.length > 0 ? <AddDocumentMenu /> : null}
        description="Build a searchable source of truth that agents can retrieve and cite."
        title="Knowledge Base"
      />
      <KnowledgeSearchPanel />
      <DocumentsTable
        canWrite={canWrite}
        documents={data.documents}
        emptyAction={canWrite ? <AddDocumentMenu /> : undefined}
      />
    </div>
  )
}
