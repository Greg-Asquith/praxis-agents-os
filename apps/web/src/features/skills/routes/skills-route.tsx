// apps/web/src/features/skills/routes/skills-route.tsx

import { useTransition } from "react"
import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { DebouncedSearchInput } from "@/components/forms/debounced-search-input"
import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useSkillsQuery } from "@/features/skills/api/list-skills"
import { SkillsTable } from "@/features/skills/components/skills-table"
import { normalisePagedSearch, type PagedSearch } from "@/lib/list-search"

const PAGE_SIZE = 25

export function SkillsRoute() {
  const search = useSearch({ from: "/app/skills" })
  const navigate = useNavigate()
  const [isChangingView, startTransition] = useTransition()
  const query = search.q ?? ""
  const offset = ((search.page ?? 1) - 1) * PAGE_SIZE
  const { data } = useSkillsQuery({
    includeInactive: true,
    limit: PAGE_SIZE,
    offset,
    ...(query ? { search: query } : {}),
  })
  const hasSkills = data.total > 0 || query !== ""

  function navigateTo(next: PagedSearch) {
    startTransition(() => {
      void navigate({ to: "/skills", search: normalisePagedSearch(next) })
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasSkills ? (
            <Button render={<Link to="/skills/new" />}>
              <PlusIcon data-icon="inline-start" />
              New Skill
            </Button>
          ) : null
        }
        description="Package reusable instructions and reference documents for agents."
        title="Skills"
      />

      {hasSkills ? (
        <DebouncedSearchInput
          ariaLabel="Search skills"
          disabled={isChangingView}
          onChange={(nextQuery) => {
            navigateTo({ q: nextQuery })
          }}
          placeholder="Search skills"
          value={query}
        />
      ) : null}

      <div aria-busy={isChangingView}>
        <SkillsTable
          limit={data.limit}
          offset={data.offset}
          onPageChange={(nextOffset) => {
            navigateTo({ ...search, page: Math.floor(nextOffset / PAGE_SIZE) + 1 })
          }}
          query={query}
          skills={data.skills}
          total={data.total}
        />
      </div>
    </div>
  )
}
