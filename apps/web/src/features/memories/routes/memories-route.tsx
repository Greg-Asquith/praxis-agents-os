// apps/web/src/features/memories/routes/memories-route.tsx

import { useEffect, useMemo, useState, useTransition } from "react"
import { Link } from "@tanstack/react-router"
import { BrainIcon, SearchXIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useMemoriesQuery } from "@/features/memories/api/list-memories"
import { MemoriesTable } from "@/features/memories/components/memories-table"
import { MemoryDetailDialog } from "@/features/memories/components/memory-detail-dialog"
import { MEMORY_AUDIENCE_LABELS } from "@/features/memories/components/memory-display"
import {
  DEFAULT_MEMORY_FILTERS,
  MEMORY_PAGE_SIZE,
  hasNarrowingFilters,
  memoryListParams,
  type MemoryFilters,
} from "@/features/memories/components/memory-filters"
import { MemorySettingsPopover } from "@/features/memories/components/memory-settings-popover"
import { MemoryToolbar } from "@/features/memories/components/memory-toolbar"
import type { MemoryAudience } from "@/features/memories/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { canEditWorkspace, canManageWorkspace } from "@/features/workspaces/permissions"
import { isOneOf } from "@/lib/guards"

const SEARCH_DEBOUNCE_MS = 300
const AUDIENCE_TABS = ["shared", "private"] as const
const AUDIENCE_SET: ReadonlySet<MemoryAudience> = new Set(AUDIENCE_TABS)

export function MemoriesRoute() {
  const { workspace } = useActiveWorkspace()
  const [isChangingView, startTransition] = useTransition()
  const [baseFilters, setBaseFilters] = useState<MemoryFilters>(DEFAULT_MEMORY_FILTERS)
  const [searchInput, setSearchInput] = useState("")
  const [q, setQ] = useState("")
  const [offset, setOffset] = useState(0)
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null)
  const filters = useMemo(() => ({ ...baseFilters, q }), [baseFilters, q])
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data } = useMemoriesQuery(memoryListParams(filters, offset))
  const role = workspace.current_user_role
  const narrowed = hasNarrowingFilters(filters)

  // Keeps the current rows on screen while a search loads.
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      startTransition(() => {
        setQ(searchInput.trim())
        setOffset(0)
      })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timeout)
    }
  }, [searchInput])

  function changeFilters(nextFilters: MemoryFilters) {
    startTransition(() => {
      setBaseFilters(nextFilters)
      setOffset(0)
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={canManageWorkspace(role) ? <MemorySettingsPopover workspace={workspace} /> : null}
        description={
          <>
            What your agents remember, where it came from, and how to correct it. For something an
            agent must always follow, add it to the agent's{" "}
            <Link className="text-link underline-offset-4 hover:underline" to="/agents">
              instructions
            </Link>
            .
          </>
        }
        title="Memory"
      />
      <div className="flex flex-col gap-3">
        <Tabs
          value={filters.audience}
          onValueChange={(value: unknown) => {
            if (isOneOf(AUDIENCE_SET, value)) {
              changeFilters({ ...baseFilters, audience: value, agentId: "" })
            }
          }}
        >
          <TabsList aria-label="Who can see the memories" variant="line">
            {AUDIENCE_TABS.map((audience) => (
              <TabsTrigger key={audience} value={audience}>
                {MEMORY_AUDIENCE_LABELS[audience]}
                <span className="text-muted-foreground text-xs tabular-nums">
                  {data.audience_counts[audience].toLocaleString()}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <p className="text-muted-foreground text-sm">{AUDIENCE_NOTES[filters.audience]}</p>
        <MemoryToolbar
          agents={agentsData.agents}
          filters={filters}
          onFiltersChange={changeFilters}
          onSearchChange={setSearchInput}
          search={searchInput}
        />
      </div>
      <div aria-busy={isChangingView} className={isChangingView ? "opacity-60" : undefined}>
        <MemoriesTable
          empty={
            narrowed ? (
              <EmptyState
                action={
                  <Button
                    onClick={() => {
                      setSearchInput("")
                      changeFilters({ ...DEFAULT_MEMORY_FILTERS, audience: filters.audience })
                    }}
                    type="button"
                    variant="outline"
                  >
                    Clear Filters
                  </Button>
                }
                description="Try other words, or clear the filters to see everything in this tab."
                icon={<SearchXIcon className="size-5" />}
                size="compact"
                title="No Memories Match"
              />
            ) : (
              <EmptyState
                description={EMPTY_DESCRIPTIONS[filters.audience]}
                icon={<BrainIcon className="size-5" />}
                title="Nothing Remembered Yet"
              />
            )
          }
          limit={MEMORY_PAGE_SIZE}
          memories={data.memories}
          offset={offset}
          onOpen={setSelectedMemoryId}
          onPageChange={(nextOffset) => {
            startTransition(() => {
              setOffset(nextOffset)
            })
          }}
          total={data.total}
        />
      </div>
      {selectedMemoryId ? (
        <MemoryDetailDialog
          canEdit={canEditWorkspace(role)}
          isManager={canManageWorkspace(role)}
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

const AUDIENCE_NOTES: Record<MemoryAudience, string> = {
  shared:
    "Everyone in this workspace can see these, and agents use them in anyone's conversations.",
  private: "Only you can see these, and agents use them only in your own conversations.",
}

const EMPTY_DESCRIPTIONS: Record<MemoryAudience, string> = {
  shared:
    "Agents save details here as they work. Everyone in this workspace can see shared memories, and the ones that relate to a conversation come up in it automatically.",
  private:
    "Agents save details that are only about you here, such as your preferences. Only you can see them.",
}
