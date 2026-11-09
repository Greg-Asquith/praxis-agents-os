// apps/web/src/components/data-table/data-table-toolbar.tsx

import type { DataTableTab } from "@/components/data-table/filter"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/** Filter tabs with counts, beside an optional search box. */
export function DataTableToolbar({
  activeTab,
  counts,
  onSearch,
  onTab,
  search,
  tabs,
}: {
  activeTab: string | undefined
  counts: ReadonlyMap<string, number>
  onSearch: ((value: string) => void) | undefined
  onTab: (id: string) => void
  search: string
  tabs: readonly DataTableTab[]
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div aria-label="Filter rows" className="flex flex-wrap gap-1" role="group">
        {tabs.map((tab) => (
          <Button
            aria-pressed={tab.id === activeTab}
            key={tab.id}
            onClick={() => {
              onTab(tab.id)
            }}
            size="sm"
            type="button"
            variant={tab.id === activeTab ? "secondary" : "ghost"}
          >
            {tab.label}
            <span className="text-muted-foreground tabular-nums">
              {String(counts.get(tab.id) ?? 0)}
            </span>
          </Button>
        ))}
      </div>
      {onSearch ? (
        <Input
          aria-label="Search rows"
          className="h-8 w-full text-sm sm:w-56"
          onChange={(event) => {
            onSearch(event.currentTarget.value)
          }}
          placeholder="Search…"
          type="search"
          value={search}
        />
      ) : null}
    </div>
  )
}
