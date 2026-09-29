// apps/web/src/features/skills/routes/skills-route.tsx

import { Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"
import { useState } from "react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useSkillsQuery } from "@/features/skills/api/list-skills"
import { SkillsTable } from "@/features/skills/components/skills-table"

const PAGE_SIZE = 50

export function SkillsRoute() {
  const [offset, setOffset] = useState(0)
  const { data } = useSkillsQuery({ includeInactive: true, limit: PAGE_SIZE, offset })
  const hasSkills = data.total > 0

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

      <SkillsTable
        limit={data.limit}
        offset={data.offset}
        onPageChange={setOffset}
        skills={data.skills}
        total={data.total}
      />
    </div>
  )
}
