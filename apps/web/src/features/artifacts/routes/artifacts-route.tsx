// apps/web/src/features/artifacts/routes/artifacts-route.tsx

import { useTransition } from "react"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { useSuspenseQueries, useSuspenseQuery } from "@tanstack/react-query"

import { DebouncedSearchInput } from "@/components/forms/debounced-search-input"
import { PageHeader } from "@/components/shell/page-header"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { artifactsQueryOptions } from "@/features/artifacts/api/list-artifacts"
import { platformArtifactsQueryOptions } from "@/features/artifacts/api/platform-list-artifacts"
import { ArtifactsTable, type ArtifactRow } from "@/features/artifacts/components/artifacts-table"
import type { ArtifactsSearch } from "@/features/artifacts/search"
import type { ArtifactScopeFilter } from "@/features/artifacts/types"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import type { SearchPatch } from "@/lib/list-search"

const PAGE_SIZE = 25

// Drops default values so the URL only carries state that differs from a fresh visit.
function normaliseSearch(next: SearchPatch<ArtifactsSearch>): ArtifactsSearch {
  return {
    ...(next.direction === "asc" ? { direction: next.direction } : {}),
    ...(next.page && next.page > 1 ? { page: next.page } : {}),
    ...(next.q ? { q: next.q } : {}),
    ...(next.scope ? { scope: next.scope } : {}),
    ...(next.sort && next.sort !== "updated_at" ? { sort: next.sort } : {}),
  }
}

// The management list ignores the search text, so its empty state must not blame the query.
function emptyStateCopy(scope: ArtifactScopeFilter, query: string, platformManagement: boolean) {
  if (query && !platformManagement) {
    return {
      emptyDescription: "Try a different word, or clear the search to see everything.",
      emptyTitle: "No matching artifacts",
    }
  }
  if (scope !== "platform") return {}
  return {
    emptyDescription: platformManagement
      ? "Publish a workspace artifact to make it available in every workspace."
      : "Artifacts shared with every workspace appear here.",
    emptyTitle: "No shared artifacts",
  }
}

export function ArtifactsRoute() {
  const { workspace } = useActiveWorkspace()
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const search = useSearch({ from: "/app/artifacts" })
  const navigate = useNavigate()
  const [isChangingView, startTransition] = useTransition()
  const scope: ArtifactScopeFilter = search.scope ?? "all"
  const page = search.page ?? 1
  const sortBy = search.sort ?? "updated_at"
  const sortDirection = search.direction ?? "desc"
  const query = search.q ?? ""
  const platformManagement = scope === "platform" && user.is_super_admin
  const offset = (page - 1) * PAGE_SIZE
  const [{ data }] = useSuspenseQueries({
    queries: [
      platformManagement
        ? platformArtifactsQueryOptions({ limit: PAGE_SIZE, offset })
        : artifactsQueryOptions({
            limit: PAGE_SIZE,
            offset,
            sortBy,
            sortDirection,
            ...(query ? { search: query } : {}),
            ...(scope === "all" ? {} : { scope }),
          }),
    ],
  })
  const artifacts: ArtifactRow[] = data.items

  function navigateTo(next: SearchPatch<ArtifactsSearch>) {
    startTransition(() => {
      void navigate({ to: "/artifacts", search: normaliseSearch(next) })
    })
  }

  function updateScope(value: unknown) {
    if (value !== "all" && value !== "workspace" && value !== "platform") return
    navigateTo({ ...search, page: undefined, scope: value === "all" ? undefined : value })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description="Reports, pages, and other durable work your agents create, with every version kept."
        title="Artifacts"
      />
      <div className="flex flex-wrap items-center gap-3">
        {platformManagement ? null : (
          <DebouncedSearchInput
            ariaLabel="Search artifacts"
            disabled={isChangingView}
            onChange={(nextQuery) => {
              navigateTo({ ...search, page: undefined, q: nextQuery })
            }}
            placeholder="Search artifacts"
            value={query}
          />
        )}
        <Tabs onValueChange={updateScope} value={scope}>
          <TabsList aria-label="Which artifacts to show">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger className="max-w-48" value="workspace">
              <span className="truncate">{workspace.name}</span>
            </TabsTrigger>
            <TabsTrigger value="platform">Shared</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {scope === "platform" ? (
        <p className="text-muted-foreground max-w-xl text-sm">
          {platformManagement
            ? "Shared artifacts are available in every workspace. Withdrawn artifacts stay listed here until you publish or delete them."
            : "Shared artifacts are available in every workspace. Workspace editors can edit them for everyone or make a workspace copy."}
        </p>
      ) : null}
      <ArtifactsTable
        artifacts={artifacts}
        isChangingView={isChangingView}
        limit={PAGE_SIZE}
        management={platformManagement}
        offset={offset}
        onOpenArtifact={(artifact) => {
          void navigate({
            to: "/artifacts/$artifactId",
            params: { artifactId: artifact.id },
            search: platformManagement ? { platform: true } : {},
          })
        }}
        onPageChange={(nextOffset) => {
          navigateTo({ ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 })
        }}
        onSortChange={(sort, direction) => {
          navigateTo({ ...search, direction, page: undefined, sort })
        }}
        sortBy={sortBy}
        sortDirection={sortDirection}
        total={data.total}
        {...emptyStateCopy(scope, query, platformManagement)}
      />
    </div>
  )
}
