// apps/web/src/features/agents/routes/agents-route.tsx

import { useTransition } from "react"
import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { DebouncedSearchInput } from "@/components/forms/debounced-search-input"
import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentsTable } from "@/features/agents/components/agents-table"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"
import { normalisePagedSearch, type PagedSearch } from "@/lib/list-search"

const PAGE_SIZE = 25

export function AgentsRoute() {
  const search = useSearch({ from: "/app/agents" })
  const navigate = useNavigate()
  const [isChangingView, startTransition] = useTransition()
  const query = search.q ?? ""
  const offset = ((search.page ?? 1) - 1) * PAGE_SIZE
  const { data: agentsData } = useAgentsQuery({
    includeInactive: true,
    limit: PAGE_SIZE,
    offset,
    ...(query ? { search: query } : {}),
  })
  const { data: modelCatalog } = useModelCatalogQuery()
  const hasAgents = agentsData.total > 0 || query !== ""

  function navigateTo(next: PagedSearch) {
    startTransition(() => {
      void navigate({ to: "/agents", search: normalisePagedSearch(next) })
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasAgents ? (
            <Button render={<Link to="/agents/new" />}>
              <PlusIcon data-icon="inline-start" />
              New Agent
            </Button>
          ) : null
        }
        description="Create and manage the agents that work in this workspace."
        title="Agents"
      />

      {hasAgents ? (
        <DebouncedSearchInput
          ariaLabel="Search agents"
          disabled={isChangingView}
          onChange={(nextQuery) => {
            navigateTo({ q: nextQuery })
          }}
          placeholder="Search agents"
          value={query}
        />
      ) : null}

      <div aria-busy={isChangingView} className="flex min-w-0 flex-col gap-3">
        <AgentsTable agents={agentsData.agents} modelCatalog={modelCatalog} query={query} />
        {agentsData.total > 0 ? (
          <PaginationControls
            ariaLabel="Agents pagination"
            disabled={isChangingView}
            limit={PAGE_SIZE}
            offset={offset}
            onPageChange={(nextOffset) => {
              navigateTo({ ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 })
            }}
            total={agentsData.total}
          />
        ) : null}
      </div>
    </div>
  )
}
