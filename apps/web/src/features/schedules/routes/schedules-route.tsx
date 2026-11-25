// apps/web/src/features/schedules/routes/schedules-route.tsx

import { useTransition } from "react"
import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { DebouncedSearchInput } from "@/components/forms/debounced-search-input"
import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"
import { SchedulesTable } from "@/features/schedules/components/schedules-table"
import { normalisePagedSearch, type PagedSearch } from "@/lib/list-search"

const PAGE_SIZE = 25

export function SchedulesRoute() {
  const search = useSearch({ from: "/app/schedules" })
  const navigate = useNavigate()
  const [isChangingView, startTransition] = useTransition()
  const query = search.q ?? ""
  const offset = ((search.page ?? 1) - 1) * PAGE_SIZE
  const { data: schedulesData } = useSchedulesQuery({
    includeInactive: true,
    limit: PAGE_SIZE,
    offset,
    ...(query ? { search: query } : {}),
  })
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const hasSchedules = schedulesData.total > 0 || query !== ""

  function navigateTo(next: PagedSearch) {
    startTransition(() => {
      void navigate({ to: "/schedules", search: normalisePagedSearch(next) })
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasSchedules ? (
            <Button render={<Link to="/schedules/new" />}>
              <PlusIcon data-icon="inline-start" />
              New Schedule
            </Button>
          ) : null
        }
        description="Create and monitor unattended agent runs across this workspace."
        title="Schedules"
      />

      {hasSchedules ? (
        <DebouncedSearchInput
          ariaLabel="Search schedules"
          disabled={isChangingView}
          onChange={(nextQuery) => {
            navigateTo({ q: nextQuery })
          }}
          placeholder="Search schedules"
          value={query}
        />
      ) : null}

      <div aria-busy={isChangingView} className="flex flex-col gap-3">
        <SchedulesTable agents={agentsData.agents} query={query} schedules={schedulesData.items} />
        {schedulesData.total > 0 ? (
          <PaginationControls
            ariaLabel="Schedules pagination"
            disabled={isChangingView}
            limit={PAGE_SIZE}
            offset={offset}
            onPageChange={(nextOffset) => {
              navigateTo({ ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 })
            }}
            total={schedulesData.total}
          />
        ) : null}
      </div>
    </div>
  )
}
