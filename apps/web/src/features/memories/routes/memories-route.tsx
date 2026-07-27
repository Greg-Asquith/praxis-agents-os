// apps/web/src/features/memories/routes/memories-route.tsx

import { useState } from "react"

import { PageHeader } from "@/components/shell/page-header"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useMemoriesQuery } from "@/features/memories/api/list-memories"
import {
  DEFAULT_MEMORY_FILTERS,
  type MemoryFilters,
} from "@/features/memories/components/memory-filters"
import { MemoryFilterBar } from "@/features/memories/components/memory-filter-bar"
import { MemoriesTable } from "@/features/memories/components/memories-table"
import { MemoryDetailDialog } from "@/features/memories/components/memory-detail-dialog"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

const PAGE_SIZE = 50

export function MemoriesRoute() {
  const { workspace } = useActiveWorkspace()
  const [filters, setFilters] = useState<MemoryFilters>(DEFAULT_MEMORY_FILTERS)
  const [offset, setOffset] = useState(0)
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null)
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data } = useMemoriesQuery({
    ...(filters.scope ? { scope: filters.scope } : {}),
    ...(filters.kind ? { kind: filters.kind } : {}),
    ...(filters.memoryType ? { memoryType: filters.memoryType } : {}),
    ...(filters.agentId ? { agentId: filters.agentId } : {}),
    status: filters.status,
    limit: PAGE_SIZE,
    offset,
  })
  const role = workspace.current_user_role
  const canEdit = role !== null && role !== "read_only"
  const isManager = role === "owner" || role === "admin"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description="Review, correct, and remove durable details agents have saved while working."
        title="Memory"
      />
      <MemoryFilterBar
        agents={agentsData.agents}
        filters={filters}
        onFiltersChange={(nextFilters) => {
          setFilters(nextFilters)
          setOffset(0)
        }}
      />
      <MemoriesTable
        limit={PAGE_SIZE}
        memories={data.memories}
        offset={offset}
        onOpen={setSelectedMemoryId}
        onPageChange={setOffset}
        total={data.total}
      />
      {selectedMemoryId ? (
        <MemoryDetailDialog
          canEdit={canEdit}
          isManager={isManager}
          memoryId={selectedMemoryId}
          onMemoryIdChange={setSelectedMemoryId}
          onOpenChange={(open) => {
            if (!open) {
              setSelectedMemoryId(null)
            }
          }}
          open
        />
      ) : null}
    </div>
  )
}
