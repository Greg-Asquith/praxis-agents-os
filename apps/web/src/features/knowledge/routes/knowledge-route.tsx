// apps/web/src/features/knowledge/routes/knowledge-route.tsx

import { useTransition } from "react"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { useSuspenseQueries, useSuspenseQuery } from "@tanstack/react-query"

import { PageHeader } from "@/components/shell/page-header"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { documentsQueryOptions } from "@/features/knowledge/api/list-documents"
import { platformDocumentsQueryOptions } from "@/features/knowledge/api/platform-list-documents"
import { AddDocumentMenu } from "@/features/knowledge/components/add-document-menu"
import { DocumentsTable } from "@/features/knowledge/components/documents-table"
import { KnowledgeSearchPanel } from "@/features/knowledge/components/knowledge-search-panel"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { canEditWorkspace } from "@/features/workspaces/permissions"

const PAGE_SIZE = 25

export function KnowledgeRoute() {
  const { workspace } = useActiveWorkspace()
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const search = useSearch({ from: "/app/knowledge" })
  const navigate = useNavigate()
  const [isChangingView, startTransition] = useTransition()
  const scope = search.scope ?? "all"
  const platformManagement = scope === "platform" && user.is_super_admin
  const canWrite = canEditWorkspace(workspace.current_user_role)
  const canAdd = scope === "platform" ? platformManagement : canWrite
  const offset = ((search.page ?? 1) - 1) * PAGE_SIZE
  const params = { limit: PAGE_SIZE, offset }
  const [{ data }] = useSuspenseQueries({
    queries: [
      platformManagement
        ? platformDocumentsQueryOptions(params)
        : documentsQueryOptions({ ...params, ...(scope !== "all" ? { scope } : {}) }),
    ],
  })
  const addAction = canAdd ? <AddDocumentMenu platform={platformManagement} /> : undefined

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={addAction}
        description="Knowledge your agents can search and cite."
        title="Knowledge Base"
      />
      <KnowledgeSearchPanel />
      <Tabs
        value={scope}
        onValueChange={(value: unknown) => {
          if (value !== "all" && value !== "workspace" && value !== "platform") return
          startTransition(() => {
            void navigate({ to: "/knowledge", search: value === "all" ? {} : { scope: value } })
          })
        }}
      >
        <TabsList aria-label="Which knowledge to show">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger className="max-w-48" value="workspace">
            <span className="truncate">{workspace.name}</span>
          </TabsTrigger>
          <TabsTrigger value="platform">Shared</TabsTrigger>
        </TabsList>
      </Tabs>
      {scope === "platform" ? (
        <p className="text-muted-foreground max-w-xl text-sm">
          {platformManagement
            ? "Review each document after processing, then publish it to every workspace."
            : "Shared knowledge is available in every workspace. Make a workspace copy for your own changes."}
        </p>
      ) : null}
      <div aria-busy={isChangingView} className="flex flex-col gap-3">
        <DocumentsTable
          canWrite={canWrite}
          documents={data.documents}
          emptyAction={addAction}
          platform={scope === "platform"}
        />
        <PaginationControls
          disabled={isChangingView}
          limit={PAGE_SIZE}
          offset={offset}
          total={data.total}
          onPageChange={(nextOffset) => {
            startTransition(() => {
              void navigate({
                to: "/knowledge",
                search: { ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 },
              })
            })
          }}
        />
      </div>
    </div>
  )
}
